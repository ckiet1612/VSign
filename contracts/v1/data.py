from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.v1.inference import CollectionSampleRequest
from contracts.v1.settings import EffectiveCollectionPolicy


class DataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("name", check_fields=False)
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value).strip()
        if not value or any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("Tên không hợp lệ")
        return value

    @field_validator("created_at", "updated_at", check_fields=False)
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class LabelEntry(DataRequest):
    id: UUID
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["sign", "negative"] = "sign"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value).strip()
        if not value or any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("Tên ký hiệu không hợp lệ")
        return value


class CreateLabelsRequest(DataRequest):
    request_id: UUID
    name: str = Field(min_length=1, max_length=120)
    parent_id: Optional[UUID] = None
    entries: list[LabelEntry] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def unique_entries(self):
        if len({entry.id for entry in self.entries}) != len(self.entries) or len({
            entry.name.casefold() for entry in self.entries}) != len(self.entries):
            raise ValueError("Danh mục có ký hiệu trùng")
        return self


class QuotaRequest(DataRequest):
    quota_per_label: int = Field(default=100, strict=True, ge=1, le=10000)


class CreateDatasetRequest(QuotaRequest):
    request_id: UUID
    name: str = Field(min_length=1, max_length=120)
    label_version_id: UUID


class StartSessionRequest(DataRequest):
    request_id: UUID
    dataset_version_id: UUID
    consent: bool = Field(default=False, strict=True)


class SessionStateRequest(DataRequest):
    state: Literal["running", "paused", "stopped", "completed"]


class SnapshotRequest(DataRequest):
    request_id: UUID


class WorkspaceSampleRequest(CollectionSampleRequest):
    sample_key: UUID


class LabelVersionResponse(DataRequest):
    id: str
    name: str
    parent_id: Optional[str]
    entries: list[LabelEntry]
    created_at: datetime


class DatasetResponse(DataRequest):
    id: str
    name: str
    label_version_id: str
    quota_per_label: int
    status: Literal["draft", "sealed"]
    sample_count: int
    counts: dict[str, dict[str, int]]
    created_at: datetime


class DataSessionResponse(DataRequest):
    id: str
    dataset_version_id: str
    created_by: str
    state: Literal["running", "paused", "stopped", "completed"]
    sample_count: int
    created_at: datetime
    updated_at: datetime


class SnapshotResponse(DataRequest):
    id: str
    dataset_version_id: str
    label_version_id: str
    sample_count: int
    sha256: str
    created_at: datetime


class DataPermissions(DataRequest):
    manage: bool
    collect: bool


class WorkspaceDataResponse(DataRequest):
    api_version: Literal["1"] = "1"
    workspace_id: str
    collection_enabled: bool
    collection_policy: EffectiveCollectionPolicy
    default_labels: list[str]
    permissions: DataPermissions
    labels: list[LabelVersionResponse]
    datasets: list[DatasetResponse]
    sessions: list[DataSessionResponse]
    snapshots: list[SnapshotResponse]
