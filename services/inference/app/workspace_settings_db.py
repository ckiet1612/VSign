from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform_db import Base, utc_now


class WorkspacePreferences(Base):
    __tablename__ = 'workspace_preferences'
    __table_args__ = (CheckConstraint('revision >= 0 AND collection_revision >= 0', name='ck_workspace_preferences_revision'),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    collection_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_by: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)


class UserNotificationPreferences(Base):
    __tablename__ = 'user_notification_preferences'
    __table_args__ = (CheckConstraint('revision >= 0', name='ck_notification_preferences_revision'),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    preferences: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SettingsMutation(Base):
    __tablename__ = 'settings_mutations'

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), nullable=False, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
