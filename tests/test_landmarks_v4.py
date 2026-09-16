import numpy as np
import torch

from ml.landmarks_v4 import (
    FEATURE_DIM,
    HAND_GLOBAL_OFFSET,
    HAND_PRESENCE_OFFSET,
    HAND_SHAPE_DIM,
    PAIR_GEOMETRY_OFFSET,
    PAIR_PRESENCE_OFFSET,
    POSE_PRESENCE_OFFSET,
    UnifiedLandmarkV4,
    frame_presence,
    mirror_sequence_v4,
    pack_landmarks_v4,
)
from ml.scripts.train_landmarks_v4 import LandmarkV4Dataset
from ml.scripts.extract_public_landmarks_v4 import select_balanced_rows
from ml.scripts.evaluate_landmarks_v4 import grouped_metrics
from ml.scripts.generate_frozen_camera_plan import DISTANCES, build_plan
from ml.scripts.audit_frozen_camera_capture import audit_capture


def _pose() -> np.ndarray:
    pose = np.zeros((33, 4), dtype=np.float32)
    pose[:, 3] = 1.0
    pose[11, :3] = (0.3, 0.4, 0.0)
    pose[12, :3] = (0.7, 0.4, 0.0)
    pose[15, :3] = (0.2, 0.65, 0.0)
    pose[16, :3] = (0.8, 0.65, 0.0)
    return pose


def _hand(wrist_x: float) -> np.ndarray:
    hand = np.zeros((21, 3), dtype=np.float32)
    hand[:, 0] = wrist_x
    hand[:, 1] = np.linspace(0.65, 0.35, 21)
    hand[9, 0] = wrist_x + 0.1
    return hand


def test_pack_v4_uses_pose_wrist_slots_and_shoulder_normalization() -> None:
    packed = pack_landmarks_v4([_hand(0.79), _hand(0.21)], _pose())
    assert packed.shape == (FEATURE_DIM,)
    np.testing.assert_array_equal(
        packed[HAND_PRESENCE_OFFSET : HAND_PRESENCE_OFFSET + 2], [1, 1]
    )
    # Shoulder center is x=.5 and width=.4: global wrists become roughly +/- .725.
    assert np.isclose(packed[HAND_GLOBAL_OFFSET], -0.725, atol=0.02)
    assert np.isclose(packed[HAND_GLOBAL_OFFSET + 3], 0.725, atol=0.02)
    assert packed[POSE_PRESENCE_OFFSET + 5] == 1.0
    assert packed[POSE_PRESENCE_OFFSET + 6] == 1.0
    assert packed[PAIR_PRESENCE_OFFSET] == 1.0
    assert np.isclose(packed[PAIR_GEOMETRY_OFFSET], 1.45, atol=0.04)
    assert packed[PAIR_GEOMETRY_OFFSET + 3] > 1.4


def test_occluded_hand_is_masked_without_fake_coordinates() -> None:
    packed = pack_landmarks_v4([_hand(0.21)], _pose())
    assert packed[HAND_PRESENCE_OFFSET] == 1.0
    assert packed[HAND_PRESENCE_OFFSET + 1] == 0.0
    second_shape = packed[HAND_SHAPE_DIM : HAND_SHAPE_DIM * 2]
    np.testing.assert_array_equal(second_shape, np.zeros(HAND_SHAPE_DIM))
    # Pose wrist still provides arm context for the missing detailed hand.
    assert packed[POSE_PRESENCE_OFFSET + 10] == 1.0
    # Pair geometry falls back to both pose wrists while one detailed hand is lost.
    assert packed[PAIR_PRESENCE_OFFSET] == 1.0


def test_mirror_v4_is_an_involution() -> None:
    sequence = np.stack([pack_landmarks_v4([_hand(0.21), _hand(0.79)], _pose())] * 16)
    np.testing.assert_allclose(
        mirror_sequence_v4(mirror_sequence_v4(sequence)), sequence, atol=1e-6
    )


def test_pose_arms_keep_occluded_frame_present() -> None:
    frame = pack_landmarks_v4([], _pose())
    assert frame_presence(np.stack([frame]))[0] == 1.0


def test_implausible_pose_does_not_create_fake_body_features() -> None:
    invalid = _pose()
    invalid[0, 1] = 0.95
    invalid[11, 1] = 0.94
    invalid[12, 1] = 0.94
    frame = pack_landmarks_v4([], invalid)
    assert frame_presence(np.stack([frame]))[0] == 0.0


