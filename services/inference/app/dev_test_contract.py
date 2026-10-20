"""Private development contracts; the deployed inference contract is unchanged."""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import CollectionHand


class TrialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trial_id: UUID
    session_id: UUID
    signer_id: str = Field(min_length=1, max_length=80)
    expected_label: str = Field(min_length=1, max_length=80)
    hand: CollectionHand
    distance: Literal["near", "standard", "far"]
    lighting: Literal["normal", "low", "side"]
    negative_action: Optional[Literal["still", "hand_enter_exit", "adjust_hair_glasses", "touch_face",
                                      "turn_body", "random_motion", "overlap_hands", "other_sign"]] = None
    captured_at: int = Field(strict=True, ge=0)
    duration_ms: int = Field(strict=True, ge=0, le=3150)
    frames: list[str] = Field(default_factory=list, max_length=16)
    source_frames: list[str] = Field(default_factory=list, max_length=42)
    pipeline: Literal["manual-server-uniform-center-square-v1"]
    runtime_key: Optional[str] = None
    technical_error: Optional[str] = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_capture(self):
        if not self.signer_id.strip():
            raise ValueError("Signer identity is required")
        if self.expected_label == "Không ký hiệu" and not self.negative_action:
            raise ValueError("Negative capture requires an action")
        if self.expected_label != "Không ký hiệu" and self.negative_action is not None:
            raise ValueError("Positive capture must not have a negative action")
        if self.technical_error is None and (len(self.frames) != 16 or not 8 <= len(self.source_frames) <= 42
                                             or self.duration_ms < 650):
            raise ValueError("A valid capture requires 16 inference frames and 8..42 source frames")
        if self.technical_error is not None and (self.frames or self.source_frames):
            raise ValueError("Technical capture failures must not claim model results")
        return self


class TrialReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool = Field(strict=True)
    notes: str = Field(max_length=2000)
    reviewer: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def require_exclusion_reason(self):
        if not self.reviewer.strip() or not self.valid and not self.notes.strip():
            raise ValueError("Reviewer and exclusion reason are required")
        return self
