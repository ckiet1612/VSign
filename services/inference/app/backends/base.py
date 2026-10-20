from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple

from PIL import Image

from app.models import PredictionStatus


@dataclass(frozen=True)
class DecodedFrame:
    image: Image.Image
    encoded_bytes: bytes


@dataclass(frozen=True)
class BackendCandidate:
    label: str
    confidence: float


@dataclass(frozen=True)
class BackendPrediction:
    status: PredictionStatus
    label: str | None
    confidence: float | None
    top_k: List[BackendCandidate]
    # Full softmax over the label map, for the per-word/context decision policy.
    probabilities: Optional[Tuple[float, ...]] = None


class InferenceBackend(Protocol):
    name: str
    model_version: str
    labels: Sequence[str]
    candidate_labels_unverified: bool
    is_mock: bool

    def predict(
        self, frames: Sequence[DecodedFrame], sequence: int
    ) -> BackendPrediction:
        """Run one blocking inference request."""
        ...
