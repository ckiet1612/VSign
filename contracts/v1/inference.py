from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


FRAME_COUNT = 16
FRAME_SIZE = 224
PROTOCOL_VERSION = "1.0"
SUPPORTED_MIME_TYPES = ("image/jpeg", "image/webp")


class PredictionStatus(str, Enum):
    OK = "ok"
    UNCERTAIN = "uncertain"
    NO_HANDS = "no_hands"
    BAD_FRAMING = "bad_framing"
    BUSY = "busy"
    ERROR = "error"


class FramesMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["frames"]
    session_id: UUID
    sequence: int = Field(strict=True, ge=0)
    captured_at: int = Field(strict=True, ge=0)
    frames: List[str] = Field(min_length=FRAME_COUNT, max_length=FRAME_COUNT)


class PredictionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class PredictionMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["prediction"] = "prediction"
    sequence: int = Field(strict=True, ge=0)
    status: PredictionStatus
    label: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    top_k: List[PredictionCandidate] = Field(default_factory=list, max_length=3)
    model_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_success_shape(self) -> "PredictionMessage":
        if self.status == PredictionStatus.OK:
            if self.label is None or self.confidence is None or not self.top_k:
                raise ValueError("prediction ok phải có label, confidence và top_k")
        return self


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    backend: str
    model_version: str
    protocol_version: str = PROTOCOL_VERSION


class MetadataResponse(BaseModel):
    backend: str
    model_version: str
    protocol_version: str = PROTOCOL_VERSION
    frame_count: int = FRAME_COUNT
    frame_width: int = FRAME_SIZE
    frame_height: int = FRAME_SIZE
    supported_image_formats: List[str]
    confidence_threshold: float
    margin_threshold: float
    labels: List[str]
    candidate_labels_unverified: bool
    mock: bool
    collection_enabled: bool = False
    collection_target_per_hand: int = 5


class CollectionHand(str, Enum):
    RIGHT = "right"
    LEFT = "left"


class CollectionSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    captured_at: int = Field(strict=True, ge=0)
    duration_ms: int = Field(strict=True, ge=650, le=3150)
    expected_label: str = Field(min_length=1, max_length=80)
    hand: CollectionHand
    # Collection keeps the complete 13 FPS source clip for frozen A/B replay;
    # websocket inference remains fixed at exactly 16 sampled frames.
    frames: List[str] = Field(min_length=8, max_length=42)
    predicted_label: Optional[str] = Field(default=None, min_length=1, max_length=80)
    predicted_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    distance: Literal["near", "standard", "far"] = "standard"
    lighting: Literal["normal", "low", "side"] = "normal"
    negative_action: Optional[
        Literal[
            "still",
            "hand_enter_exit",
            "adjust_hair_glasses",
            "touch_face",
            "turn_body",
            "random_motion",
            "overlap_hands",
            "other_sign",
        ]
    ] = None


class CollectionHandCounts(BaseModel):
    right: int = Field(ge=0)
    left: int = Field(ge=0)


class CollectionSummaryResponse(BaseModel):
    enabled: bool
    target_per_hand: int = Field(ge=1)
    counts: Dict[str, CollectionHandCounts]


class CollectionSampleResponse(BaseModel):
    status: Literal["saved"] = "saved"
    sample_id: str = Field(min_length=1)
    expected_label: str = Field(min_length=1)
    hand: CollectionHand
    relative_video_path: str = Field(min_length=1)
    label_hand_count: int = Field(ge=1)
