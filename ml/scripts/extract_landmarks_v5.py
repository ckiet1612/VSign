from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

import av
import mediapipe as mp
import numpy as np

from ml.ab_evaluation import motion_weighted_sample_indices, v4_landmark_motion
from ml.landmarks_v2 import pack_landmarks as pack_landmarks_v3
from ml.landmarks_v4 import (
    FEATURE_DIM as V4_FEATURE_DIM,
    POSE_PRESENCE_OFFSET,
    pack_landmarks_v4,
)
from ml.landmarks_v5 import (
    FEATURE_DIM,
    SEQUENCE_LENGTH,
    combine_v3_v4_sequences,
)


def manifest_rows(
    path: Path, labels: set[str]
) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    invalid = sorted({row.get("split", "") for row in rows} - {"train", "validation", "test"})
    if invalid:
        raise ValueError(f"Manifest có split không hợp lệ: {invalid}")
    # Test is intentionally unavailable to this extractor.
    return [
        row
        for row in rows
        if row.get("label") in labels and row.get("split") in {"train", "validation"}
    ]


def read_frames(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        frames = [
            frame.to_ndarray(format="rgb24")
            for frame in container.decode(video=0)
        ]
    if not frames:
        raise ValueError(f"Video không có frame: {path}")
    return frames


def extract_frame(
    hand_detector: Any,
    pose_detector: Any,
    frame: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=np.ascontiguousarray(frame),
    )
    hand_result = hand_detector.detect(image)
    pose_result = pose_detector.detect(image)
    hands = [
        [(point.x, point.y, point.z) for point in landmarks]
        for landmarks in hand_result.hand_landmarks
    ]
    pose = None
    if pose_result.pose_landmarks:
        pose = [
            (
                point.x,
                point.y,
                point.z,
                float(point.visibility if point.visibility is not None else 1.0),
            )
            for point in pose_result.pose_landmarks[0]
        ]
    return pack_landmarks_v3(hands), pack_landmarks_v4(hands, pose)


def sample_detected_sequence(
    v3_frames: list[np.ndarray], v4_frames: list[np.ndarray]
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    if len(v3_frames) != len(v4_frames) or not v3_frames:
        raise ValueError("Chuỗi V3/V4 phải có cùng số frame và không được rỗng")
    scores = [
        0.0
        if index == 0
        else v4_landmark_motion(v4_frames[index - 1], v4_frames[index])
        for index in range(len(v4_frames))
    ]
    indices = motion_weighted_sample_indices(
        len(v4_frames), scores, SEQUENCE_LENGTH
    )
    v3 = np.stack([v3_frames[index] for index in indices]).astype(np.float32)
    v4 = np.stack([v4_frames[index] for index in indices]).astype(np.float32)
    return v3, v4, indices


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trích exact V3 + body context cho VSign V5"
    )
    parser.add_argument(
        "--input-dir", type=Path, default=Path("ml/data/collected/webcam")
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Nếu có, chỉ trích public train/validation; public test luôn bị loại",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/dataset"),
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=Path("ml/artifacts/visignlanguage_common20/labels.json"),
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
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/data/processed/landmarks_v5/collected_common20.npz"),
    )
    parser.add_argument("--minimum-hand-confidence", type=float, default=0.35)
    parser.add_argument("--minimum-pose-confidence", type=float, default=0.30)
    args = parser.parse_args()

    source_root = args.dataset_root if args.manifest else args.input_dir
    if "evaluation" in source_root.resolve().parts:
        raise ValueError("Không được trích bộ evaluation bằng pipeline train V5")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("labels.json phải là một mảng chuỗi")
    labels = [label for label in labels if label != "Không ký hiệu"]
    label_to_index = {label: index for index, label in enumerate(labels)}

    items: list[dict[str, str]] = []
    if args.manifest:
        for row in manifest_rows(args.manifest, set(labels)):
            items.append(
                {
                    "path": row["path"],
                    "label": row["label"],
                    "hand": "unknown",
                    "split": row["split"],
                    "group_id": row.get("group_id", row["path"]),
                    "distance": "public",
                    "lighting": "public",
                }
            )
    else:
        for video_path in sorted(args.input_dir.rglob("*.mp4")):
            metadata_path = video_path.with_suffix(".json")
            if not metadata_path.is_file():
                raise FileNotFoundError(f"Thiếu metadata: {metadata_path}")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            label = metadata.get("expected_label")
            if label == "Không ký hiệu":
                continue
            if label not in label_to_index:
                raise ValueError(f"Nhãn ngoài common-20 tại {metadata_path}: {label!r}")
            items.append(
                {
                    "path": str(video_path.relative_to(args.input_dir)),
                    "label": str(label),
                    "hand": str(metadata.get("hand", "unknown")),
                    "split": "",
                    "group_id": str(video_path.relative_to(args.input_dir)),
                    "distance": str(metadata.get("distance", "unspecified")),
                    "lighting": str(metadata.get("lighting", "unspecified")),
                }
            )
    if not items:
        raise FileNotFoundError("Không tìm thấy video common-20 để trích V5")

    os.environ.setdefault("GLOG_minloglevel", "2")
    hand_options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(args.hand_model),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=args.minimum_hand_confidence,
        min_hand_presence_confidence=args.minimum_hand_confidence,
        min_tracking_confidence=args.minimum_hand_confidence,
    )
    pose_options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(args.pose_model),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=args.minimum_pose_confidence,
        min_pose_presence_confidence=args.minimum_pose_confidence,
        min_tracking_confidence=args.minimum_pose_confidence,
        output_segmentation_masks=False,
    )

    sequences: list[np.ndarray] = []
    targets: list[int] = []
    detected_hands: list[int] = []
    detected_pose: list[int] = []
    source_frame_counts: list[int] = []
    with (
        mp.tasks.vision.HandLandmarker.create_from_options(hand_options) as hand_detector,
        mp.tasks.vision.PoseLandmarker.create_from_options(pose_options) as pose_detector,
    ):
        for item_index, item in enumerate(items, start=1):
            video_path = source_root / item["path"]
            frames = read_frames(video_path)
            v3_frames: list[np.ndarray] = []
            v4_frames: list[np.ndarray] = []
            for frame in frames:
                v3_frame, v4_frame = extract_frame(
                    hand_detector, pose_detector, frame
                )
                v3_frames.append(v3_frame)
                v4_frames.append(v4_frame)
            v3, v4, _ = sample_detected_sequence(v3_frames, v4_frames)
            sequence = combine_v3_v4_sequences(v3, v4)
            if sequence.shape != (SEQUENCE_LENGTH, FEATURE_DIM):
                raise AssertionError(f"Feature V5 sai shape: {sequence.shape}")
            sequences.append(sequence)
            targets.append(label_to_index[item["label"]])
            detected_hands.append(int((v3[:, -2:].max(axis=1) > 0.5).sum()))
            detected_pose.append(
                int((v4[:, POSE_PRESENCE_OFFSET:].max(axis=1) > 0.5).sum())
            )
            source_frame_counts.append(len(frames))
            if item_index % 20 == 0 or item_index == len(items):
                print(f"Đã trích V5 {item_index}/{len(items)} video", flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    values: dict[str, np.ndarray] = {
        "sequences": np.stack(sequences).astype(np.float32),
        "labels": np.asarray(targets, dtype=np.int64),
        "hands": np.asarray([item["hand"] for item in items]),
        "paths": np.asarray([item["path"] for item in items]),
        "group_ids": np.asarray([item["group_id"] for item in items]),
        "distances": np.asarray([item["distance"] for item in items]),
        "lighting": np.asarray([item["lighting"] for item in items]),
        "detected_hand_frames": np.asarray(detected_hands, dtype=np.int64),
        "detected_pose_frames": np.asarray(detected_pose, dtype=np.int64),
        "source_frame_counts": np.asarray(source_frame_counts, dtype=np.int64),
        "label_names": np.asarray(labels),
        "feature_schema": np.asarray("vsign-v5-exact-v3-plus-context57"),
    }
    if args.manifest:
        values["splits"] = np.asarray([item["split"] for item in items])
    np.savez_compressed(args.output, **values)
    print(f"Đã lưu {len(sequences)} chuỗi V5 vào {args.output}")


if __name__ == "__main__":
    main()
