from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform_db import Base, utc_now


class EvaluationRun(Base):
    __tablename__ = 'evaluation_runs'
    __table_args__ = (CheckConstraint("status IN ('queued','running','completed','failed','cancelled')",
                                     name='ck_evaluation_status'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey('registered_models.id'))
    baseline_model_id: Mapped[str] = mapped_column(ForeignKey('registered_models.id'))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('data_snapshots.id'))
    requested_by: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(12), default='queued')
    frozen_json: Mapped[dict] = mapped_column(JSON)
    report_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    gate_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    report_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    worker_id: Mapped[Optional[str]] = mapped_column(String(36))
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class EvaluationWorkerState(Base):
    __tablename__ = 'evaluation_workers'
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    backend: Mapped[str] = mapped_column(String(20), primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(36))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
