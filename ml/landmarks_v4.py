from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import torch
from torch import nn

from ml.landmarks_v2 import SEQUENCE_LENGTH, TemporalResidualBlock


MAX_HANDS = 2
LANDMARKS_PER_HAND = 21
COORDINATES = 3
HAND_SHAPE_DIM = LANDMARKS_PER_HAND * COORDINATES
HAND_SHAPES_DIM = MAX_HANDS * HAND_SHAPE_DIM
HAND_GLOBAL_DIM = MAX_HANDS * COORDINATES

# MediaPipe Pose indices used by the model: nose, eyes, mouth corners,
# shoulders, elbows and wrists. They provide body-relative context while
# keeping the browser model compact.
POSE_SOURCE_INDICES = (0, 2, 5, 9, 10, 11, 12, 13, 14, 15, 16)
POSE_LANDMARK_COUNT = len(POSE_SOURCE_INDICES)
POSE_COORDINATE_DIM = POSE_LANDMARK_COUNT * COORDINATES
PAIR_GEOMETRY_DIM = 4  # anatomical right-minus-left xyz plus distance

HAND_SHAPE_OFFSET = 0
HAND_GLOBAL_OFFSET = HAND_SHAPES_DIM
POSE_COORDINATE_OFFSET = HAND_GLOBAL_OFFSET + HAND_GLOBAL_DIM
PAIR_GEOMETRY_OFFSET = POSE_COORDINATE_OFFSET + POSE_COORDINATE_DIM
PAIR_PRESENCE_OFFSET = PAIR_GEOMETRY_OFFSET + PAIR_GEOMETRY_DIM
HAND_PRESENCE_OFFSET = PAIR_PRESENCE_OFFSET + 1
POSE_PRESENCE_OFFSET = HAND_PRESENCE_OFFSET + MAX_HANDS
FEATURE_DIM = POSE_PRESENCE_OFFSET + POSE_LANDMARK_COUNT

LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_WRIST = 15
RIGHT_WRIST = 16
VISIBILITY_THRESHOLD = 0.35
EPSILON = 1e-6


def _as_landmarks(
    values: Sequence[Sequence[float]], expected: int, name: str
) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 2 or array.shape[0] != expected or array.shape[1] < COORDINATES:
        raise ValueError(f"{name} phải có shape ({expected}, 3 hoặc 4)")
    return array


def _visible(landmarks: np.ndarray, index: int) -> bool:
    point = landmarks[index]
    if not np.isfinite(point[:COORDINATES]).all():
        return False
    return point.shape[0] < 4 or float(point[3]) >= VISIBILITY_THRESHOLD


def _pose_is_usable(pose: np.ndarray | None) -> bool:
    if pose is None or not all(
        _visible(pose, index) for index in (0, LEFT_SHOULDER, RIGHT_SHOULDER)
    ):
        return False
    shoulders = pose[[LEFT_SHOULDER, RIGHT_SHOULDER], :COORDINATES]
    center_y = float(shoulders[:, 1].mean())
    width = float(np.linalg.norm(shoulders[0, :2] - shoulders[1, :2]))
    nose_above_shoulders = float(pose[0, 1]) < center_y - 0.03
    return 0.08 <= width <= 0.75 and center_y < 0.82 and nose_above_shoulders


def _assign_hands_to_pose(
    hands: list[np.ndarray], pose: np.ndarray | None
) -> list[np.ndarray | None]:
    """Assign hands to anatomical left/right slots using pose wrists.

    Image x-order is only a fallback. Pose wrist matching prevents slot flips
    when two hands cross, which is especially important for "Trường học".
    """

    slots: list[np.ndarray | None] = [None, None]
    if not hands:
        return slots
    hands = hands[:MAX_HANDS]
    if (
        pose is not None
        and _visible(pose, LEFT_WRIST)
        and _visible(pose, RIGHT_WRIST)
    ):
        wrist_targets = pose[[LEFT_WRIST, RIGHT_WRIST], :2]
        hand_wrists = np.stack([hand[0, :2] for hand in hands])
        distances = np.linalg.norm(
            hand_wrists[:, None, :] - wrist_targets[None, :, :], axis=-1
        )
        if len(hands) == 1:
            slots[int(np.argmin(distances[0]))] = hands[0]
            return slots
        direct = float(distances[0, 0] + distances[1, 1])
        crossed = float(distances[0, 1] + distances[1, 0])
        if direct <= crossed:
            slots = [hands[0], hands[1]]
        else:
            slots = [hands[1], hands[0]]
        return slots

    ordered = sorted(hands, key=lambda hand: float(hand[0, 0]))
    for index, hand in enumerate(ordered):
        slots[index] = hand
    return slots


