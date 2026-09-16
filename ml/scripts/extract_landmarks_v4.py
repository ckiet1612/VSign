from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import av
import mediapipe as mp
import numpy as np

from ml.landmarks_v4 import (
    FEATURE_DIM,
    HAND_PRESENCE_OFFSET,
    POSE_PRESENCE_OFFSET,
    SEQUENCE_LENGTH,
    pack_landmarks_v4,
)


def read_frames(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]


def label_order(labels_path: Path) -> list[str]:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("labels.json phải là một mảng chuỗi")
    return labels


def extract_frame(
    hand_detector: Any, pose_detector: Any, frame: np.ndarray
) -> np.ndarray:
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(frame))
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
    return pack_landmarks_v4(hands, pose)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trích hand shape + upper-body pose cho model VSign V4"
    )
    parser.add_argument(
        "--input-dir", type=Path, default=Path("ml/data/collected/webcam")
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
        default=Path("ml/data/processed/landmarks_v4/collected_common20.npz"),
    )
    parser.add_argument("--minimum-hand-confidence", type=float, default=0.35)
    parser.add_argument("--minimum-pose-confidence", type=float, default=0.30)
    args = parser.parse_args()

    if "evaluation" in args.input_dir.resolve().parts:
        raise ValueError(
            "Không trích bộ evaluation bằng pipeline tạo dữ liệu train. "
            "Hãy dùng evaluate_landmarks_ab.py để giữ bộ đánh giá chỉ đọc."
        )

    for model_path in (args.hand_model, args.pose_model):
        if not model_path.is_file():
            raise FileNotFoundError(f"Không tìm thấy MediaPipe model: {model_path}")
    labels = label_order(args.labels)
    label_to_index = {label: index for index, label in enumerate(labels)}
    paths = sorted(args.input_dir.rglob("*.mp4"))
    if not paths:
        raise FileNotFoundError(f"Không tìm thấy video trong {args.input_dir}")

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
    recorded_hands: list[str] = []
    relative_paths: list[str] = []
    distances: list[str] = []
    lighting_conditions: list[str] = []
    negative_actions: list[str] = []
    detected_hand_frames: list[int] = []
    detected_pose_frames: list[int] = []
    arm_only_frames: list[int] = []
    unknown_labels: list[str] = []

    with (
        mp.tasks.vision.HandLandmarker.create_from_options(hand_options) as hand_detector,
        mp.tasks.vision.PoseLandmarker.create_from_options(pose_options) as pose_detector,
    ):
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
            sequence = np.stack(
                [extract_frame(hand_detector, pose_detector, frame) for frame in frames]
            )
            hand_mask = sequence[
                :, HAND_PRESENCE_OFFSET : HAND_PRESENCE_OFFSET + 2
            ].max(axis=1)
            pose_mask = sequence[:, POSE_PRESENCE_OFFSET:].max(axis=1)
            sequences.append(sequence)
            targets.append(label_to_index[label])
            recorded_hands.append(str(metadata.get("hand", "unknown")))
            relative_paths.append(str(path.relative_to(args.input_dir)))
            distances.append(str(metadata.get("distance", "unspecified")))
            lighting_conditions.append(
                str(metadata.get("lighting", "unspecified"))
            )
            negative_actions.append(
                str(metadata.get("negative_action") or "none")
            )
            detected_hand_frames.append(int((hand_mask > 0.5).sum()))
            detected_pose_frames.append(int((pose_mask > 0.5).sum()))
            arm_only_frames.append(int(((hand_mask <= 0.5) & (pose_mask > 0.5)).sum()))
            if index % 20 == 0 or index == len(paths):
                print(f"Đã trích V4 {index}/{len(paths)} video", flush=True)

    if unknown_labels:
        raise ValueError("Có nhãn ngoài common-20:\n" + "\n".join(unknown_labels))
    values = np.stack(sequences).astype(np.float32)
    if values.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
        raise AssertionError(f"Shape landmark V4 không hợp lệ: {values.shape}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        sequences=values,
        labels=np.asarray(targets, dtype=np.int64),
        hands=np.asarray(recorded_hands),
        paths=np.asarray(relative_paths),
        distances=np.asarray(distances),
        lighting=np.asarray(lighting_conditions),
        negative_actions=np.asarray(negative_actions),
        detected_hand_frames=np.asarray(detected_hand_frames, dtype=np.int64),
        detected_pose_frames=np.asarray(detected_pose_frames, dtype=np.int64),
        arm_only_frames=np.asarray(arm_only_frames, dtype=np.int64),
        label_names=np.asarray(labels),
        feature_schema=np.asarray(
            "vsign-landmarks-v4.1-shoulder-relative-interhand"
        ),
    )
    hand_detection = np.asarray(detected_hand_frames)
    pose_detection = np.asarray(detected_pose_frames)
    arm_only = np.asarray(arm_only_frames)
    print(f"Đã lưu {len(values)} mẫu V4 vào {args.output}")
    print(
        "Frame có tay: "
        f"trung vị {float(np.median(hand_detection)):.1f}/{SEQUENCE_LENGTH}, "
        f"thấp nhất {int(hand_detection.min())}/{SEQUENCE_LENGTH}"
    )
    print(
        "Frame có pose: "
        f"trung vị {float(np.median(pose_detection)):.1f}/{SEQUENCE_LENGTH}, "
        f"thấp nhất {int(pose_detection.min())}/{SEQUENCE_LENGTH}"
    )
    print(
        "Frame pose cứu được khi mất tay chi tiết: "
        f"{int(arm_only.sum())} frame trong {int((hand_detection < SEQUENCE_LENGTH).sum())} video"
    )
    missing_both = np.flatnonzero((hand_detection == 0) & (pose_detection == 0))
    if len(missing_both):
        print(f"CẢNH BÁO: {len(missing_both)} video không có cả tay lẫn pose")
        for sample_index in missing_both.tolist():
            print(f"- {relative_paths[sample_index]}")


if __name__ == "__main__":
    main()
