from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ml.landmarks_v4 import (
    HAND_PRESENCE_OFFSET,
    PAIR_GEOMETRY_OFFSET,
    POSE_COORDINATE_OFFSET,
    POSE_LANDMARK_COUNT,
    POSE_PRESENCE_OFFSET,
    SEQUENCE_LENGTH,
)


IDLE_LABEL = "Không ký hiệu"


@dataclass(frozen=True)
class IdleCandidate:
    source_index: int
    start: int
    end: int
    length: int
    motion: float


def boundary_runs(hand_visible: np.ndarray) -> list[tuple[int, int]]:
    first = 0
    while first < len(hand_visible) and not hand_visible[first]:
        first += 1
    last_count = 0
    while last_count < len(hand_visible) and not hand_visible[-1 - last_count]:
        last_count += 1
    runs: list[tuple[int, int]] = []
    if first >= 3:
        runs.append((0, first))
    if last_count >= 3:
        runs.append((len(hand_visible) - last_count, len(hand_visible)))
    return runs


def pose_arm_motion(sequence: np.ndarray, start: int, end: int) -> float:
    pose = sequence[
        :, POSE_COORDINATE_OFFSET:PAIR_GEOMETRY_OFFSET
    ].reshape(SEQUENCE_LENGTH, POSE_LANDMARK_COUNT, 3)
    mask = sequence[:, POSE_PRESENCE_OFFSET:]
    distances: list[float] = []
    for frame in range(start + 1, end):
        for point in range(7, 11):
            if mask[frame - 1, point] > 0.5 and mask[frame, point] > 0.5:
                distances.append(
                    float(np.linalg.norm(pose[frame, point, :2] - pose[frame - 1, point, :2]))
                )
    return float(np.mean(distances)) if distances else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tạo lớp Không ký hiệu từ đoạn idle thật ở biên clip V4"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("ml/data/processed/landmarks_v4/collected_common20.npz"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/data/processed/landmarks_v4/collected_common20_idle.npz"),
    )
    parser.add_argument("--per-source-label", type=int, default=5)
    parser.add_argument("--maximum-motion", type=float, default=0.055)
    args = parser.parse_args()

    data = np.load(args.input)
    sequences = data["sequences"].astype(np.float32)
    targets = data["labels"].astype(np.int64)
    label_names = data["label_names"].tolist()
    if IDLE_LABEL in label_names:
        raise ValueError("Dataset đã có lớp Không ký hiệu")

    hand_visible = (
        sequences[:, :, HAND_PRESENCE_OFFSET:POSE_PRESENCE_OFFSET].max(axis=-1)
        > 0.5
    )
    chosen: list[IdleCandidate] = []
    for label_index in range(len(label_names)):
        candidates: list[IdleCandidate] = []
        for source_index in np.flatnonzero(targets == label_index).tolist():
            runs = boundary_runs(hand_visible[source_index])
            if not runs:
                continue
            start, end = max(runs, key=lambda run: run[1] - run[0])
            motion = pose_arm_motion(sequences[source_index], start, end)
            if motion <= args.maximum_motion:
                candidates.append(
                    IdleCandidate(source_index, start, end, end - start, motion)
                )
        candidates.sort(key=lambda item: (-item.length, item.motion, item.source_index))
        chosen.extend(candidates[: args.per_source_label])

    if len(chosen) < len(label_names) * 2:
        raise RuntimeError(f"Chỉ tìm được {len(chosen)} đoạn idle đủ sạch")
    idle_sequences: list[np.ndarray] = []
    idle_paths: list[str] = []
    idle_source_indices: list[int] = []
    for item in chosen:
        indices = np.rint(
            np.linspace(item.start, item.end - 1, SEQUENCE_LENGTH)
        ).astype(np.int64)
        idle_sequences.append(sequences[item.source_index, indices])
        idle_paths.append(
            f"{data['paths'][item.source_index]}#idle-{item.start}-{item.end}"
        )
        idle_source_indices.append(item.source_index)

    idle_values = np.stack(idle_sequences).astype(np.float32)
    positive_count = len(sequences)
    combined_sequences = np.concatenate((sequences, idle_values))
    combined_targets = np.concatenate(
        (targets, np.full(len(idle_values), len(label_names), dtype=np.int64))
    )
    source_indices = np.concatenate(
        (np.arange(positive_count, dtype=np.int64), np.asarray(idle_source_indices))
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        sequences=combined_sequences,
        labels=combined_targets,
        hands=np.concatenate((data["hands"], np.full(len(idle_values), "none"))),
        paths=np.concatenate((data["paths"], np.asarray(idle_paths))),
        label_names=np.asarray(label_names + [IDLE_LABEL]),
        is_negative=np.concatenate(
            (np.zeros(positive_count, dtype=np.bool_), np.ones(len(idle_values), dtype=np.bool_))
        ),
        source_sample_index=source_indices,
        feature_schema=np.asarray(
            "vsign-landmarks-v4.1-shoulder-relative-interhand-idle"
        ),
    )
    print(
        f"Đã thêm {len(idle_values)} đoạn idle thật; dataset mới có "
        f"{len(combined_sequences)} mẫu và {len(label_names) + 1} lớp"
    )
    motions = np.asarray([item.motion for item in chosen])
    lengths = np.asarray([item.length for item in chosen])
    print(
        f"Idle boundary: độ dài trung vị {np.median(lengths):.1f} frame, "
        f"motion trung vị {np.median(motions):.4f}, max {motions.max():.4f}"
    )


if __name__ == "__main__":
    main()
