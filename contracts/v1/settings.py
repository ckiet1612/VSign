from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class WorkspaceOptions(SettingsModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator('name')
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = unicodedata.normalize('NFC', value).strip()
        if not value or any(unicodedata.category(char).startswith('C') for char in value):
            raise ValueError('Tên workspace không hợp lệ')
        return value

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError('Múi giờ không hợp lệ') from None
        return value


class RetentionPolicy(SettingsModel):
    draft_samples_days: Optional[int] = Field(default=None, strict=True, ge=1, le=3650)
    audit_events_days: Optional[int] = Field(default=None, strict=True, ge=1, le=3650)
    automatic_deletion: Literal[False] = False


class CollectionPolicy(SettingsModel):
    enabled: bool = Field(default=True, strict=True)
    require_consent: bool = Field(default=False, strict=True)
    default_quota_per_label: int = Field(default=100, strict=True, ge=1, le=10000)


class EffectiveCollectionPolicy(CollectionPolicy):
    revision: int
    process_enabled: bool


class RuntimeDefaults(SettingsModel):
    capture_mode: Literal['manual', 'automatic'] = 'manual'


class NotificationPreferences(SettingsModel):
    collection_completed: bool = Field(strict=True)
    evaluation_finished: bool = Field(strict=True)
    integration_failed: bool = Field(strict=True)


class StoredConfiguration(SettingsModel):
    timezone: str = 'UTC'
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)
    collection_policy: CollectionPolicy = Field(default_factory=CollectionPolicy)
    runtime_defaults: RuntimeDefaults = Field(default_factory=RuntimeDefaults)


class SettingsRequest(SettingsModel):
    request_id: UUID
    expected_revision: int = Field(strict=True, ge=0, le=2147483646)


class UpdateWorkspaceSettings(SettingsRequest):
    workspace: Optional[WorkspaceOptions] = None
    retention: Optional[RetentionPolicy] = None
    collection_policy: Optional[CollectionPolicy] = None
    runtime_defaults: Optional[RuntimeDefaults] = None

    @model_validator(mode='after')
    def nonempty_sections(self):
        sections = {'workspace', 'retention', 'collection_policy', 'runtime_defaults'}
        if not self.model_fields_set.intersection(sections) or any(
                getattr(self, key) is None for key in self.model_fields_set.intersection(sections)):
            raise ValueError('Cần ít nhất một nhóm cài đặt hợp lệ')
        for key in self.model_fields_set.intersection(sections):
            section = getattr(self, key)
            if section.model_fields_set != set(type(section).model_fields):
                raise ValueError('Cần gửi đầy đủ trường trong nhóm cài đặt')
        return self


class UpdateNotifications(SettingsRequest):
    preferences: NotificationPreferences


class NotificationSettings(SettingsModel):
    revision: int
    updated_at: Optional[datetime]
    preferences: NotificationPreferences
    delivery: Literal['not_configured'] = 'not_configured'


class SettingsPermissions(SettingsModel):
    manage: bool


class WorkspaceSettingsResponse(SettingsModel):
    api_version: Literal['1'] = '1'
    workspace_id: str
    user_id: str
    revision: int
    updated_at: Optional[datetime]
    permissions: SettingsPermissions
    workspace: Optional[WorkspaceOptions]
    retention: Optional[RetentionPolicy]
    collection_policy: Optional[CollectionPolicy]
    runtime_defaults: RuntimeDefaults
    process_collection_enabled: bool
    notifications: NotificationSettings
    request_id: Optional[UUID] = None
    applied_revision: Optional[int] = None
