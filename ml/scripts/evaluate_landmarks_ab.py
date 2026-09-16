from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import av
import mediapipe as mp
import numpy as np
import onnxruntime as ort

from ml.ab_evaluation import PairedFrame, automatic_sequence, manual_sequence
from ml.landmarks_v2 import FEATURE_DIM as V3_FEATURE_DIM, hand_presence, mirror_sequence
from ml.landmarks_v2 import pack_landmarks as pack_landmarks_v3
from ml.landmarks_v4 import (
    FEATURE_DIM as V4_FEATURE_DIM,
    HAND_PRESENCE_OFFSET,
    POSE_PRESENCE_OFFSET,
    mirror_sequence_v4,
    pack_landmarks_v4,
)


IDLE_LABEL = "Không ký hiệu"
REJECTED_LABEL = "Rejected"
TARGET_TRACKING_INTERVAL_MS = 30.0
# Browser parity: V4.2 was trained with independent IMAGE-mode pose detections.
# The hand tracker remains VIDEO mode for low-latency drawing and stable hands.
POSE_INTERVAL_MS = 60.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    values = np.exp(shifted)
    return values / values.sum()


def _read_tracking_frames(path: Path) -> list[tuple[float, np.ndarray]]:
    output: list[tuple[float, np.ndarray]] = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        fallback_rate = float(stream.average_rate or 15.0)
        last_time = -1e9
        for index, frame in enumerate(container.decode(video=0)):
            timestamp = (
                float(frame.time) * 1000.0
                if frame.time is not None
                else index * 1000.0 / fallback_rate
            )
            if output and timestamp - last_time < TARGET_TRACKING_INTERVAL_MS:
                continue
            output.append((timestamp, frame.to_ndarray(format="rgb24")))
            last_time = timestamp
    if not output:
        raise ValueError(f"Video không có frame: {path}")
    initial = output[0][0]
    return [(timestamp - initial, frame) for timestamp, frame in output]


def _extract_video(
    path: Path,
    hand_model: Path,
    pose_model: Path,
) -> list[PairedFrame]:
    frames = _read_tracking_frames(path)
    hand_options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(hand_model),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.35,
        min_hand_presence_confidence=0.35,
        min_tracking_confidence=0.35,
    )
    pose_options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(pose_model),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=0.30,
        min_pose_presence_confidence=0.30,
        min_tracking_confidence=0.30,
        output_segmentation_masks=False,
    )
    output: list[PairedFrame] = []
    latest_pose: list[tuple[float, float, float, float]] | None = None
    last_pose_at = -POSE_INTERVAL_MS
    previous_timestamp = -1
    with (
        mp.tasks.vision.HandLandmarker.create_from_options(hand_options) as hand_detector,
        mp.tasks.vision.PoseLandmarker.create_from_options(pose_options) as pose_detector,
    ):
        for timestamp, pixels in frames:
            timestamp_ms = max(previous_timestamp + 1, int(round(timestamp)))
            previous_timestamp = timestamp_ms
            image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(pixels),
            )
            hand_result = hand_detector.detect_for_video(image, timestamp_ms)
            if timestamp_ms - last_pose_at >= POSE_INTERVAL_MS:
                pose_result = pose_detector.detect(image)
                latest_pose = None
                if pose_result.pose_landmarks:
                    latest_pose = [
                        (
                            point.x,
                            point.y,
                            point.z,
                            float(point.visibility if point.visibility is not None else 1.0),
                        )
                        for point in pose_result.pose_landmarks[0]
                    ]
                last_pose_at = timestamp_ms
            hands = [
                [(point.x, point.y, point.z) for point in landmarks]
                for landmarks in hand_result.hand_landmarks
            ]
            output.append(
                PairedFrame(
                    timestamp_ms=float(timestamp_ms),
                    v3=pack_landmarks_v3(hands),
                    v4=pack_landmarks_v4(hands, latest_pose),
                )
            )
    return output


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def _verify_manifest(manifest: dict[str, Any]) -> None:
    for model in manifest["models"].values():
        model_path = _resolve(model["model"])
        labels_path = _resolve(model["labels"])
        if sha256(model_path) != model["model_sha256"]:
            raise RuntimeError(f"Model đã đổi sau khi khóa manifest: {model_path}")
        if sha256(labels_path) != model["labels_sha256"]:
            raise RuntimeError(f"Labels đã đổi sau khi khóa manifest: {labels_path}")
    for sample in manifest["samples"]:
        video = _resolve(sample["video"])
        if sha256(video) != sample["video_sha256"]:
            raise RuntimeError(f"Video đã đổi sau khi khóa manifest: {video}")
        if sample.get("metadata"):
            metadata = _resolve(sample["metadata"])
            if sha256(metadata) != sample["metadata_sha256"]:
                raise RuntimeError(f"Metadata đã đổi sau khi khóa manifest: {metadata}")
    extraction = manifest.get("feature_extraction")
    if extraction:
        for key in ("hand", "pose"):
            model_path = _resolve(extraction[f"{key}_model"])
            if sha256(model_path) != extraction[f"{key}_model_sha256"]:
                raise RuntimeError(
                    f"MediaPipe {key} model đã đổi sau khi khóa manifest: {model_path}"
                )
        expected = {
            "hand_running_mode": "VIDEO",
            "hand_tracking_interval_ms": int(TARGET_TRACKING_INTERVAL_MS),
            "pose_running_mode": "IMAGE",
            "pose_delegate": "CPU",
            "pose_refresh_interval_ms": int(POSE_INTERVAL_MS),
        }
        mismatches = {
            key: (extraction.get(key), value)
            for key, value in expected.items()
            if extraction.get(key) != value
        }
        if mismatches:
            raise RuntimeError(f"Protocol trích feature không khớp manifest: {mismatches}")


