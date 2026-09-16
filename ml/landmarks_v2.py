from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import torch
from torch import nn


SEQUENCE_LENGTH = 16
MAX_HANDS = 2
LANDMARKS_PER_HAND = 21
COORDINATES_PER_LANDMARK = 3
HAND_FEATURES = LANDMARKS_PER_HAND * COORDINATES_PER_LANDMARK
FEATURE_DIM = MAX_HANDS * HAND_FEATURES + MAX_HANDS


def pack_landmarks(hands: Iterable[Sequence[Sequence[float]]]) -> np.ndarray:
    """Pack at most two hands in left-to-right image order.

    Each hand must contain the 21 MediaPipe landmarks in x/y/z order. A
    presence bit per slot is appended so missing hands are unambiguous.
    """

    arrays = []
    for hand in hands:
        values = np.asarray(hand, dtype=np.float32)
        if values.shape != (LANDMARKS_PER_HAND, COORDINATES_PER_LANDMARK):
            raise ValueError(
                "Mỗi bàn tay phải có shape "
                f"({LANDMARKS_PER_HAND}, {COORDINATES_PER_LANDMARK})"
            )
        arrays.append(values)
    arrays.sort(key=lambda values: float(values[0, 0]))
    arrays = arrays[:MAX_HANDS]

    packed = np.zeros(FEATURE_DIM, dtype=np.float32)
    for index, values in enumerate(arrays):
        start = index * HAND_FEATURES
        packed[start : start + HAND_FEATURES] = values.reshape(-1)
        packed[MAX_HANDS * HAND_FEATURES + index] = 1.0
    return packed


def mirror_sequence(sequence: np.ndarray) -> np.ndarray:
    """Mirror a sequence and preserve canonical left-to-right hand slots."""

    values = np.asarray(sequence, dtype=np.float32)
    if values.shape[-1] != FEATURE_DIM:
        raise ValueError(f"Feature cuối phải có kích thước {FEATURE_DIM}")
    output = values.copy()
    original_shape = output.shape
    flat = output.reshape(-1, FEATURE_DIM)
    hands = flat[:, : MAX_HANDS * HAND_FEATURES].reshape(
        -1, MAX_HANDS, LANDMARKS_PER_HAND, COORDINATES_PER_LANDMARK
    )
    presence = flat[:, -MAX_HANDS:]
    hands[..., 0] = 1.0 - hands[..., 0]

    both = (presence[:, 0] > 0.5) & (presence[:, 1] > 0.5)
    if np.any(both):
        hands[both] = hands[both, ::-1]
        presence[both] = presence[both, ::-1]
    return flat.reshape(original_shape)


def hand_presence(sequence: np.ndarray) -> np.ndarray:
    values = np.asarray(sequence)
    return values[..., -MAX_HANDS:].max(axis=-1)


class TemporalResidualBlock(nn.Module):
    def __init__(self, width: int, dilation: int, dropout: float) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Conv1d(width, width, kernel_size=3, padding=dilation, dilation=dilation),
            nn.BatchNorm1d(width),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Conv1d(width, width, kernel_size=3, padding=dilation, dilation=dilation),
            nn.BatchNorm1d(width),
        )
        self.activation = nn.ReLU(inplace=True)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.activation(inputs + self.network(inputs))


