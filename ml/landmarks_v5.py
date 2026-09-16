from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import torch
from torch import nn

from ml.landmarks_v2 import (
    FEATURE_DIM as BASELINE_FEATURE_DIM,
    SEQUENCE_LENGTH,
    LandmarkKeyframeNet,
    TemporalResidualBlock,
    mirror_sequence as mirror_baseline_sequence,
    pack_landmarks as pack_baseline_landmarks,
)
from ml.landmarks_v4 import (
    FEATURE_DIM as V4_FEATURE_DIM,
    HAND_GLOBAL_OFFSET,
    POSE_PRESENCE_OFFSET,
    mirror_sequence_v4,
    pack_landmarks_v4,
)


# V5 deliberately retains the exact V3 frame as its first block.  Only the
# body-relative context from V4 is appended; normalized hand shapes from V4 are
# omitted because the frozen V3 branch already owns hand-shape classification.
CONTEXT_SOURCE_OFFSET = HAND_GLOBAL_OFFSET
CONTEXT_DIM = V4_FEATURE_DIM - CONTEXT_SOURCE_OFFSET
CONTEXT_OFFSET = BASELINE_FEATURE_DIM
FEATURE_DIM = BASELINE_FEATURE_DIM + CONTEXT_DIM

CONTEXT_POSE_PRESENCE_OFFSET = POSE_PRESENCE_OFFSET - CONTEXT_SOURCE_OFFSET
LEFT_SHOULDER_CONTEXT_MASK = CONTEXT_POSE_PRESENCE_OFFSET + 5
RIGHT_SHOULDER_CONTEXT_MASK = CONTEXT_POSE_PRESENCE_OFFSET + 6

DEFAULT_FOCUS_LABELS = ("Uống", "Ăn", "Trường học", "Nói", "Đâu")


def pack_landmarks_v5(
    hands: Iterable[Sequence[Sequence[float]]],
    pose: Sequence[Sequence[float]] | None,
) -> np.ndarray:
    """Pack the exact V3 hand frame plus bounded V4 body context."""

    hand_values = [np.asarray(hand, dtype=np.float32) for hand in hands]
    baseline_hands = [hand[:, :3] for hand in hand_values]
    baseline = pack_baseline_landmarks(baseline_hands)
    contextual = pack_landmarks_v4(hand_values, pose)
    return np.concatenate(
        (baseline, contextual[CONTEXT_SOURCE_OFFSET:]), dtype=np.float32
    )


def combine_v3_v4_sequences(
    baseline_sequences: np.ndarray, contextual_sequences: np.ndarray
) -> np.ndarray:
    """Join aligned V3/V4 sequences without changing either source."""

    baseline = np.asarray(baseline_sequences, dtype=np.float32)
    contextual = np.asarray(contextual_sequences, dtype=np.float32)
    if baseline.shape[:-1] != contextual.shape[:-1]:
        raise ValueError("Chuỗi V3 và V4 phải có cùng batch/frame")
    if baseline.shape[-1] != BASELINE_FEATURE_DIM:
        raise ValueError(f"Feature V3 phải có kích thước {BASELINE_FEATURE_DIM}")
    if contextual.shape[-1] != V4_FEATURE_DIM:
        raise ValueError(f"Feature V4 phải có kích thước {V4_FEATURE_DIM}")
    return np.concatenate(
        (baseline, contextual[..., CONTEXT_SOURCE_OFFSET:]), axis=-1
    ).astype(np.float32, copy=False)