def pack_landmarks_v4(
    hands: Iterable[Sequence[Sequence[float]]],
    pose: Sequence[Sequence[float]] | None,
) -> np.ndarray:
    """Pack hand shape and body-relative pose into a masked V4 frame.

    Hand shape is normalized around each wrist by palm size. Global hand and
    upper-body positions are normalized by shoulder center/width. Missing
    hands and low-visibility pose landmarks remain zero and are represented by
    explicit masks, never by fabricated coordinates.
    """

    hand_arrays = [
        _as_landmarks(hand, LANDMARKS_PER_HAND, "Mỗi bàn tay") for hand in hands
    ]
    pose_array = None if pose is None else _as_landmarks(pose, 33, "Pose")
    usable_pose = pose_array if _pose_is_usable(pose_array) else None
    slots = _assign_hands_to_pose(hand_arrays, usable_pose)
    packed = np.zeros(FEATURE_DIM, dtype=np.float32)

    shoulder_valid = bool(
        usable_pose is not None
        and _visible(usable_pose, LEFT_SHOULDER)
        and _visible(usable_pose, RIGHT_SHOULDER)
    )
    shoulder_center = np.zeros(COORDINATES, dtype=np.float32)
    shoulder_width = np.float32(1.0)
    if shoulder_valid and usable_pose is not None:
        shoulders = usable_pose[[LEFT_SHOULDER, RIGHT_SHOULDER], :COORDINATES]
        shoulder_center = shoulders.mean(axis=0)
        shoulder_width = np.float32(
            max(float(np.linalg.norm(shoulders[0, :2] - shoulders[1, :2])), 0.05)
        )

    for slot_index, hand in enumerate(slots):
        if hand is None:
            continue
        wrist = hand[0, :COORDINATES]
        palm_scale = max(
            float(np.linalg.norm(hand[9, :2] - hand[0, :2])), 0.025
        )
        shape = np.clip(
            (hand[:, :COORDINATES] - wrist) / palm_scale, -4.0, 4.0
        )
        shape_start = HAND_SHAPE_OFFSET + slot_index * HAND_SHAPE_DIM
        packed[shape_start : shape_start + HAND_SHAPE_DIM] = shape.reshape(-1)
        packed[HAND_PRESENCE_OFFSET + slot_index] = 1.0
        if shoulder_valid:
            global_start = HAND_GLOBAL_OFFSET + slot_index * COORDINATES
            packed[global_start : global_start + COORDINATES] = np.clip(
                (wrist - shoulder_center) / shoulder_width, -4.0, 4.0
            )

    if shoulder_valid and usable_pose is not None:
        for output_index, source_index in enumerate(POSE_SOURCE_INDICES):
            if not _visible(usable_pose, source_index):
                continue
            coordinate_start = POSE_COORDINATE_OFFSET + output_index * COORDINATES
            packed[coordinate_start : coordinate_start + COORDINATES] = np.clip(
                (usable_pose[source_index, :COORDINATES] - shoulder_center)
                / shoulder_width,
                -4.0,
                4.0,
            )
            packed[POSE_PRESENCE_OFFSET + output_index] = 1.0
    _set_pair_geometry_inplace(packed.reshape(1, FEATURE_DIM))
    return packed


