from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform_db import Base, utc_now


class UsageConversation(Base):
    """One conversation at the counter, summarised by the staff recognizer when it ends. Counts and labels only."""
    __tablename__ = 'usage_conversations'
    __table_args__ = (Index('ix_usage_conversations_workspace_started', 'workspace_id', 'started_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    display_id: Mapped[Optional[str]] = mapped_column(ForeignKey('display_devices.id'))
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    words: Mapped[int] = mapped_column(Integer, nullable=False)
    uncertain: Mapped[int] = mapped_column(Integer, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, nullable=False)
    staff_undos: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_undos: Mapped[int] = mapped_column(Integer, nullable=False)
    replies: Mapped[int] = mapped_column(Integer, nullable=False)
    voice_replies: Mapped[int] = mapped_column(Integer, nullable=False)
    labels_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    undone_labels_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