def test_training_occlusion_keeps_pose_context() -> None:
    sequence = np.stack([pack_landmarks_v4([_hand(0.21), _hand(0.79)], _pose())] * 16)
    occluded = LandmarkV4Dataset.occlude_hand(sequence, 1, 5, 11)
    assert np.all(occluded[5:11, HAND_PRESENCE_OFFSET + 1] == 0)
    assert np.all(occluded[5:11, POSE_PRESENCE_OFFSET + 10] == 1)
    assert np.all(frame_presence(occluded[5:11]) == 1)


def test_unified_v4_output_shape_and_finite_values() -> None:
    model = UnifiedLandmarkV4(20).eval()
    inputs = torch.zeros((2, 16, FEATURE_DIM), dtype=torch.float32)
    inputs[:, :, POSE_PRESENCE_OFFSET + 5] = 1
    with torch.no_grad():
        output = model(inputs)
    assert output.shape == (2, 20)
    assert torch.isfinite(output).all()


def test_public_selection_is_group_safe_and_balances_common_with_oov() -> None:
    rows = []
    for label in ("Chào", "Ngoài lớp"):
        for split in ("train", "validation", "test"):
            for group in range(3):
                for variant in range(2):
                    rows.append(
                        {
                            "label": label,
                            "split": split,
                            "group_id": f"{label}:{split}:{group}",
                            "path": f"{label}/{split}-{group}_{variant}.mp4",
                        }
                    )
    selected = select_balanced_rows(
        rows,
        {"Chào"},
        common_train_groups=2,
        common_holdout_groups=1,
        negative_train_groups=1,
        negative_holdout_groups=1,
        seed=7,
    )
    assert len(selected) == 7
    assert len({row["group_id"] for row in selected}) == len(selected)
    assert sum(row["label"] == "Chào" for row in selected) == 4
    assert sum(row["label"] == "Ngoài lớp" for row in selected) == 3


def test_grouped_frozen_metrics_separate_positive_and_negative() -> None:
    metrics = grouped_metrics(
        np.asarray(["near", "near", "far", "far"]),
        np.asarray([0, 2, 1, 2]),
        np.asarray([True, True, False, False]),
        np.asarray([True, False, False, False]),
        idle_index=2,
    )
    assert metrics["near"] == {
        "samples": 2,
        "positive_accepted_accuracy": 1.0,
        "negative_false_accept_rate": 1.0,
    }
    assert metrics["far"] == {
        "samples": 2,
        "positive_accepted_accuracy": 0.0,
        "negative_false_accept_rate": 0.0,
    }


def test_frozen_camera_plan_covers_labels_distances_and_negative_actions() -> None:
    labels = ["Chào", "Trường học", "Không ký hiệu"]
    rows = build_plan(labels, negative_count=8, seed=11)
    positives = [row for row in rows if row["kind"] == "positive"]
    negatives = [row for row in rows if row["kind"] == "negative"]
    assert len(positives) == 6
    assert len(negatives) == 8
    for label in ("Chào", "Trường học"):
        selected = [row for row in positives if row["expected_label"] == label]
        assert {row["distance"] for row in selected} == set(DISTANCES)
        assert {row["hand"] for row in selected} == {"left", "right"}
    assert len({row["negative_action"] for row in negatives}) == 8


def test_frozen_capture_audit_detects_missing_and_duplicate_rows() -> None:
    plan = [
        {
            "expected_label": "Trường học",
            "hand": "right",
            "distance": "far",
            "lighting": "side",
            "negative_action": "",
        },
        {
            "expected_label": "Không ký hiệu",
            "hand": "left",
            "distance": "near",
            "lighting": "low",
            "negative_action": "overlap_hands",
        },
    ]
    captured = [
        {
            "expected_label": "trường học",
            "hand": "right",
            "distance": "far",
            "lighting": "side",
            "negative_action": None,
        },
        {
            "expected_label": "Trường học",
            "hand": "right",
            "distance": "far",
            "lighting": "side",
            "negative_action": None,
        },
    ]
    missing, unexpected = audit_capture(plan, captured)
    assert sum(missing.values()) == 1
    assert sum(unexpected.values()) == 1
