import numpy as np
import torch

from ml.landmarks_v2 import FEATURE_DIM as V3_FEATURE_DIM, LandmarkKeyframeNet
from ml.landmarks_v4 import FEATURE_DIM as V4_FEATURE_DIM, HAND_GLOBAL_OFFSET
from ml.landmarks_v5 import (
    FEATURE_DIM,
    GuardedLandmarkV5,
    combine_v3_v4_sequences,
    mirror_sequence_v5,
)


def test_v5_join_keeps_exact_v3_and_context_blocks() -> None:
    baseline = np.arange(2 * 16 * V3_FEATURE_DIM, dtype=np.float32).reshape(
        2, 16, V3_FEATURE_DIM
    )
    contextual = np.arange(2 * 16 * V4_FEATURE_DIM, dtype=np.float32).reshape(
        2, 16, V4_FEATURE_DIM
    )
    joined = combine_v3_v4_sequences(baseline, contextual)
    assert joined.shape == (2, 16, FEATURE_DIM)
    np.testing.assert_array_equal(joined[..., :V3_FEATURE_DIM], baseline)
    np.testing.assert_array_equal(
        joined[..., V3_FEATURE_DIM:], contextual[..., HAND_GLOBAL_OFFSET:]
    )


def test_v5_mirror_is_an_involution() -> None:
    rng = np.random.default_rng(17)
    baseline = rng.random((3, 16, V3_FEATURE_DIM), dtype=np.float32)
    contextual = rng.normal(size=(3, 16, V4_FEATURE_DIM)).astype(np.float32)
    baseline[..., -2:] = 1
    contextual[..., -13:] = 1
    joined = combine_v3_v4_sequences(baseline, contextual)
    np.testing.assert_allclose(
        mirror_sequence_v5(mirror_sequence_v5(joined)), joined, atol=1e-6
    )


def test_zero_context_or_untrained_residual_is_exact_v3() -> None:
    torch.manual_seed(9)
    baseline = LandmarkKeyframeNet(20).eval()
    model = GuardedLandmarkV5(20, focus_indices=[5, 6, 8, 12, 15]).eval()
    model.load_baseline_state(baseline.state_dict())
    inputs = torch.randn(4, 16, FEATURE_DIM)
    inputs[..., V3_FEATURE_DIM - 2 : V3_FEATURE_DIM] = 1
    with torch.no_grad():
        expected = baseline(inputs[..., :V3_FEATURE_DIM])
        actual = model(inputs)
    torch.testing.assert_close(actual, expected, rtol=0, atol=0)


def test_context_is_disabled_without_shoulders() -> None:
    torch.manual_seed(11)
    model = GuardedLandmarkV5(20, focus_indices=[5, 6, 8, 12, 15]).eval()
    with torch.no_grad():
        model.context_classifier[-1].bias.fill_(4)
    inputs = torch.randn(2, 16, FEATURE_DIM)
    inputs[..., V3_FEATURE_DIM - 2 : V3_FEATURE_DIM] = 1
    # Context pose masks remain absent, so the deliberately non-zero residual
    # must still be gated away.
    inputs[..., V3_FEATURE_DIM:] = 0
    with torch.no_grad():
        baseline_logits = model.baseline(inputs[..., :V3_FEATURE_DIM])
        correction = model.context_correction(inputs, baseline_logits)
    torch.testing.assert_close(correction, torch.zeros_like(correction))


def test_stable_v3_prediction_gates_away_context_branch() -> None:
    torch.manual_seed(13)
    model = GuardedLandmarkV5(20, focus_indices=[5, 6, 8, 12, 15]).eval()
    inputs = torch.randn(2, 16, FEATURE_DIM)
    inputs[..., V3_FEATURE_DIM - 2 : V3_FEATURE_DIM] = 1
    # Mark both shoulders as available and make the residual non-zero.
    inputs[..., V3_FEATURE_DIM + 51] = 1
    inputs[..., V3_FEATURE_DIM + 52] = 1
    with torch.no_grad():
        model.context_classifier[-1].bias.fill_(3)
        baseline_logits = torch.zeros(2, 20)
        baseline_logits[:, 0] = 5  # Chào is outside the focus group.
        correction = model.context_correction(inputs, baseline_logits)
    torch.testing.assert_close(correction, torch.zeros_like(correction))