def split_v5_sequence(sequence: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(sequence, dtype=np.float32)
    if values.shape[-1] != FEATURE_DIM:
        raise ValueError(f"Feature V5 phải có kích thước {FEATURE_DIM}")
    baseline = values[..., :BASELINE_FEATURE_DIM]
    contextual = np.zeros((*values.shape[:-1], V4_FEATURE_DIM), dtype=np.float32)
    contextual[..., CONTEXT_SOURCE_OFFSET:] = values[..., CONTEXT_OFFSET:]
    return baseline, contextual


def mirror_sequence_v5(sequence: np.ndarray) -> np.ndarray:
    """Mirror both blocks using their original, train-serving-parity rules."""

    baseline, contextual = split_v5_sequence(sequence)
    mirrored_baseline = mirror_baseline_sequence(baseline)
    mirrored_contextual = mirror_sequence_v4(contextual)
    return np.concatenate(
        (
            mirrored_baseline,
            mirrored_contextual[..., CONTEXT_SOURCE_OFFSET:],
        ),
        axis=-1,
    ).astype(np.float32, copy=False)


class GuardedLandmarkV5(nn.Module):
    """Frozen V3 with a small, masked and bounded context correction.

    The residual branch cannot alter non-focus logits.  It is disabled when
    both shoulders are unavailable, making V5 exactly equal to V3 in that case.
    """

    def __init__(
        self,
        class_count: int,
        *,
        focus_indices: Sequence[int],
        width: int = 48,
        dropout: float = 0.18,
        max_logit_correction: float = 1.25,
    ) -> None:
        super().__init__()
        self.baseline = LandmarkKeyframeNet(class_count)
        for parameter in self.baseline.parameters():
            parameter.requires_grad_(False)

        self.context_frame_encoder = nn.Sequential(
            nn.Linear(CONTEXT_DIM, width),
            nn.LayerNorm(width),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.context_motion_encoder = nn.Sequential(
            nn.Linear(CONTEXT_DIM, width),
            nn.LayerNorm(width),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.context_position = nn.Parameter(torch.zeros(1, SEQUENCE_LENGTH, width))
        nn.init.normal_(self.context_position, mean=0.0, std=0.012)
        self.context_temporal = nn.Sequential(
            TemporalResidualBlock(width, dilation=1, dropout=dropout),
            TemporalResidualBlock(width, dilation=2, dropout=dropout),
        )
        self.context_attention = nn.Conv1d(width, 1, kernel_size=1)
        self.context_classifier = nn.Sequential(
            nn.Linear(width * 7, width * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(width * 2, class_count),
        )
        # Starting V5 is bit-for-bit V3. Training must earn every correction.
        nn.init.zeros_(self.context_classifier[-1].weight)
        nn.init.zeros_(self.context_classifier[-1].bias)

        correction_mask = torch.zeros(class_count, dtype=torch.float32)
        correction_mask[list(focus_indices)] = 1.0
        self.register_buffer("correction_mask", correction_mask)
        self.register_buffer(
            "max_logit_correction",
            torch.tensor(float(max_logit_correction), dtype=torch.float32),
        )

    def train(self, mode: bool = True) -> GuardedLandmarkV5:
        super().train(mode)
        # Frozen BatchNorm and Dropout must retain the exact V3 inference path.
        self.baseline.eval()
        return self

    def load_baseline_state(self, state: dict[str, torch.Tensor]) -> None:
        self.baseline.load_state_dict(state, strict=True)
        self.baseline.eval()

    @staticmethod
    def _pose_available(context: torch.Tensor) -> torch.Tensor:
        shoulders = torch.minimum(
            context[..., LEFT_SHOULDER_CONTEXT_MASK],
            context[..., RIGHT_SHOULDER_CONTEXT_MASK],
        )
        return shoulders.amax(dim=1, keepdim=True)

    def context_correction(
        self, inputs: torch.Tensor, baseline_logits: torch.Tensor
    ) -> torch.Tensor:
        context = inputs[..., CONTEXT_OFFSET:]
        pose_available = self._pose_available(context)
        active = torch.minimum(
            inputs[..., BASELINE_FEATURE_DIM - 2 :].amax(dim=-1),
            torch.minimum(
                context[..., LEFT_SHOULDER_CONTEXT_MASK],
                context[..., RIGHT_SHOULDER_CONTEXT_MASK],
            ),
        )
        differences = torch.cat(
            (torch.zeros_like(context[:, :1]), context[:, 1:] - context[:, :-1]),
            dim=1,
        )
        adjacent = torch.cat(
            (active[:, :1], active[:, 1:] * active[:, :-1]), dim=1
        )
        differences = differences * adjacent.unsqueeze(-1)
        encoded = (
            self.context_frame_encoder(context)
            + 0.45 * self.context_motion_encoder(differences)
            + self.context_position
        ).transpose(1, 2)
        encoded = self.context_temporal(encoded)

        has_active = active.amax(dim=1, keepdim=True) > 0.5
        safe_active = torch.where(has_active, active, torch.ones_like(active))
        attention_logits = self.context_attention(encoded).squeeze(1)
        attention_logits = attention_logits.masked_fill(safe_active <= 0.5, -1e4)
        attention = torch.softmax(attention_logits, dim=1)
        keyframe = (encoded * attention.unsqueeze(1)).sum(dim=2)

        mask = safe_active.unsqueeze(1)
        denominator = mask.sum(dim=2).clamp(min=1.0)
        mean = (encoded * mask).sum(dim=2) / denominator
        maximum = encoded.masked_fill(mask <= 0.5, -1e4).amax(dim=2)
        batch = encoded.shape[0]
        ordered = encoded.reshape(batch, encoded.shape[1], 4, 4)
        ordered_mask = mask.reshape(batch, 1, 4, 4)
        ordered_pool = (
            (ordered * ordered_mask).sum(dim=3)
            / ordered_mask.sum(dim=3).clamp(min=1.0)
        ).flatten(start_dim=1)
        pooled = torch.cat((keyframe, ordered_pool, mean, maximum), dim=1)
        correction = torch.tanh(self.context_classifier(pooled))
        # If V3 already selects one of the 15 stable classes, V5 is exactly V3.
        # The branch only resolves ambiguity inside the observed focus group.
        focus_gate = self.correction_mask[
            baseline_logits.argmax(dim=1)
        ].unsqueeze(1)
        return (
            correction
            * self.max_logit_correction
            * self.correction_mask
            * pose_available
            * focus_gate
            * has_active.to(correction.dtype)
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        baseline_logits = self.baseline(inputs[..., :BASELINE_FEATURE_DIM])
        return baseline_logits + self.context_correction(inputs, baseline_logits)