def _set_pair_geometry_inplace(flat: np.ndarray) -> None:
    flat[:, PAIR_GEOMETRY_OFFSET:PAIR_PRESENCE_OFFSET] = 0.0
    flat[:, PAIR_PRESENCE_OFFSET] = 0.0
    pose = flat[:, POSE_COORDINATE_OFFSET:PAIR_GEOMETRY_OFFSET].reshape(
        -1, POSE_LANDMARK_COUNT, COORDINATES
    )
    pose_mask = flat[:, POSE_PRESENCE_OFFSET:]
    globals_ = flat[:, HAND_GLOBAL_OFFSET:POSE_COORDINATE_OFFSET].reshape(
        -1, MAX_HANDS, COORDINATES
    )
    hand_mask = flat[:, HAND_PRESENCE_OFFSET:POSE_PRESENCE_OFFSET]
    shoulders_available = (pose_mask[:, 5] > 0.5) & (pose_mask[:, 6] > 0.5)
    for frame_index in range(len(flat)):
        wrists: list[np.ndarray | None] = [None, None]
        for hand_index, pose_wrist_index in enumerate((9, 10)):
            if (
                shoulders_available[frame_index]
                and hand_mask[frame_index, hand_index] > 0.5
            ):
                wrists[hand_index] = globals_[frame_index, hand_index]
            elif pose_mask[frame_index, pose_wrist_index] > 0.5:
                wrists[hand_index] = pose[frame_index, pose_wrist_index]
        if wrists[0] is None or wrists[1] is None:
            continue
        delta = np.asarray(wrists[1]) - np.asarray(wrists[0])
        flat[
            frame_index,
            PAIR_GEOMETRY_OFFSET : PAIR_GEOMETRY_OFFSET + COORDINATES,
        ] = np.clip(delta, -8.0, 8.0)
        flat[frame_index, PAIR_GEOMETRY_OFFSET + 3] = min(
            float(np.linalg.norm(delta)), 8.0
        )
        flat[frame_index, PAIR_PRESENCE_OFFSET] = 1.0


def recompute_pair_geometry_v4(sequence: np.ndarray) -> np.ndarray:
    """Rebuild pair features after dropout or occlusion augmentation."""

    values = np.asarray(sequence, dtype=np.float32)
    if values.shape[-1] != FEATURE_DIM:
        raise ValueError(f"Feature cuối phải có kích thước {FEATURE_DIM}")
    output = values.copy()
    _set_pair_geometry_inplace(output.reshape(-1, FEATURE_DIM))
    return output


def mirror_sequence_v4(sequence: np.ndarray) -> np.ndarray:
    """Mirror shoulder-relative features and swap anatomical left/right."""

    values = np.asarray(sequence, dtype=np.float32)
    if values.shape[-1] != FEATURE_DIM:
        raise ValueError(f"Feature cuối phải có kích thước {FEATURE_DIM}")
    original_shape = values.shape
    flat = values.copy().reshape(-1, FEATURE_DIM)

    shapes = flat[:, HAND_SHAPE_OFFSET:HAND_GLOBAL_OFFSET].reshape(
        -1, MAX_HANDS, LANDMARKS_PER_HAND, COORDINATES
    )
    shapes[..., 0] *= -1.0
    shapes[:] = shapes[:, ::-1].copy()

    globals_ = flat[:, HAND_GLOBAL_OFFSET:POSE_COORDINATE_OFFSET].reshape(
        -1, MAX_HANDS, COORDINATES
    )
    globals_[..., 0] *= -1.0
    globals_[:] = globals_[:, ::-1].copy()

    pose = flat[:, POSE_COORDINATE_OFFSET:PAIR_GEOMETRY_OFFSET].reshape(
        -1, POSE_LANDMARK_COUNT, COORDINATES
    )
    pose[..., 0] *= -1.0
    pose_mask = flat[:, POSE_PRESENCE_OFFSET:].reshape(-1, POSE_LANDMARK_COUNT)
    # nose is central; eyes, mouth, shoulders, elbows and wrists are paired.
    for left, right in ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10)):
        pose[:, [left, right]] = pose[:, [right, left]].copy()
        pose_mask[:, [left, right]] = pose_mask[:, [right, left]].copy()

    hand_mask = flat[:, HAND_PRESENCE_OFFSET:POSE_PRESENCE_OFFSET]
    hand_mask[:] = hand_mask[:, ::-1].copy()
    pair = flat[:, PAIR_GEOMETRY_OFFSET:PAIR_PRESENCE_OFFSET]
    # Pair direction is anatomical right-minus-left. Mirroring x and then
    # swapping sides keeps dx, while dy and dz change sign.
    pair[:, 1:3] *= -1.0
    return flat.reshape(original_shape)


