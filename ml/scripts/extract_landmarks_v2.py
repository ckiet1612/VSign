from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import av
import mediapipe as mp
import numpy as np

from ml.landmarks_v2 import FEATURE_DIM, SEQUENCE_LENGTH, pack_landmarks


def read_frames(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]


def label_order(labels_path: Path) -> list[str]:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("labels.json phải là một mảng chuỗi")
    return labels


def extract_frame(detector: Any, frame: np.ndarray) -> np.ndarray:
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame))
    result = detector.detect(image)
    hands = [
        [(point.x, point.y, point.z) for point in landmarks]
        for landmarks in result.hand_landmarks
    ]
    return pack_landmarks(hands)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trích 21 điểm tay cho model VSign v2")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("ml/data/collected/webcam"),
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
        "--output",
        type=Path,
        default=Path("ml/data/processed/landmarks_v2/collected_common20.npz"),
    )
    parser.add_argument("--minimum-detection-confidence", type=float, default=0.35)
    args = parser.parse_args()

    labels = label_order(args.labels)
    label_to_index = {label: index for index, label in enumerate(labels)}
    paths = sorted(args.input_dir.rglob("*.mp4"))
    if not paths:
        raise FileNotFoundError(f"Không tìm thấy video trong {args.input_dir}")

    os.environ.setdefault("GLOG_minloglevel", "2")
    base_options = mp.tasks.BaseOptions(
        model_asset_path=str(args.hand_model),
        delegate=mp.tasks.BaseOptions.Delegate.CPU,
    )
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=base_options,
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=args.minimum_detection_confidence,
        min_hand_presence_confidence=args.minimum_detection_confidence,
        min_tracking_confidence=args.minimum_detection_confidence,
    )

    sequences: list[np.ndarray] = []
    targets: list[int] = []
    recorded_hands: list[str] = []
    relative_paths: list[str] = []
    detected_frames: list[int] = []
    unknown_labels: list[str] = []

    with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
        for index, path in enumerate(paths, start=1):
            metadata_path = path.with_suffix(".json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            label = metadata.get("expected_label")
            if label not in label_to_index:
                unknown_labels.append(f"{path}: {label!r}")
                continue
            frames = read_frames(path)
            if len(frames) != SEQUENCE_LENGTH:
                raise ValueError(
                    f"{path} có {len(frames)} frame; cần đúng {SEQUENCE_LENGTH} frame"
                )
            sequence = np.stack([extract_frame(detector, frame) for frame in frames])
            sequences.append(sequence)
            targets.append(label_to_index[label])
            recorded_hands.append(str(metadata.get("hand", "unknown")))
            relative_paths.append(str(path.relative_to(args.input_dir)))
            detected_frames.append(int((sequence[:, -2:].max(axis=1) > 0.5).sum()))
            if index % 20 == 0 or index == len(paths):
                print(f"Đã trích {index}/{len(paths)} video", flush=True)

    if unknown_labels:
        raise ValueError("Có nhãn ngoài common-20:\n" + "\n".join(unknown_labels))

    values = np.stack(sequences).astype(np.float32)
    if values.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
        raise AssertionError(f"Shape landmark không hợp lệ: {values.shape}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        sequences=values,
        labels=np.asarray(targets, dtype=np.int64),
        hands=np.asarray(recorded_hands),
        paths=np.asarray(relative_paths),
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
    missing = [relative_paths[i] for i in np.flatnonzero(detection == 0)]
    if missing:
        print(f"CẢNH BÁO: {len(missing)} video không phát hiện được tay")
        for path in missing:
            print(f"- {path}")


if __name__ == "__main__":
    main()
