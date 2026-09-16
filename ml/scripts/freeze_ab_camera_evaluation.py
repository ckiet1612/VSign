from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ml.scripts.audit_frozen_camera_capture import audit_capture


IDLE_LABEL = "Không ký hiệu"
DEFAULT_RAW_DIR = Path("ml/data/evaluation/frozen_camera_v4/raw")
DEFAULT_PLAN = Path("ml/data/evaluation/frozen_camera_v4/capture_plan.csv")
DEFAULT_OUTPUT = Path("ml/data/evaluation/frozen_camera_v4/ab_manifest.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _model_entry(model: Path, labels: Path, version: str, schema: str) -> dict[str, str]:
    if not model.is_file() or not labels.is_file():
        raise FileNotFoundError(f"Thiếu artifact A/B: {model} hoặc {labels}")
    return {
        "version": version,
        "feature_schema": schema,
        "model": _repo_path(model),
        "model_sha256": sha256(model),
        "labels": _repo_path(labels),
        "labels_sha256": sha256(labels),
    }


def _local_samples(raw_dir: Path, plan: Path) -> list[dict[str, Any]]:
    with plan.open(encoding="utf-8", newline="") as handle:
        plan_rows = list(csv.DictReader(handle))
    metadata_paths = sorted(raw_dir.rglob("*.json")) if raw_dir.exists() else []
    metadata = [json.loads(path.read_text(encoding="utf-8")) for path in metadata_paths]
    missing, unexpected = audit_capture(plan_rows, metadata)
    if missing or unexpected:
        raise RuntimeError(
            f"Bộ camera chưa khớp capture plan: thiếu {sum(missing.values())}, "
            f"ngoài lịch/trùng {sum(unexpected.values())}"
        )
    samples: list[dict[str, Any]] = []
    for metadata_path, item in zip(metadata_paths, metadata):
        video = metadata_path.with_suffix(".mp4")
        if not video.is_file():
            raise FileNotFoundError(f"Thiếu video cho metadata: {metadata_path}")
        if int(item.get("frame_count", 0)) < 8:
            raise ValueError(f"Clip không đủ frame nguồn cho A/B: {video}")
        samples.append(
            {
                "sample_id": str(item.get("sample_id", video.stem)),
                "video": _repo_path(video),
                "video_sha256": sha256(video),
                "metadata": _repo_path(metadata_path),
                "metadata_sha256": sha256(metadata_path),
                "expected_label": str(item["expected_label"]),
                "is_negative": str(item["expected_label"]) == IDLE_LABEL,
                "hand": str(item.get("hand", "unknown")),
                "distance": str(item.get("distance", "unspecified")),
                "lighting": str(item.get("lighting", "unspecified")),
                "negative_action": str(item.get("negative_action") or "none"),
            }
        )
    return samples


def _indexed_samples(dataset: Path, video_root: Path) -> list[dict[str, Any]]:
    data = np.load(dataset, allow_pickle=False)
    label_names = data["label_names"].astype(str)
    labels = data["labels"].astype(np.int64)
    paths = data["paths"].astype(str)
    source_labels = (
        data["source_labels"].astype(str)
        if "source_labels" in data.files
        else label_names[labels]
    )
    samples: list[dict[str, Any]] = []
    for index, (target, relative, source_label) in enumerate(
        zip(labels.tolist(), paths.tolist(), source_labels.tolist())
    ):
        video = video_root / relative
        if not video.is_file():
            raise FileNotFoundError(f"Thiếu video index {index}: {video}")
        expected = str(label_names[int(target)])
        samples.append(
            {
                "sample_id": f"indexed-{index:04d}",
                "video": _repo_path(video),
                "video_sha256": sha256(video),
                "metadata": None,
                "metadata_sha256": None,
                "expected_label": expected,
                "source_label": str(source_label),
                "is_negative": expected == IDLE_LABEL,
                "hand": "unknown",
                "distance": "unspecified",
                "lighting": "unspecified",
                "negative_action": "other_sign" if expected == IDLE_LABEL else "none",
            }
        )
    return samples


def _training_overlap(
    samples: list[dict[str, Any]], training_video_dir: Path
) -> list[str]:
    if not training_video_dir.exists():
        return []
    training_hashes = {
        sha256(path): path for path in training_video_dir.rglob("*.mp4")
    }
    return [
        f"{sample['video']} == {training_hashes[sample['video_sha256']]}"
        for sample in samples
        if sample["video_sha256"] in training_hashes
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Khóa video, model, threshold và cổng A/B V3–V4.2 trước khi xem kết quả"
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--index-dataset", type=Path)
    parser.add_argument(
        "--video-root",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/dataset"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--selection-role",
        choices=("release_gate", "auxiliary_only"),
        default="release_gate",
    )
    parser.add_argument(
        "--training-video-dir",
        type=Path,
        default=Path("ml/data/collected/webcam"),
        help="Denylist chống đưa clip train/development vào release gate",
    )
    parser.add_argument(
        "--v3-model", type=Path, default=Path("ml/artifacts/landmark_v3/model.onnx")
    )
    parser.add_argument(
        "--v3-labels", type=Path, default=Path("ml/artifacts/landmark_v3/labels.json")
    )
    parser.add_argument(
        "--v4-model", type=Path, default=Path("ml/artifacts/landmark_v4/model.onnx")
    )
    parser.add_argument(
        "--v4-labels", type=Path, default=Path("ml/artifacts/landmark_v4/labels.json")
    )
    parser.add_argument(
        "--hand-model",
        type=Path,
        default=Path("apps/web/public/models/hand_landmarker.task"),
    )
    parser.add_argument(
        "--pose-model",
        type=Path,
        default=Path("apps/web/public/models/pose_landmarker_lite.task"),
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Manifest A/B đã tồn tại, không ghi đè: {args.output}")
    if args.index_dataset is not None and args.selection_role != "auxiliary_only":
        raise ValueError("Dataset public/indexed chỉ được phép mang vai trò auxiliary_only")

    samples = (
        _indexed_samples(args.index_dataset, args.video_root)
        if args.index_dataset is not None
        else _local_samples(args.raw_dir, args.plan)
    )
    positives = Counter(
        sample["expected_label"] for sample in samples if not sample["is_negative"]
    )
    negative_count = sum(bool(sample["is_negative"]) for sample in samples)
    if args.selection_role == "release_gate":
        if len(positives) != 20 or min(positives.values(), default=0) < 3:
            raise ValueError("Release gate cần đủ 20 từ và ít nhất 3 clip/từ")
        if negative_count < 30:
            raise ValueError("Release gate cần ít nhất 30 clip negative")
        overlaps = _training_overlap(samples, args.training_video_dir)
        if overlaps:
            raise ValueError(
                "Release gate trùng video train/development:\n" + "\n".join(overlaps)
            )

    manifest = {
        "schema_version": "1.0",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "selection_role": args.selection_role,
        "source": (
            {
                "kind": "indexed_public_video",
                "index_dataset": _repo_path(args.index_dataset),
                "index_dataset_sha256": sha256(args.index_dataset),
                "video_root": _repo_path(args.video_root),
            }
            if args.index_dataset is not None
            else {
                "kind": "local_frozen_camera",
                "raw_dir": _repo_path(args.raw_dir),
                "capture_plan": _repo_path(args.plan),
                "capture_plan_sha256": sha256(args.plan),
            }
        ),
        "models": {
            "v3": _model_entry(
                args.v3_model,
                args.v3_labels,
                "landmark-keyframe-v3-personalized",
                "16x128",
            ),
            "v4_2": _model_entry(
                args.v4_model,
                args.v4_labels,
                "unified-landmark-v4.2-personalized",
                "16x183",
            ),
        },
        "feature_extraction": {
            "hand_model": _repo_path(args.hand_model),
            "hand_model_sha256": sha256(args.hand_model),
            "hand_running_mode": "VIDEO",
            "hand_delegate": "GPU_or_CPU_browser",
            "hand_tracking_interval_ms": 30,
            "pose_model": _repo_path(args.pose_model),
            "pose_model_sha256": sha256(args.pose_model),
            "pose_running_mode": "IMAGE",
            "pose_delegate": "CPU",
            "pose_refresh_interval_ms": 60,
            "note": (
                "V4.2 was trained with IMAGE-mode pose. VIDEO-mode pose is a known "
                "train-serving skew that attracts unrelated signs to Đâu."
            ),
        },
        "modes": {
            "manual": {
                "sampling": "motion-weighted full clip, paired source indices",
                "thresholds": {"confidence": 0.56, "margin": 0.18},
            },
            "automatic": {
                "sampling": "browser auto-segmentation parity replay, paired source indices",
                "thresholds": {"confidence": 0.66, "margin": 0.24},
            },
        },
        "minimum_detected_hand_frames": 4,
        "release_gate": {
            "minimum_positive_per_label": 3,
            "minimum_negative": 30,
            "maximum_negative_false_accept_rate": 0.05,
            "require_v4_noninferior_each_mode": [
                "raw_top1_accuracy_positive",
                "accepted_correct_rate_positive",
                "accepted_accuracy_positive",
            ],
            "require_v4_not_higher_each_mode": [
                "positive_rejection_rate",
                "negative_false_accept_rate",
                "wrong_to_dau_rate_positive",
            ],
            "strict_improvement_required": True,
        },
        "sample_count": len(samples),
        "positive_count": len(samples) - negative_count,
        "negative_count": negative_count,
        "training_overlap_check": {
            "training_video_dir": _repo_path(args.training_video_dir),
            "matched_sha256_count": 0 if args.selection_role == "release_gate" else None,
        },
        "positive_by_label": dict(sorted(positives.items())),
        "samples": samples,
        "policy": (
            (
                "Bộ này chỉ dùng A/B và chọn runtime theo cổng đã khóa. "
                if args.selection_role == "release_gate"
                else "Bộ auxiliary này chỉ dùng chẩn đoán và không có quyền chọn runtime. "
            )
            + "Cấm dùng video, feature, prediction, confusion hoặc threshold từ đây "
            "để train, early-stop, calibrate hay điều chỉnh model."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Đã khóa {len(samples)} video A/B tại {args.output}")
    print(f"Vai trò: {args.selection_role}; positive={manifest['positive_count']}, negative={negative_count}")


if __name__ == "__main__":
    main()
