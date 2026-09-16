from collections import Counter, defaultdict

import numpy as np

from ml.scripts.generate_v5_scaleup_plan import (
    build_rows,
    build_targets,
    load_quality_checked_public_counts,
)


def test_scaleup_targets_100_unique_videos_without_public_test() -> None:
    labels = ["Uống", "Nói"]
    public = Counter({"Uống": 23, "Nói": 22})
    local = defaultdict(Counter)
    local["Uống"].update({"right": 5, "left": 5})
    local["Nói"].update({"right": 5, "left": 5})
    targets = build_targets(labels, public, target_per_label=100)
    rows = build_rows(labels, targets, local)

    assert targets["Uống"] == {"right": 39, "left": 38}
    assert targets["Nói"] == {"right": 39, "left": 39}
    new_counts = Counter((row["expected_label"], row["hand"]) for row in rows)
    for label in labels:
        final_local = sum(
            local[label][hand] + new_counts[label, hand]
            for hand in ("right", "left")
        )
        assert public[label] + final_local == 100


def test_scaleup_does_not_add_rows_past_target() -> None:
    labels = ["Chào"]
    public = Counter({"Chào": 60})
    local = defaultdict(Counter)
    local["Chào"].update({"right": 25, "left": 25})
    targets = build_targets(labels, public, target_per_label=100)
    assert build_rows(labels, targets, local) == []


def test_public_quality_counts_exclude_no_hand_and_forbidden_test(tmp_path) -> None:
    path = tmp_path / "public.npz"
    np.savez_compressed(
        path,
        labels=np.asarray([0, 0, 1], dtype=np.int64),
        label_names=np.asarray(["Uống", "Ăn"]),
        splits=np.asarray(["train", "validation", "train"]),
        detected_hand_frames=np.asarray([0, 1, 3], dtype=np.int64),
    )
    counts = load_quality_checked_public_counts(
        path, min_detected_hand_frames=1
    )
    assert counts == Counter({"Uống": 1, "Ăn": 1})
