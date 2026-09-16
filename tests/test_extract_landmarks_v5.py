import csv
from pathlib import Path

import numpy as np

from ml.landmarks_v2 import FEATURE_DIM as V3_FEATURE_DIM
from ml.landmarks_v4 import FEATURE_DIM as V4_FEATURE_DIM
from ml.landmarks_v5 import FEATURE_DIM as V5_FEATURE_DIM
from ml.scripts.extract_landmarks_v5 import (
    manifest_rows,
    sample_detected_sequence,
)


def test_manifest_extractor_never_returns_public_test(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("path", "label", "split"))
        writer.writeheader()
        writer.writerows(
            [
                {"path": "train.mp4", "label": "Uống", "split": "train"},
                {"path": "val.mp4", "label": "Uống", "split": "validation"},
                {"path": "test.mp4", "label": "Uống", "split": "test"},
                {"path": "other.mp4", "label": "Khác", "split": "train"},
            ]
        )
    selected = manifest_rows(manifest, {"Uống"})
    assert [row["path"] for row in selected] == ["train.mp4", "val.mp4"]


def test_sampling_preserves_v3_v4_alignment() -> None:
    v3 = [np.full(V3_FEATURE_DIM, index, dtype=np.float32) for index in range(30)]
    v4 = [np.zeros(V4_FEATURE_DIM, dtype=np.float32) for _ in range(30)]
    sampled_v3, sampled_v4, indices = sample_detected_sequence(v3, v4)
    assert sampled_v3.shape == (16, V3_FEATURE_DIM)
    assert sampled_v4.shape == (16, V4_FEATURE_DIM)
    assert len(indices) == 16
    assert sampled_v3.shape[-1] + (V4_FEATURE_DIM - 126) == V5_FEATURE_DIM
    assert [int(value) for value in sampled_v3[:, 0]] == indices