class LandmarkTCN(nn.Module):
    """Small temporal model intended for ONNX inference in the browser."""

    def __init__(
        self,
        class_count: int,
        *,
        feature_dim: int = FEATURE_DIM,
        width: int = 128,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.frame_encoder = nn.Sequential(
            nn.Linear(feature_dim, width),
            nn.LayerNorm(width),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
        )
        self.temporal = nn.Sequential(
            TemporalResidualBlock(width, dilation=1, dropout=dropout),
            TemporalResidualBlock(width, dilation=2, dropout=dropout),
        )
        self.attention = nn.Conv1d(width, 1, kernel_size=1)
        self.classifier = nn.Sequential(
            nn.Linear(width * 2, width),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(width, class_count),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        presence = inputs[..., -MAX_HANDS:].amax(dim=-1)
        encoded = self.frame_encoder(inputs).transpose(1, 2)
        encoded = self.temporal(encoded)
        weights = torch.sigmoid(self.attention(encoded).squeeze(1)) * presence
        denominator = weights.sum(dim=1, keepdim=True).clamp(min=1e-6)
        mean = (encoded * weights.unsqueeze(1)).sum(dim=2) / denominator
        centered = encoded - mean.unsqueeze(2)
        variance = (centered.square() * weights.unsqueeze(1)).sum(dim=2) / denominator
        pooled = torch.cat((mean, torch.sqrt(variance + 1e-6)), dim=1)
        return self.classifier(pooled)


class LandmarkKeyframeNet(nn.Module):
    """Prioritize a learned decisive frame, then use ordered motion as context."""

    def __init__(
        self,
        class_count: int,
        *,
        feature_dim: int = FEATURE_DIM,
        width: int = 96,
        dropout: float = 0.18,
    ) -> None:
        super().__init__()
        self.frame_encoder = nn.Sequential(
            nn.Linear(feature_dim, width),
            nn.LayerNorm(width),
            nn.ReLU(inplace=True),
        )
        self.motion_encoder = nn.Sequential(
            nn.Linear(feature_dim, width),
            nn.LayerNorm(width),
            nn.ReLU(inplace=True),
        )
        self.position = nn.Parameter(torch.zeros(1, SEQUENCE_LENGTH, width))
        nn.init.normal_(self.position, mean=0.0, std=0.015)
        self.temporal = nn.Sequential(
            TemporalResidualBlock(width, dilation=1, dropout=dropout),
            TemporalResidualBlock(width, dilation=2, dropout=dropout),
        )
        self.key_attention = nn.Conv1d(width, 1, kernel_size=1)
        self.primary_classifier = nn.Sequential(
            nn.Linear(width, width),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(width, class_count),
        )
        self.context_classifier = nn.Sequential(
            nn.Linear(width * 6, width * 2),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(width * 2, class_count),
        )

    @staticmethod
    def canonicalize(inputs: torch.Tensor) -> torch.Tensor:
        hands = inputs[..., : MAX_HANDS * HAND_FEATURES].reshape(
            inputs.shape[0],
            inputs.shape[1],
            MAX_HANDS,
            LANDMARKS_PER_HAND,
            COORDINATES_PER_LANDMARK,
        )
        presence = inputs[..., -MAX_HANDS:]
        wrist = hands[..., :1, :]
        palm_scale = torch.linalg.vector_norm(
            hands[..., 9, :2] - hands[..., 0, :2], dim=-1
        ).clamp(min=0.04)
        relative = (hands - wrist) / palm_scale[..., None, None]
        # Landmark 0 retains global wrist location; the remaining landmarks
        # describe hand shape independent of signer distance and hand size.
        canonical_hands = torch.cat((wrist, relative[..., 1:, :]), dim=-2)
        canonical_hands = canonical_hands * presence[..., None, None]
        return torch.cat(
            (canonical_hands.flatten(start_dim=-3), presence), dim=-1
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        presence = inputs[..., -MAX_HANDS:].amax(dim=-1)
        differences = torch.cat(
            (torch.zeros_like(inputs[:, :1]), inputs[:, 1:] - inputs[:, :-1]),
            dim=1,
        )
        encoded = (
            self.frame_encoder(self.canonicalize(inputs))
            + 0.5 * self.motion_encoder(differences)
            + self.position
        ).transpose(1, 2)
        encoded = self.temporal(encoded)

        attention_logits = self.key_attention(encoded).squeeze(1)
        attention_logits = attention_logits.masked_fill(presence <= 0.5, -1e4)
        attention = torch.softmax(attention_logits, dim=1)
        keyframe = (encoded * attention.unsqueeze(1)).sum(dim=2)

        mask = presence.unsqueeze(1)
        denominator = mask.sum(dim=2).clamp(min=1.0)
        mean = (encoded * mask).sum(dim=2) / denominator
        maximum = encoded.masked_fill(mask <= 0.5, -1e4).amax(dim=2)

        batch = encoded.shape[0]
        ordered = encoded.reshape(batch, encoded.shape[1], 4, 4)
        ordered_mask = mask.reshape(batch, 1, 4, 4)
        ordered_sum = (ordered * ordered_mask).sum(dim=3)
        ordered_denominator = ordered_mask.sum(dim=3).clamp(min=1.0)
        ordered_pool = (ordered_sum / ordered_denominator).flatten(start_dim=1)

        context = torch.cat((ordered_pool, mean, maximum), dim=1)
        primary_logits = self.primary_classifier(keyframe)
        context_logits = self.context_classifier(context)
        return primary_logits + 0.45 * context_logits


@dataclass(frozen=True)
class SplitIndices:
    train: np.ndarray
    validation: np.ndarray


def stratified_hand_split(
    labels: np.ndarray,
    hands: Sequence[str],
    *,
    validation_fraction: float = 0.2,
    seed: int = 20260911,
) -> SplitIndices:
    """Keep every label/recorded-hand group represented in validation."""

    labels = np.asarray(labels, dtype=np.int64)
    if len(labels) != len(hands):
        raise ValueError("labels và hands phải có cùng số mẫu")
    rng = np.random.default_rng(seed)
    train: list[int] = []
    validation: list[int] = []
    groups: dict[tuple[int, str], list[int]] = {}
    for index, (label, hand) in enumerate(zip(labels.tolist(), hands)):
        groups.setdefault((int(label), str(hand)), []).append(index)
    for indices in groups.values():
        shuffled = np.asarray(indices, dtype=np.int64)
        rng.shuffle(shuffled)
        validation_count = max(1, int(round(len(shuffled) * validation_fraction)))
        validation_count = min(validation_count, max(1, len(shuffled) - 1))
        validation.extend(shuffled[:validation_count].tolist())
        train.extend(shuffled[validation_count:].tolist())
    return SplitIndices(
        train=np.asarray(sorted(train), dtype=np.int64),
        validation=np.asarray(sorted(validation), dtype=np.int64),
    )
