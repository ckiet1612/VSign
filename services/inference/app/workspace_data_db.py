from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.platform_db import Base, utc_now


class ScopedData:
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class LabelVersion(ScopedData, Base):
    __tablename__ = "data_label_versions"
    __table_args__ = (UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(["workspace_id", "parent_id"], ["data_label_versions.workspace_id", "data_label_versions.id"]))

    name: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[Optional[str]] = mapped_column(String(36))
    entries_json: Mapped[list] = mapped_column(JSON)
    request_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36))


class DatasetVersion(ScopedData, Base):
    __tablename__ = "data_versions"
    __table_args__ = (UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(["workspace_id", "label_version_id"], ["data_label_versions.workspace_id", "data_label_versions.id"]),
        CheckConstraint("status IN ('draft','sealed')", name="ck_data_status"),
        CheckConstraint("quota_per_label >= 1 AND quota_per_label <= 10000", name="ck_data_quota"))

    name: Mapped[str] = mapped_column(String(120))
    label_version_id: Mapped[str] = mapped_column(String(36))
    quota_per_label: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="draft")
    request_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36))


class DataSession(ScopedData, Base):
    __tablename__ = "data_sessions"
    __table_args__ = (UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(["workspace_id", "dataset_version_id"], ["data_versions.workspace_id", "data_versions.id"]),
        CheckConstraint("state IN ('running','paused','stopped','completed')", name="ck_data_session_state"))

    dataset_version_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(12), default="running")
    created_by: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    consented_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    policy_revision: Mapped[Optional[int]] = mapped_column(Integer)


class DataSample(ScopedData, Base):
    __tablename__ = "data_samples"
    __table_args__ = (
        ForeignKeyConstraint(["workspace_id", "dataset_version_id"], ["data_versions.workspace_id", "data_versions.id"]),
        ForeignKeyConstraint(["workspace_id", "collection_session_id"], ["data_sessions.workspace_id", "data_sessions.id"]),
        CheckConstraint("hand IN ('right','left')", name="ck_data_sample_hand"))

    dataset_version_id: Mapped[str] = mapped_column(String(36))
    collection_session_id: Mapped[str] = mapped_column(String(36), index=True)
    label_id: Mapped[str] = mapped_column(String(36))
    expected_label: Mapped[str] = mapped_column(String(80))
    hand: Mapped[str] = mapped_column(String(8))
    relative_path: Mapped[str] = mapped_column(String(256))
    video_sha256: Mapped[str] = mapped_column(String(64))
    metadata_sha256: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))


class DatasetSnapshot(ScopedData, Base):
    __tablename__ = "data_snapshots"
    __table_args__ = (UniqueConstraint("workspace_id", "dataset_version_id"),
        ForeignKeyConstraint(["workspace_id", "dataset_version_id"], ["data_versions.workspace_id", "data_versions.id"]),
        ForeignKeyConstraint(["workspace_id", "label_version_id"], ["data_label_versions.workspace_id", "data_label_versions.id"]))

    dataset_version_id: Mapped[str] = mapped_column(String(36))
    label_version_id: Mapped[str] = mapped_column(String(36))
    sample_count: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36))
