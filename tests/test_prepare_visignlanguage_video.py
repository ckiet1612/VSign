from __future__ import annotations

import csv
import pickle
from pathlib import Path

import pytest

from ml.scripts.prepare_visignlanguage_video import (
    build_manifest,
    load_label_mapping,
    normalize_text,
)


def test_label_mapping_is_normalized_and_contiguous() -> None:
    payload = pickle.dumps({"Cảm ơn": 0, "Xin lỗi": 1})
    mapping = load_label_mapping(payload)
    assert mapping == {"Cảm ơn": 0, "Xin lỗi": 1}


def test_label_mapping_rejects_non_contiguous_ids() -> None:
    with pytest.raises(ValueError, match="liên tiếp"):
        load_label_mapping(pickle.dumps({"A": 0, "B": 2}))


def test_manifest_split_keeps_augmented_group_together(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    metadata = tmp_path / "metadata.csv"
    labels = {"Cảm ơn": 0, "Xin lỗi": 1}
    source_rows = []
    for label, label_id in labels.items():
        for group in range(5):
            for suffix in ("", "_1"):
                filename = f"{label_id}-{group}{suffix}.mp4"
                path = dataset / "train" / label / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                source_rows.append(
                    {
                        "split": "train",
                        "label": label,
                        "filename": filename,
                        "fps": "20",
                        "total_frames": "30",
                        "width": "224",
                        "height": "224",
                        "duration_s": "1.5",
                    }
                )
    with metadata.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=source_rows[0])
        writer.writeheader()
        writer.writerows(source_rows)

    rows, audit = build_manifest(metadata, dataset, labels, seed=7)

    group_splits = {}
    for row in rows:
        group_splits.setdefault(row["group_id"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in group_splits.values())
    assert set(audit["split_counts"]) == {"train", "validation", "test"}
    assert audit["group_leakage"] == []
    assert normalize_text("Cảm ơn") == "Cảm ơn"
