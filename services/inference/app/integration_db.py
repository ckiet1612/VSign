from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.platform_db import Base, utc_now


class ScopedIntegration:
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IntegrationKey(ScopedIntegration, Base):
    __tablename__ = 'integration_keys'
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(24))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSON)
    requests_per_minute: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class IntegrationWebhook(ScopedIntegration, Base):
    __tablename__ = 'integration_webhooks'
    __table_args__ = (UniqueConstraint('workspace_id','id'),)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048))
    events: Mapped[list] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    secret_ciphertext: Mapped[str] = mapped_column(String(512))
    secret_version: Mapped[int] = mapped_column(Integer, default=1)


class IntegrationDelivery(ScopedIntegration, Base):
    __tablename__ = 'integration_deliveries'
    __table_args__ = (
        UniqueConstraint('webhook_id','event_id'),
        ForeignKeyConstraint(['workspace_id','webhook_id'],['integration_webhooks.workspace_id','integration_webhooks.id']),
        CheckConstraint("status IN ('pending','sending','delivered','failed','cancelled')", name='ck_integration_delivery_status'))
    webhook_id: Mapped[str] = mapped_column(String(36))
    event_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(12), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    claim_token: Mapped[Optional[str]] = mapped_column(String(36))
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(String(64))


class IntegrationLog(ScopedIntegration, Base):
    __tablename__ = 'integration_logs'
    kind: Mapped[str] = mapped_column(String(12))
    resource_id: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(120))
    status_code: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(String(64))


class IntegrationRateBucket(Base):
    __tablename__ = 'integration_rate_buckets'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    bucket: Mapped[str] = mapped_column(String(120), primary_key=True)
    window: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer)


class IntegrationMutation(ScopedIntegration, Base):
    __tablename__ = 'integration_mutations'
    request_hash: Mapped[str] = mapped_column(String(64))


class IntegrationWorkerState(Base):
    __tablename__ = 'integration_workers'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