def _model_prediction(
    session: ort.InferenceSession,
    sequence: np.ndarray,
    labels: list[str],
    model_key: str,
    confidence_threshold: float,
    margin_threshold: float,
    minimum_hand_frames: int,
) -> dict[str, Any]:
    if model_key == "v3":
        expected_shape = (16, V3_FEATURE_DIM)
        mirrored = mirror_sequence(sequence)
        detected_frames = int((hand_presence(sequence) > 0.5).sum())
    else:
        expected_shape = (16, V4_FEATURE_DIM)
        mirrored = mirror_sequence_v4(sequence)
        detected_frames = int(
            (
                sequence[
                    :, HAND_PRESENCE_OFFSET : HAND_PRESENCE_OFFSET + 2
                ].max(axis=1)
                > 0.5
            ).sum()
        )
    if sequence.shape != expected_shape:
        raise ValueError(f"Sequence {model_key} có shape sai: {sequence.shape}")
    batch = np.stack((sequence, mirrored)).astype(np.float32)
    logits = session.run(None, {"landmarks": batch})[0].mean(axis=0)
    probabilities = softmax(logits)
    ordering = np.argsort(-probabilities)
    top_index = int(ordering[0])
    confidence = float(probabilities[top_index])
    margin = confidence - float(probabilities[int(ordering[1])])
    raw_label = labels[top_index]
    accepted = bool(
        detected_frames >= minimum_hand_frames
        and raw_label != IDLE_LABEL
        and confidence >= confidence_threshold
        and margin >= margin_threshold
    )
    return {
        "detected_hand_frames": detected_frames,
        "raw_prediction": raw_label,
        "confidence": confidence,
        "margin": margin,
        "accepted": accepted,
        "accepted_label": raw_label if accepted else None,
        "top3": [
            {"label": labels[int(index)], "confidence": float(probabilities[int(index)])}
            for index in ordering[:3]
            if labels[int(index)] != IDLE_LABEL
        ][:3],
    }


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _summarize(rows: list[dict[str, Any]], common_labels: list[str]) -> dict[str, Any]:
    positive = [row for row in rows if not row["is_negative"]]
    negative = [row for row in rows if row["is_negative"]]
    accepted_positive = [row for row in positive if row["accepted"]]
    correct_positive = [row for row in positive if row["accepted"] and row["correct"]]
    raw_correct = [row for row in positive if row["raw_prediction"] == row["expected_label"]]
    wrong_to_dau = [
        row
        for row in positive
        if row["expected_label"] != "Đâu" and row["raw_prediction"] == "Đâu"
    ]
    non_dau_positive = [row for row in positive if row["expected_label"] != "Đâu"]

    columns = common_labels + [REJECTED_LABEL]
    expected_rows = common_labels + [IDLE_LABEL]
    confusion = np.zeros((len(expected_rows), len(columns)), dtype=np.int64)
    expected_index = {label: index for index, label in enumerate(expected_rows)}
    column_index = {label: index for index, label in enumerate(columns)}
    for row in rows:
        output = row["accepted_label"] or REJECTED_LABEL
        confusion[expected_index[row["expected_label"]], column_index[output]] += 1

    per_class: dict[str, dict[str, Any]] = {}
    for label in common_labels:
        selected = [row for row in positive if row["expected_label"] == label]
        accepted = [row for row in selected if row["accepted"]]
        correct = [row for row in selected if row["accepted"] and row["correct"]]
        attracted = [row for row in selected if label != "Đâu" and row["raw_prediction"] == "Đâu"]
        per_class[label] = {
            "samples": len(selected),
            "segmented_rate": _safe_rate(sum(row["segmented"] for row in selected), len(selected)),
            "raw_top1_accuracy": _safe_rate(
                sum(row["raw_prediction"] == label for row in selected), len(selected)
            ),
            "accepted_correct_rate": _safe_rate(len(correct), len(selected)),
            "accepted_accuracy": _safe_rate(len(correct), len(accepted)),
            "rejection_rate": _safe_rate(len(selected) - len(accepted), len(selected)),
            "raw_wrong_to_dau": len(attracted),
        }

    attracted_sources = Counter(row["expected_label"] for row in wrong_to_dau)
    negative_predictions = Counter(
        row["accepted_label"] for row in negative if row["accepted_label"]
    )
    return {
        "sample_count": len(rows),
        "positive_samples": len(positive),
        "negative_samples": len(negative),
        "segmented_rate_positive": _safe_rate(
            sum(row["segmented"] for row in positive), len(positive)
        ),
        "raw_top1_accuracy_positive": _safe_rate(len(raw_correct), len(positive)),
        "accepted_correct_rate_positive": _safe_rate(len(correct_positive), len(positive)),
        "accepted_accuracy_positive": _safe_rate(
            len(correct_positive), len(accepted_positive)
        ),
        "positive_rejection_rate": _safe_rate(
            len(positive) - len(accepted_positive), len(positive)
        ),
        "negative_false_accept_rate": _safe_rate(
            sum(row["accepted"] for row in negative), len(negative)
        ),
        "wrong_to_dau_count_positive": len(wrong_to_dau),
        "wrong_to_dau_rate_positive": _safe_rate(len(wrong_to_dau), len(non_dau_positive)),
        "accepted_wrong_to_dau_count_positive": sum(row["accepted"] for row in wrong_to_dau),
        "dau_attraction_sources": dict(sorted(attracted_sources.items())),
        "negative_accepted_predictions": dict(sorted(negative_predictions.items())),
        "per_class": per_class,
        "confusion_rows": expected_rows,
        "confusion_columns": columns,
        "confusion_matrix": confusion.tolist(),
    }


