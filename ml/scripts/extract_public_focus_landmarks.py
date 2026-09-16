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

from ml.landmarks_v2 import FEATURE_DIM, SEQUENCE_LENGTH, pack_landmarks


def sample_frames(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
    if not frames:
        raise ValueError(f"Video không có frame: {path}")
    indices = np.rint(np.linspace(0, len(frames) - 1, SEQUENCE_LENGTH)).astype(int)
    return [frames[index] for index in indices]


def extract_frame(detector: Any, frame: np.ndarray) -> np.ndarray:
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame))
    result = detector.detect(image)
    hands = [
        [(point.x, point.y, point.z) for point in landmarks]
        for landmarks in result.hand_landmarks
    ]
    return pack_landmarks(hands)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trích landmark công khai cho các nhãn cần sửa ranh giới"
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/dataset"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/common20_manifest.csv"),
    )
    parser.add_argument(
        "--label-map",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/common20_label_map.json"),
    )
    parser.add_argument(
        "--hand-model",
        type=Path,
        default=Path("apps/web/public/models/hand_landmarker.task"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/data/processed/landmarks_v3/public_school_chao.npz"),
    )
    parser.add_argument(
        "--focus-labels", nargs="+", default=["Trường học", "Chào"]
    )
    parser.add_argument("--minimum-detection-confidence", type=float, default=0.35)
    args = parser.parse_args()

    labels = json.loads(args.label_map.read_text(encoding="utf-8"))
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("Label map không hợp lệ")
    unknown = sorted(set(args.focus_labels) - set(labels))
    if unknown:
        raise ValueError(f"Nhãn focus không nằm trong common-20: {unknown}")
    label_to_index = {label: index for index, label in enumerate(labels)}

    with args.manifest.open(encoding="utf-8", newline="") as file:
        rows = [
            row
            for row in csv.DictReader(file)
            if row["label"] in args.focus_labels
        ]
    if not rows:
        raise ValueError("Không tìm thấy video focus trong manifest")

    os.environ.setdefault("GLOG_minloglevel", "2")
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(args.hand_model),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        ),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=args.minimum_detection_confidence,
        min_hand_presence_confidence=args.minimum_detection_confidence,
        min_tracking_confidence=args.minimum_detection_confidence,
    )

    sequences: list[np.ndarray] = []
    targets: list[int] = []
    paths: list[str] = []
    splits: list[str] = []
    groups: list[str] = []
    detected_frames: list[int] = []
    with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
        for index, row in enumerate(rows, start=1):
            path = args.dataset_root / row["path"]
            frames = sample_frames(path)
            sequence = np.stack([extract_frame(detector, frame) for frame in frames])
            sequences.append(sequence)
            targets.append(label_to_index[row["label"]])
            paths.append(row["path"])
            splits.append(row["split"])
            groups.append(row["group_id"])
            detected_frames.append(int((sequence[:, -2:].max(axis=1) > 0.5).sum()))
            if index % 20 == 0 or index == len(rows):
                print(f"Đã trích {index}/{len(rows)} video focus", flush=True)

    values = np.stack(sequences).astype(np.float32)
    if values.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
        raise AssertionError(f"Shape landmark không hợp lệ: {values.shape}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        sequences=values,
        labels=np.asarray(targets, dtype=np.int64),
        paths=np.asarray(paths),
        splits=np.asarray(splits),
        group_ids=np.asarray(groups),
        detected_frames=np.asarray(detected_frames, dtype=np.int64),
        label_names=np.asarray(labels),
    )
    detection = np.asarray(detected_frames)
    print(f"Đã lưu {len(values)} mẫu vào {args.output}")
    print(
        "Frame có tay: "
        f"trung vị {float(np.median(detection)):.1f}/{SEQUENCE_LENGTH}, "
        f"thấp nhất {int(detection.min())}/{SEQUENCE_LENGTH}"
    )


if __name__ == "__main__":
    main()
