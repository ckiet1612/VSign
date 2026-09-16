import numpy as np
import torch

from ml.landmarks_v2 import (
    FEATURE_DIM,
    HAND_FEATURES,
    LandmarkKeyframeNet,
    LandmarkTCN,
    mirror_sequence,
    pack_landmarks,
    stratified_hand_split,
)


def _hand(wrist_x: float) -> np.ndarray:
    values = np.zeros((21, 3), dtype=np.float32)
    values[:, 0] = wrist_x
    values[:, 1] = np.linspace(0.1, 0.9, 21)
    return values


def test_pack_landmarks_sorts_hands_and_sets_presence() -> None:
    packed = pack_landmarks([_hand(0.8), _hand(0.2)])
    assert packed.shape == (FEATURE_DIM,)
    assert packed[0] == np.float32(0.2)
    assert packed[HAND_FEATURES] == np.float32(0.8)
    np.testing.assert_array_equal(packed[-2:], np.ones(2, dtype=np.float32))


def test_mirror_sequence_is_an_involution() -> None:
    sequence = np.stack([pack_landmarks([_hand(0.2), _hand(0.75)])] * 16)
    mirrored = mirror_sequence(sequence)
    assert mirrored[0, 0] == np.float32(0.25)
    assert mirrored[0, HAND_FEATURES] == np.float32(0.8)
    np.testing.assert_allclose(mirror_sequence(mirrored), sequence)


def test_stratified_hand_split_keeps_every_group_in_both_sets() -> None:
    labels = np.repeat(np.arange(3), 10)
    hands = [hand for _ in range(3) for hand in (["left"] * 5 + ["right"] * 5)]
    split = stratified_hand_split(labels, hands)
    assert len(split.train) == 24
    assert len(split.validation) == 6
    for label in range(3):
        for hand in ("left", "right"):
            group = {
                index
                for index, (item_label, item_hand) in enumerate(zip(labels, hands))
                if item_label == label and item_hand == hand
            }
            assert group & set(split.train.tolist())
            assert group & set(split.validation.tolist())


def test_landmark_tcn_output_shape_and_finite_values() -> None:
    model = LandmarkTCN(20).eval()
    inputs = torch.zeros((2, 16, FEATURE_DIM), dtype=torch.float32)
    inputs[:, :, -2] = 1
    with torch.no_grad():
        output = model(inputs)
    assert output.shape == (2, 20)
    assert torch.isfinite(output).all()


def test_landmark_keyframe_net_output_shape_and_finite_values() -> None:
    model = LandmarkKeyframeNet(20).eval()
    inputs = torch.zeros((2, 16, FEATURE_DIM), dtype=torch.float32)
    inputs[:, :, -2] = 1
    with torch.no_grad():
        output = model(inputs)
    assert output.shape == (2, 20)
    assert torch.isfinite(output).all()
