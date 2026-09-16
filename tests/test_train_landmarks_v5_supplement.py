from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ml.landmarks_v2 import SplitIndices
from ml.landmarks_v5 import FEATURE_DIM
from ml.scripts.train_landmarks_v5 import append_v5_supplements


def write_supplement(
    path: Path,
    labels: list[str],
    sample_paths: list[str],
    targets: list[int],
    splits: list[str] | None,
    detected_hand_frames: list[int] | None = None,
) -> None:
    values = {
        "sequences": np.zeros((len(targets), 16, FEATURE_DIM), dtype=np.float32),
        "labels": np.asarray(targets, dtype=np.int64),
        "hands": np.asarray(["unknown"] * len(targets)),
        "paths": np.asarray(sample_paths),
        "label_names": np.asarray(labels),
    }
    if splits is not None:
        values["splits"] = np.asarray(splits)
    if detected_hand_frames is not None:
        values["detected_hand_frames"] = np.asarray(
            detected_hand_frames, dtype=np.int64
        )
    np.savez_compressed(path, **values)


def test_supplement_deduplicates_and_preserves_declared_split(tmp_path: Path) -> None:
    labels = ["Uống", "Ăn"]
    path = tmp_path / "public.npz"
    write_supplement(
        path,
        labels,
        ["old.mp4", "train.mp4", "val.mp4"],
        [0, 0, 1],
        ["train", "train", "validation"],
    )
    output = append_v5_supplements(
        np.zeros((1, 16, FEATURE_DIM), dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        ["right"],
        ["old.mp4"],
        SplitIndices(
            train=np.asarray([0], dtype=np.int64),
            validation=np.asarray([], dtype=np.int64),
        ),
        [path],
        labels,
        seed=1,
    )
    sequences, targets, _, paths, split, added, rejected = output
    assert sequences.shape[0] == 3
    assert targets.tolist() == [0, 0, 1]
    assert paths == ["old.mp4", "train.mp4", "val.mp4"]
    assert split.train.tolist() == [0, 1]
    assert split.validation.tolist() == [2]
    assert added == 2
    assert rejected == 0


def test_supplement_rejects_public_test_split(tmp_path: Path) -> None:
    labels = ["Uống"]
    path = tmp_path / "forbidden.npz"
    write_supplement(path, labels, ["test.mp4"], [0], ["test"])
    with pytest.raises(ValueError, match="split cấm"):
        append_v5_supplements(
            np.zeros((1, 16, FEATURE_DIM), dtype=np.float32),
            np.asarray([0], dtype=np.int64),
            ["right"],
            ["old.mp4"],
            SplitIndices(
                train=np.asarray([0], dtype=np.int64),
                validation=np.asarray([], dtype=np.int64),
            ),
            [path],
            labels,
            seed=1,
        )


def test_supplement_rejects_test_even_when_quality_would_filter_it(
    tmp_path: Path,
) -> None:
    labels = ["Uống"]
    path = tmp_path / "forbidden-low-quality.npz"
    write_supplement(
        path,
        labels,
        ["test.mp4"],
        [0],
        ["test"],
        detected_hand_frames=[0],
    )
    with pytest.raises(ValueError, match="split cấm"):
        append_v5_supplements(
            np.zeros((1, 16, FEATURE_DIM), dtype=np.float32),
            np.asarray([0], dtype=np.int64),
            ["right"],
            ["old.mp4"],
            SplitIndices(
                train=np.asarray([0], dtype=np.int64),
                validation=np.asarray([], dtype=np.int64),
            ),
            [path],
            labels,
            seed=1,
        )


def test_supplement_rejects_clip_without_detected_hand(tmp_path: Path) -> None:
    labels = ["Uống"]
    path = tmp_path / "quality.npz"
    write_supplement(
        path,
        labels,
        ["no-hand.mp4", "valid.mp4"],
        [0, 0],
        ["train", "train"],
        detected_hand_frames=[0, 1],
    )
    output = append_v5_supplements(
        np.zeros((1, 16, FEATURE_DIM), dtype=np.float32),
        np.asarray([0], dtype=np.int64),
        ["right"],
        ["old.mp4"],
        SplitIndices(
            train=np.asarray([0], dtype=np.int64),
            validation=np.asarray([], dtype=np.int64),
        ),
        [path],
        labels,
        seed=1,
    )
    sequences, targets, _, paths, split, added, rejected = output
    assert sequences.shape[0] == 2
    assert targets.tolist() == [0, 0]
    assert paths == ["old.mp4", "valid.mp4"]
    assert split.train.tolist() == [0, 1]
    assert added == 1
    assert rejected == 1
