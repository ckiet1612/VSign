from datetime import datetime, timezone, timedelta
from typing import Literal, Optional
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from contracts.v1.data import DataRequest

SCOPE_NAMES = ('models:read', 'snapshots:read', 'evaluations:read')
EVENT_NAMES = ('collection.started', 'collection.paused', 'collection.resumed',
               'collection.stopped', 'collection.completed', 'data.snapshot_created',
               'evaluation.requested', 'evaluation.started', 'evaluation.completed',
               'evaluation.failed', 'evaluation.cancelled', 'deployment.succeeded', 'deployment.failed')
Scope = Literal['models:read', 'snapshots:read', 'evaluations:read']
EventName = Literal['collection.started', 'collection.paused', 'collection.resumed',
                    'collection.stopped', 'collection.completed', 'data.snapshot_created',
                    'evaluation.requested', 'evaluation.started', 'evaluation.completed',
                    'evaluation.failed', 'evaluation.cancelled', 'deployment.succeeded', 'deployment.failed']


class IntegrationRequest(DataRequest):
    request_id: UUID


class CreateKeyRequest(IntegrationRequest):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[Scope] = Field(min_length=1, max_length=3)
    expires_at: datetime
    requests_per_minute: int = Field(default=60, strict=True, ge=1, le=60)

    @field_validator('expires_at')
    @classmethod
    def expiry(cls, value):
        if value.tzinfo is None:
            raise ValueError('Ngày hết hạn cần múi giờ')
        if not datetime.now(timezone.utc) < value <= datetime.now(timezone.utc) + timedelta(days=365):
            raise ValueError('Ngày hết hạn phải trong 365 ngày tới')
        return value

    @field_validator('scopes')
    @classmethod
    def unique_scopes(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Quyền bị trùng')
        return sorted(value)


class ConfigureWebhookRequest(IntegrationRequest):
    enabled: Optional[bool] = Field(default=None, strict=True)
    events: Optional[list[EventName]] = Field(default=None, min_length=1, max_length=len(EVENT_NAMES))

    @field_validator('events')
    @classmethod
    def unique_events(cls, value):
        if value is None:
            return None
        if len(set(value)) != len(value):
            raise ValueError('Sự kiện bị trùng')
        return sorted(value)

    @model_validator(mode='after')
    def has_change(self):
        if self.enabled is None and self.events is None:
            raise ValueError('Cần trạng thái hoặc sự kiện cần đổi')
        return self


class CreateWebhookRequest(IntegrationRequest):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    events: list[EventName] = Field(min_length=1, max_length=len(EVENT_NAMES))

    @field_validator('events')
    @classmethod
    def unique_events(cls, value):
        return ConfigureWebhookRequest.unique_events(value)