def frame_presence(sequence: np.ndarray) -> np.ndarray:
    values = np.asarray(sequence)
    hand = values[..., HAND_PRESENCE_OFFSET:POSE_PRESENCE_OFFSET].max(axis=-1)
    # Shoulders/elbows/wrists keep an occluded two-hand sign alive.
    arm = values[..., POSE_PRESENCE_OFFSET + 5 :].max(axis=-1)
    return np.maximum(hand, arm)


class UnifiedLandmarkV4(nn.Module):
    """One compact keyframe + trajectory network for all common-20 signs."""

    def __init__(
        self,
        class_count: int,
        *,
        feature_dim: int = FEATURE_DIM,
        width: int = 112,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.frame_encoder = nn.Sequential(
            nn.Linear(feature_dim, width),
            nn.LayerNorm(width),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.motion_encoder = nn.Sequential(
            nn.Linear(feature_dim, width),
            nn.LayerNorm(width),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.position = nn.Parameter(torch.zeros(1, SEQUENCE_LENGTH, width))
        nn.init.normal_(self.position, mean=0.0, std=0.015)
        self.temporal = nn.Sequential(
            TemporalResidualBlock(width, dilation=1, dropout=dropout),
            TemporalResidualBlock(width, dilation=2, dropout=dropout),
            TemporalResidualBlock(width, dilation=4, dropout=dropout),
        )
        self.key_attention = nn.Conv1d(width, 1, kernel_size=1)
        self.key_classifier = nn.Sequential(
            nn.Linear(width, width), nn.GELU(), nn.Dropout(dropout), nn.Linear(width, class_count)
        )
        # Four ordered temporal bins + masked mean/max/std retain the whole path.
        self.trajectory_classifier = nn.Sequential(
            nn.Linear(width * 7, width * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width * 2, class_count),
        )

    @staticmethod
    def _active_mask(inputs: torch.Tensor) -> torch.Tensor:
        hand = inputs[
            ..., HAND_PRESENCE_OFFSET:POSE_PRESENCE_OFFSET
        ].amax(dim=-1)
        arm = inputs[..., POSE_PRESENCE_OFFSET + 5 :].amax(dim=-1)
        active = torch.maximum(hand, arm)
        any_active = active.amax(dim=1, keepdim=True) > 0.5
        return torch.where(any_active, active, torch.ones_like(active))

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        active = self._active_mask(inputs)
        differences = torch.cat(
            (torch.zeros_like(inputs[:, :1]), inputs[:, 1:] - inputs[:, :-1]),
            dim=1,
        )
        adjacent = torch.cat(
            (active[:, :1], active[:, 1:] * active[:, :-1]), dim=1
        )
        differences = differences * adjacent.unsqueeze(-1)
        encoded = (
            self.frame_encoder(inputs)
            + 0.55 * self.motion_encoder(differences)
            + self.position
        ).transpose(1, 2)
        encoded = self.temporal(encoded)

        attention_logits = self.key_attention(encoded).squeeze(1)
        attention_logits = attention_logits.masked_fill(active <= 0.5, -1e4)
        attention = torch.softmax(attention_logits, dim=1)
        keyframe = (encoded * attention.unsqueeze(1)).sum(dim=2)

        mask = active.unsqueeze(1)
        denominator = mask.sum(dim=2).clamp(min=1.0)
        mean = (encoded * mask).sum(dim=2) / denominator
        maximum = encoded.masked_fill(mask <= 0.5, -1e4).amax(dim=2)
        variance = ((encoded - mean.unsqueeze(2)).square() * mask).sum(dim=2)
        standard_deviation = torch.sqrt(variance / denominator + 1e-6)

        batch = encoded.shape[0]
        ordered = encoded.reshape(batch, encoded.shape[1], 4, 4)
        ordered_mask = mask.reshape(batch, 1, 4, 4)
        ordered_pool = (
            (ordered * ordered_mask).sum(dim=3)
            / ordered_mask.sum(dim=3).clamp(min=1.0)
        ).flatten(start_dim=1)
        trajectory = torch.cat(
            (ordered_pool, mean, maximum, standard_deviation), dim=1
        )
        return self.key_classifier(keyframe) + 0.55 * self.trajectory_classifier(
            trajectory
        )
