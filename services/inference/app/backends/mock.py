from __future__ import annotations

import hashlib
from typing import Optional, Sequence

from app.backends.base import (
    BackendCandidate,
    BackendPrediction,
    DecodedFrame,
)
from app.models import PredictionStatus


# Deterministic UI-only labels aligned with the ViSignLanguage common-20 output
# order. This is still a mock and must never be presented as an AI prediction.
MOCK_CANDIDATE_LABELS = (
    "chào",
    "cảm ơn",
    "xin lỗi",
    "tôi",
    "đi",
    "uống",
    "ăn",
    "nhà",
    "trường học",
    "bệnh viện",
    "giúp",
    "đồng ý",
    "nói",
    "nghe",
    "mua",
    "đâu",
    "nhìn",
    "cho",
    "biết",
    "có thể",
)


class MockInferenceBackend:
    name = "mock"
    labels = MOCK_CANDIDATE_LABELS
    candidate_labels_unverified = True
    is_mock = True

    def __init__(
        self,
        model_version: str = "mock-common-20-v1",
        forced_status: Optional[PredictionStatus] = None,
    ) -> None:
        self.model_version = model_version
        # Test-only constructor seam; it is intentionally not wired to the API or env.
        self._forced_status = forced_status

    def predict(
        self, frames: Sequence[DecodedFrame], sequence: int
    ) -> BackendPrediction:
        if self._forced_status is not None and self._forced_status != PredictionStatus.OK:
            return BackendPrediction(
                status=self._forced_status,
                label=None,
                confidence=None,
                top_k=[],
            )

        digest = hashlib.sha256()
        digest.update(sequence.to_bytes(8, byteorder="big", signed=False))
        for frame in frames:
            digest.update(frame.encoded_bytes)
        checksum = digest.digest()

        first_index = int.from_bytes(checksum[:4], "big") % len(self.labels)
        label_indices = [
            first_index,
            (first_index + 1 + checksum[4] % 8) % len(self.labels),
            (first_index + 9 + checksum[5] % 8) % len(self.labels),
        ]
        while len(set(label_indices)) < 3:
            label_indices[-1] = (label_indices[-1] + 1) % len(self.labels)

        top_confidence = round(0.78 + (checksum[6] / 255) * 0.16, 4)
        confidences = [top_confidence, round(top_confidence * 0.22, 4), round(top_confidence * 0.08, 4)]
        top_k = [
            BackendCandidate(self.labels[index], confidence)
            for index, confidence in zip(label_indices, confidences)
        ]
        return BackendPrediction(
            status=PredictionStatus.OK,
            label=top_k[0].label,
            confidence=top_k[0].confidence,
            top_k=top_k,
        )
