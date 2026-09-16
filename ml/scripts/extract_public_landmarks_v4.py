from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

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


IDLE_LABEL = "Không ký hiệu"
SPLITS = ("train", "validation", "test")


def _stable_key(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}\0{value}".encode("utf-8")).hexdigest()


def select_balanced_rows(
    rows: Iterable[dict[str, str]],
    common_labels: set[str],
    *,
    common_train_groups: int,
    common_holdout_groups: int,
    negative_train_groups: int,
    negative_holdout_groups: int,
    seed: int,
) -> list[dict[str, str]]:
    """Select one video per source group with balanced common/OOV coverage."""

    by_label_split: dict[tuple[str, str], dict[str, list[dict[str, str]]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for row in rows:
        split = row.get("split", "")
        if split not in SPLITS:
            raise ValueError(f"Split không hợp lệ: {split!r}")
        by_label_split[(row["label"], split)][row["group_id"]].append(row)

    labels = sorted({label for label, _ in by_label_split})
    selected: list[dict[str, str]] = []
    for label in labels:
        is_common = label in common_labels
        for split in SPLITS:
            limit = (
                common_train_groups
                if is_common and split == "train"
                else common_holdout_groups
                if is_common
                else negative_train_groups
                if split == "train"
                else negative_holdout_groups
            )
            groups = by_label_split.get((label, split), {})
            if not groups:
                raise ValueError(
                    f"{label}/{split} không có group trong manifest"
                )
            actual_limit = min(limit, len(groups))
            ordered_groups = sorted(
                groups, key=lambda group: _stable_key(seed, f"{label}\0{split}\0{group}")
            )
            for group in ordered_groups[:actual_limit]:
                variants = sorted(
                    groups[group],
                    key=lambda row: _stable_key(seed, row["path"]),
                )
                selected.append(variants[0])
    return sorted(selected, key=lambda row: (row["split"], row["label"], row["path"]))


def sample_frames(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
    if not frames:
        raise ValueError(f"Video không có frame: {path}")
    indices = np.rint(np.linspace(0, len(frames) - 1, SEQUENCE_LENGTH)).astype(int)
    return [frames[index] for index in indices]


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


def _save(
    path: Path,
    indices: np.ndarray,
    *,
    sequences: np.ndarray,
    targets: np.ndarray,
    rows: list[dict[str, str]],
    detected_hands: np.ndarray,
    detected_pose: np.ndarray,
    label_names: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        sequences=sequences[indices],
        labels=targets[indices],
        hands=np.full(len(indices), "unknown"),
        paths=np.asarray([rows[index]["path"] for index in indices]),
        splits=np.asarray([rows[index]["split"] for index in indices]),
        group_ids=np.asarray([rows[index]["group_id"] for index in indices]),
        source_labels=np.asarray([rows[index]["label"] for index in indices]),
        detected_hand_frames=detected_hands[indices],
        detected_pose_frames=detected_pose[indices],
        is_negative=targets[indices] == label_names.index(IDLE_LABEL),
        label_names=np.asarray(label_names),
        feature_schema=np.asarray(
            "vsign-landmarks-v4.1-public-balanced-interhand"
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trích common-20 và OOV negative từ ViSignLanguage cho V4.1"
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/dataset"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("ml/data/raw/visignlanguage-video/manifest.csv"),
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
        default=Path("ml/data/processed/landmarks_v4/public_balanced_trainval.npz"),
    )
    parser.add_argument(
        "--test-output",
        type=Path,
        default=Path("ml/data/processed/landmarks_v4/public_balanced_test.npz"),
    )
    parser.add_argument(
        "--reuse-dataset",
        action="append",
        type=Path,
        default=[],
        help="NPZ V4.1 đã trích; video trùng path sẽ được tái sử dụng",
    )
    parser.add_argument("--common-train-groups", type=int, default=12)
    parser.add_argument("--common-holdout-groups", type=int, default=2)
    parser.add_argument("--negative-train-groups", type=int, default=4)
    parser.add_argument("--negative-holdout-groups", type=int, default=1)
    parser.add_argument("--minimum-hand-confidence", type=float, default=0.35)
    parser.add_argument("--minimum-pose-confidence", type=float, default=0.30)
    parser.add_argument("--seed", type=int, default=20260911)
    args = parser.parse_args()

    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise ValueError("labels.json phải là một mảng chuỗi")
    if IDLE_LABEL in labels:
        labels = [label for label in labels if label != IDLE_LABEL]
    label_names = labels + [IDLE_LABEL]
    label_to_index = {label: index for index, label in enumerate(labels)}
    with args.manifest.open(encoding="utf-8", newline="") as handle:
        manifest_rows = list(csv.DictReader(handle))
    selected = select_balanced_rows(
        manifest_rows,
        set(labels),
        common_train_groups=args.common_train_groups,
        common_holdout_groups=args.common_holdout_groups,
        negative_train_groups=args.negative_train_groups,
        negative_holdout_groups=args.negative_holdout_groups,
        seed=args.seed,
    )

    reused: dict[str, tuple[np.ndarray, int, int]] = {}
    for reuse_path in args.reuse_dataset:
        reuse = np.load(reuse_path)
        reuse_sequences = reuse["sequences"].astype(np.float32)
        if reuse_sequences.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
            raise ValueError(f"Dataset tái sử dụng có shape sai: {reuse_path}")
        reuse_hands = reuse["detected_hand_frames"].astype(np.int64)
        reuse_pose = reuse["detected_pose_frames"].astype(np.int64)
        for path, sequence, hand_count, pose_count in zip(
            reuse["paths"].astype(str), reuse_sequences, reuse_hands, reuse_pose
        ):
            reused[str(path)] = (sequence, int(hand_count), int(pose_count))

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
    hand_counts: list[int] = []
    pose_counts: list[int] = []
    with (
        mp.tasks.vision.HandLandmarker.create_from_options(hand_options) as hand_detector,
        mp.tasks.vision.PoseLandmarker.create_from_options(pose_options) as pose_detector,
    ):
        for index, row in enumerate(selected, start=1):
            cached = reused.get(row["path"])
            if cached is None:
                frames = sample_frames(args.dataset_root / row["path"])
                sequence = np.stack(
                    [
                        extract_frame(hand_detector, pose_detector, frame)
                        for frame in frames
                    ]
                )
                hand_count = int(
                    (
                        sequence[
                            :, HAND_PRESENCE_OFFSET : HAND_PRESENCE_OFFSET + 2
                        ].max(axis=1)
                        > 0.5
                    ).sum()
                )
                pose_count = int(
                    (sequence[:, POSE_PRESENCE_OFFSET:].max(axis=1) > 0.5).sum()
                )
            else:
                sequence, hand_count, pose_count = cached
            sequences.append(sequence)
            targets.append(label_to_index.get(row["label"], len(labels)))
            hand_counts.append(hand_count)
            pose_counts.append(pose_count)
            if index % 40 == 0 or index == len(selected):
                print(f"Đã trích public V4.1 {index}/{len(selected)} video", flush=True)

    values = np.stack(sequences).astype(np.float32)
    if values.shape[1:] != (SEQUENCE_LENGTH, FEATURE_DIM):
        raise AssertionError(f"Shape landmark V4.1 không hợp lệ: {values.shape}")
    target_values = np.asarray(targets, dtype=np.int64)
    hand_values = np.asarray(hand_counts, dtype=np.int64)
    pose_values = np.asarray(pose_counts, dtype=np.int64)
    trainval = np.asarray(
        [index for index, row in enumerate(selected) if row["split"] != "test"],
        dtype=np.int64,
    )
    test = np.asarray(
        [index for index, row in enumerate(selected) if row["split"] == "test"],
        dtype=np.int64,
    )
    _save(
        args.output,
        trainval,
        sequences=values,
        targets=target_values,
        rows=selected,
        detected_hands=hand_values,
        detected_pose=pose_values,
        label_names=label_names,
    )
    _save(
        args.test_output,
        test,
        sequences=values,
        targets=target_values,
        rows=selected,
        detected_hands=hand_values,
        detected_pose=pose_values,
        label_names=label_names,
    )
    print(
        f"Đã lưu {len(trainval)} train/validation và {len(test)} test; "
        f"hand median={np.median(hand_values):.1f}/16, "
        f"pose median={np.median(pose_values):.1f}/16"
    )


if __name__ == "__main__":
    main()