def _compare_and_gate(
    metrics: dict[str, dict[str, dict[str, Any]]],
    gate: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    strictly_better = False
    for mode in ("manual", "automatic"):
        v3 = metrics[mode]["v3"]
        v4 = metrics[mode]["v4_2"]
        for key in gate["require_v4_noninferior_each_mode"]:
            passed = v4[key] is not None and v3[key] is not None and v4[key] >= v3[key]
            strictly_better |= bool(passed and v4[key] > v3[key])
            checks.append(
                {"mode": mode, "metric": key, "rule": "v4>=v3", "v3": v3[key], "v4_2": v4[key], "passed": passed}
            )
        for key in gate["require_v4_not_higher_each_mode"]:
            passed = v4[key] is not None and v3[key] is not None and v4[key] <= v3[key]
            strictly_better |= bool(passed and v4[key] < v3[key])
            checks.append(
                {"mode": mode, "metric": key, "rule": "v4<=v3", "v3": v3[key], "v4_2": v4[key], "passed": passed}
            )
        false_accept = v4["negative_false_accept_rate"]
        passed = false_accept is not None and false_accept <= gate["maximum_negative_false_accept_rate"]
        checks.append(
            {
                "mode": mode,
                "metric": "negative_false_accept_rate",
                "rule": f"v4<={gate['maximum_negative_false_accept_rate']}",
                "v3": v3["negative_false_accept_rate"],
                "v4_2": false_accept,
                "passed": passed,
            }
        )
    passed = all(check["passed"] for check in checks) and (
        strictly_better or not gate["strict_improvement_required"]
    )
    return {"passed": passed, "strictly_better": strictly_better, "checks": checks}


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# A/B VSign V3 và V4.2",
        "",
        f"- Vai trò: `{report['selection_role']}`",
        f"- Video: {report['sample_count']} ({report['positive_count']} positive, {report['negative_count']} negative)",
        f"- Quyết định runtime: **{report['runtime_decision']}**",
        f"- Cổng V4.2: **{'ĐẠT' if report['gate']['passed'] else 'KHÔNG ĐẠT'}**",
        "",
        "| Chế độ | Model | Top-1 | Correct accepted / all | Accuracy khi accepted | Rejection | False accept | Sai hút về Đâu |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in ("manual", "automatic"):
        for model in ("v3", "v4_2"):
            item = report["metrics"][mode][model]
            percent = lambda value: "—" if value is None else f"{value * 100:.1f}%"
            lines.append(
                f"| {mode} | {model} | {percent(item['raw_top1_accuracy_positive'])} | "
                f"{percent(item['accepted_correct_rate_positive'])} | "
                f"{percent(item['accepted_accuracy_positive'])} | "
                f"{percent(item['positive_rejection_rate'])} | "
                f"{percent(item['negative_false_accept_rate'])} | "
                f"{item['wrong_to_dau_count_positive']} |"
            )
    lines.extend(["", "## Theo từng từ", ""])
    for mode in ("manual", "automatic"):
        lines.extend(
            [
                f"### {mode}",
                "",
                "| Từ | V3 top-1 | V4.2 top-1 | V3 correct accepted | V4.2 correct accepted | V3→Đâu | V4.2→Đâu |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        labels = report["metrics"][mode]["v3"]["per_class"]
        for label in labels:
            v3 = report["metrics"][mode]["v3"]["per_class"][label]
            v4 = report["metrics"][mode]["v4_2"]["per_class"][label]
            percent = lambda value: "—" if value is None else f"{value * 100:.1f}%"
            lines.append(
                f"| {label} | {percent(v3['raw_top1_accuracy'])} | {percent(v4['raw_top1_accuracy'])} | "
                f"{percent(v3['accepted_correct_rate'])} | {percent(v4['accepted_correct_rate'])} | "
                f"{v3['raw_wrong_to_dau']} | {v4['raw_wrong_to_dau']} |"
            )
        lines.append("")
    lines.append(f"> {report['policy']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="A/B V3 và V4.2 trên cùng video đã khóa")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hand-model", type=Path, default=Path("apps/web/public/models/hand_landmarker.task"))
    parser.add_argument("--pose-model", type=Path, default=Path("apps/web/public/models/pose_landmarker_lite.task"))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Báo cáo A/B đã tồn tại, không ghi đè: {args.output}")
    for model in (args.hand_model, args.pose_model):
        if not model.is_file():
            raise FileNotFoundError(f"Thiếu MediaPipe model: {model}")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    _verify_manifest(manifest)
    extraction = manifest.get("feature_extraction")
    if extraction:
        expected_hand = _resolve(extraction["hand_model"]).resolve()
        expected_pose = _resolve(extraction["pose_model"]).resolve()
        if args.hand_model.resolve() != expected_hand or args.pose_model.resolve() != expected_pose:
            raise RuntimeError(
                "Evaluator phải dùng đúng MediaPipe model đã khóa trong manifest"
            )
    common_labels = json.loads(
        _resolve(manifest["models"]["v3"]["labels"]).read_text(encoding="utf-8")
    )
    v4_labels = json.loads(
        _resolve(manifest["models"]["v4_2"]["labels"]).read_text(encoding="utf-8")
    )
    if v4_labels[: len(common_labels)] != common_labels or IDLE_LABEL not in v4_labels:
        raise ValueError("Label V3/V4.2 không tương thích cho A/B")

    sessions = {
        key: ort.InferenceSession(
            str(_resolve(spec["model"])), providers=["CPUExecutionProvider"]
        )
        for key, spec in manifest["models"].items()
    }
    rows: dict[str, dict[str, list[dict[str, Any]]]] = {
        mode: {model: [] for model in sessions} for mode in ("manual", "automatic")
    }
    os.environ.setdefault("GLOG_minloglevel", "2")
    for sample_index, sample in enumerate(manifest["samples"], start=1):
        paired_frames = _extract_video(
            _resolve(sample["video"]), args.hand_model, args.pose_model
        )
        sequences = {
            "manual": manual_sequence(paired_frames),
            "automatic": automatic_sequence(paired_frames),
        }
        for mode, paired in sequences.items():
            thresholds = manifest["modes"][mode]["thresholds"]
            for model_key, session in sessions.items():
                sequence = None if paired is None else getattr(paired, "v3" if model_key == "v3" else "v4")
                if sequence is None:
                    prediction = {
                        "detected_hand_frames": 0,
                        "raw_prediction": None,
                        "confidence": None,
                        "margin": None,
                        "accepted": False,
                        "accepted_label": None,
                        "top3": [],
                    }
                else:
                    prediction = _model_prediction(
                        session,
                        sequence,
                        common_labels if model_key == "v3" else v4_labels,
                        model_key,
                        float(thresholds["confidence"]),
                        float(thresholds["margin"]),
                        int(manifest["minimum_detected_hand_frames"]),
                    )
                expected = sample["expected_label"]
                rows[mode][model_key].append(
                    {
                        "sample_id": sample["sample_id"],
                        "video": sample["video"],
                        "expected_label": expected,
                        "source_label": sample.get("source_label", expected),
                        "is_negative": bool(sample["is_negative"]),
                        "hand": sample.get("hand", "unknown"),
                        "distance": sample.get("distance", "unspecified"),
                        "lighting": sample.get("lighting", "unspecified"),
                        "negative_action": sample.get("negative_action", "none"),
                        "segmented": paired is not None,
                        "correct": prediction["accepted_label"] == expected,
                        **prediction,
                    }
                )
        if sample_index % 10 == 0 or sample_index == len(manifest["samples"]):
            print(f"Đã A/B {sample_index}/{len(manifest['samples'])} video", flush=True)

    metrics = {
        mode: {
            model: _summarize(model_rows, common_labels)
            for model, model_rows in model_group.items()
        }
        for mode, model_group in rows.items()
    }
    gate = _compare_and_gate(metrics, manifest["release_gate"])
    runtime_decision = (
        "not_authorized_auxiliary_only"
        if manifest["selection_role"] != "release_gate"
        else "v4_2"
        if gate["passed"]
        else "v3"
    )
    report = {
        "schema_version": "1.0",
        "manifest": str(args.manifest),
        "manifest_sha256": sha256(args.manifest),
        "selection_role": manifest["selection_role"],
        "sample_count": manifest["sample_count"],
        "positive_count": manifest["positive_count"],
        "negative_count": manifest["negative_count"],
        "feature_extraction": manifest.get("feature_extraction"),
        "metrics": metrics,
        "gate": gate,
        "runtime_decision": runtime_decision,
        "sample_results": rows,
        "policy": manifest["policy"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown = args.output.with_suffix(".md")
    markdown.write_text(_markdown_report(report), encoding="utf-8")
    print(_markdown_report(report))
    print(f"JSON: {args.output}")
    print(f"Markdown: {markdown}")


if __name__ == "__main__":
    main()
