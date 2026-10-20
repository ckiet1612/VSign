from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.platform_db import Base, utc_now


class RegisteredModel(Base):
    __tablename__ = "registered_models"
    __table_args__ = (UniqueConstraint("workspace_id", "model_version", name="uq_registry_version"),
                      CheckConstraint("origin IN ('baseline','candidate')", name="ck_model_origin"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    model_version: Mapped[str] = mapped_column(String(160), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    labels_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    labels_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_validation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelValidation(Base):
    __tablename__ = "model_validations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    model_id: Mapped[str] = mapped_column(ForeignKey("registered_models.id"), nullable=False)
    baseline_model_id: Mapped[str] = mapped_column(ForeignKey("registered_models.id"), nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evaluation_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DeploymentTarget(Base):
    __tablename__ = "deployment_targets"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    runtime_url: Mapped[str] = mapped_column(String(256), nullable=False)
    backend: Mapped[str] = mapped_column(String(20), nullable=False)
    active_model_id: Mapped[str] = mapped_column(ForeignKey("registered_models.id"), nullable=False)
    previous_model_id: Mapped[Optional[str]] = mapped_column(ForeignKey("registered_models.id"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pending_job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_model_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class DeploymentJob(Base):
    __tablename__ = "deployment_jobs"
    __table_args__ = (CheckConstraint("operation IN ('deploy','rollback')", name="ck_deployment_operation"),
                      CheckConstraint("status IN ('queued','loading','succeeded','failed')", name="ck_deployment_status"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(12), nullable=False)
    from_model_id: Mapped[str] = mapped_column(ForeignKey("registered_models.id"), nullable=False)
    to_model_id: Mapped[str] = mapped_column(ForeignKey("registered_models.id"), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    worker_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
