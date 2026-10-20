from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


WORKSPACE_API_VERSION = "1"
WORKSPACE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
WORKSPACE_ROLES = ("owner", "admin", "operator", "reviewer", "viewer")
INTERNAL_ROLES = ("model_admin", "system_admin")


class AuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class AuthenticatedUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=36)
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["owner", "admin", "operator", "reviewer", "viewer", "model_admin", "system_admin"]


class AuthSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: Literal[True] = True
    auth_mode: Literal["session", "local_admin"] = "session"
    user: AuthenticatedUser


class AuthLogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: Literal[False] = False


class WorkspaceContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: Literal["1"] = WORKSPACE_API_VERSION
    workspace_id: str = Field(pattern=WORKSPACE_ID_PATTERN, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    environment: Literal["development", "production"]
    scope_source: Literal["local-config"] = "local-config"
    auth_required: bool = False


class WorkspaceCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overview: bool
    recognize: bool
    data: bool
    evaluation: bool
    monitoring: bool
    models: bool
    activity: bool
    integrations: bool
    team: bool
    settings: bool


class WorkspaceCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: Literal["1"] = WORKSPACE_API_VERSION
    workspace_id: str = Field(pattern=WORKSPACE_ID_PATTERN, min_length=1, max_length=64)
    capabilities: WorkspaceCapabilities


class WorkspaceMemberResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=36)
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["owner", "admin", "operator", "reviewer", "viewer", "model_admin", "system_admin"]
    active: bool


class WorkspaceMembersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: Literal["1"] = WORKSPACE_API_VERSION
    workspace_id: str = Field(pattern=WORKSPACE_ID_PATTERN, min_length=1, max_length=64)
    members: List[WorkspaceMemberResponse] = Field(default_factory=list)


class WorkspaceAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    workspace_id: str = Field(pattern=WORKSPACE_ID_PATTERN, min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=120)
    actor_type: Literal["system", "user", "service"]
    actor_id: Optional[str] = Field(default=None, min_length=1, max_length=120)
    occurred_at: datetime
    resource_type: Optional[str] = Field(default=None, min_length=1, max_length=120)
    resource_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    outcome: Literal["success", "failure"]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceAuditPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_version: Literal["1"] = WORKSPACE_API_VERSION
    workspace_id: str = Field(pattern=WORKSPACE_ID_PATTERN, min_length=1, max_length=64)
    events: List[WorkspaceAuditEvent] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: bool = False
    source: Literal["not_configured", "store"] = "not_configured"


class WorkspaceClientEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["model.switched", "collection.started", "collection.paused", "collection.resumed",
                        "collection.stopped", "collection.completed", "collection.sample_saved"]
    resource_id: UUID
    model_version: str = Field(min_length=1, max_length=120)
    previous_model_version: Optional[str] = Field(default=None, min_length=1, max_length=120)
    model_option: Optional[Literal["current", "seated"]] = None
    previous_model_option: Optional[Literal["current", "seated"]] = None
    capture_session_id: Optional[UUID] = None
    saved_samples: Optional[int] = Field(default=None, ge=0, le=1000000)
    sample_id: Optional[UUID] = None
    reason: Optional[Literal["manual", "capture_error", "save_error", "navigation", "camera_off", "completed", "context_changed"]] = None

    @field_validator("model_version", "previous_model_version")
    @classmethod
    def nonblank_model(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Model version không được trống")
        return value

    @model_validator(mode="after")
    def event_shape(self) -> "WorkspaceClientEventRequest":
        if self.event_type == "model.switched":
            if not self.previous_model_version or not self.model_option or not self.previous_model_option or self.model_option == self.previous_model_option:
                raise ValueError("Chuyển model cần lựa chọn trước và sau khác nhau")
            if any(value is not None for value in (self.saved_samples, self.sample_id, self.capture_session_id, self.reason)):
                raise ValueError("Sự kiện model không nhận dữ liệu phiên thu")
        else:
            if self.saved_samples is None or any(value is not None for value in (self.previous_model_version, self.model_option, self.previous_model_option)):
                raise ValueError("Sự kiện thu mẫu cần số mẫu và không nhận thay đổi model")
            if self.event_type == "collection.sample_saved":
                if self.sample_id is None or self.saved_samples < 1:
                    raise ValueError("Mẫu đã lưu cần sample ID và số mẫu đã xác nhận")
            elif self.sample_id is not None:
                raise ValueError("Sample ID chỉ dùng cho sự kiện lưu mẫu")
        return self


class WorkspaceClientEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["recorded"] = "recorded"
    event_id: UUID
