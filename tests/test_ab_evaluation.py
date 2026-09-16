from __future__ import annotations

import numpy as np

from ml.ab_evaluation import (
    PairedFrame,
    automatic_sequence,
    manual_sequence,
    motion_weighted_sample_indices,
)
from ml.landmarks_v2 import FEATURE_DIM as V3_FEATURE_DIM
from ml.landmarks_v4 import (
    FEATURE_DIM as V4_FEATURE_DIM,
    HAND_GLOBAL_OFFSET,
    HAND_PRESENCE_OFFSET,
    POSE_COORDINATE_OFFSET,
    POSE_PRESENCE_OFFSET,
)
from ml.scripts.evaluate_landmarks_ab import _compare_and_gate, _summarize
from ml.scripts.freeze_ab_camera_evaluation import _training_overlap, sha256


def paired_hand_frame(timestamp: float, x: float) -> PairedFrame:
    v3 = np.zeros(V3_FEATURE_DIM, dtype=np.float32)
    v4 = np.zeros(V4_FEATURE_DIM, dtype=np.float32)
    v3[-2] = 1.0
    v4[HAND_PRESENCE_OFFSET] = 1.0
    v4[HAND_GLOBAL_OFFSET : HAND_GLOBAL_OFFSET + 2] = (x, 0.5)
    for point in range(21):
        v4[point * 3 : point * 3 + 2] = (x + point * 0.001, 0.5)
    return PairedFrame(timestamp, v3, v4)


def paired_pose_frame(timestamp: float, x: float) -> PairedFrame:
    v3 = np.zeros(V3_FEATURE_DIM, dtype=np.float32)
    v4 = np.zeros(V4_FEATURE_DIM, dtype=np.float32)
    for point in range(7, 11):
        offset = POSE_COORDINATE_OFFSET + point * 3
        v4[offset : offset + 2] = (x, 0.5)
        v4[POSE_PRESENCE_OFFSET + point] = 1.0
    return PairedFrame(timestamp, v3, v4)


def test_manual_sequence_keeps_exactly_sixteen_paired_frames() -> None:
    frames = [paired_hand_frame(index * 50.0, 0.2 + index * 0.01) for index in range(30)]
    sequence = manual_sequence(frames)
    assert sequence.v3.shape == (16, V3_FEATURE_DIM)
    assert sequence.v4.shape == (16, V4_FEATURE_DIM)
    assert len(sequence.source_indices) == 16


def test_automatic_replay_is_consistent_at_15_and_30_fps() -> None:
    for interval in (33.0, 67.0):
        frames = [
            paired_hand_frame(index * interval, 0.2 + index * interval / 2000.0)
            for index in range(int(1_100 / interval))
        ]
        sequence = automatic_sequence(frames)
        assert sequence is not None
        assert sequence.v3.shape == (16, V3_FEATURE_DIM)
        assert sequence.v4.shape == (16, V4_FEATURE_DIM)


def test_automatic_replay_rejects_body_only_motion() -> None:
    frames = [paired_pose_frame(index * 40.0, 0.2 + index * 0.02) for index in range(50)]
    assert automatic_sequence(frames) is None


def test_motion_sampler_matches_browser_endpoint_contract() -> None:
    scores = [0.0] * 24
    scores[12] = 1.0
    indices = motion_weighted_sample_indices(24, scores)
    assert len(indices) == 16
    assert indices[0] == 0
    assert indices[-1] == 23
    assert 12 in indices
    assert indices == sorted(indices)


def test_metrics_report_dau_attraction_and_false_accept() -> None:
    rows = [
        {
            "expected_label": "Chào",
            "is_negative": False,
            "segmented": True,
            "raw_prediction": "Đâu",
            "accepted": True,
            "accepted_label": "Đâu",
            "correct": False,
        },
        {
            "expected_label": "Đâu",
            "is_negative": False,
            "segmented": True,
            "raw_prediction": "Đâu",
            "accepted": True,
            "accepted_label": "Đâu",
            "correct": True,
        },
        {
            "expected_label": "Không ký hiệu",
            "is_negative": True,
            "segmented": True,
            "raw_prediction": "Chào",
            "accepted": True,
            "accepted_label": "Chào",
            "correct": False,
        },
    ]
    metrics = _summarize(rows, ["Chào", "Đâu"])
    assert metrics["wrong_to_dau_count_positive"] == 1
    assert metrics["wrong_to_dau_rate_positive"] == 1.0
    assert metrics["negative_false_accept_rate"] == 1.0
    assert metrics["per_class"]["Chào"]["raw_wrong_to_dau"] == 1


def test_release_gate_requires_v4_noninferior_in_both_modes() -> None:
    better = {
        "raw_top1_accuracy_positive": 0.9,
        "accepted_correct_rate_positive": 0.85,
        "accepted_accuracy_positive": 0.95,
        "positive_rejection_rate": 0.1,
        "negative_false_accept_rate": 0.04,
        "wrong_to_dau_rate_positive": 0.01,
    }
    worse = {**better, "raw_top1_accuracy_positive": 0.8}
    metrics = {
        "manual": {"v3": better, "v4_2": better},
        "automatic": {"v3": better, "v4_2": worse},
    }
    gate = {
        "maximum_negative_false_accept_rate": 0.05,
        "require_v4_noninferior_each_mode": [
            "raw_top1_accuracy_positive",
            "accepted_correct_rate_positive",
            "accepted_accuracy_positive",
        ],
        "require_v4_not_higher_each_mode": [
            "positive_rejection_rate",
            "negative_false_accept_rate",
            "wrong_to_dau_rate_positive",
        ],
        "strict_improvement_required": True,
    }
    assert _compare_and_gate(metrics, gate)["passed"] is False


def test_release_gate_detects_video_reused_from_training(tmp_path) -> None:
    training = tmp_path / "training"
    training.mkdir()
    train_video = training / "known.mp4"
    train_video.write_bytes(b"same-camera-clip")
    samples = [
        {
            "video": "evaluation/copied.mp4",
            "video_sha256": sha256(train_video),
        }
    ]
    overlaps = _training_overlap(samples, training)
    assert len(overlaps) == 1
    assert "known.mp4" in overlaps[0]
