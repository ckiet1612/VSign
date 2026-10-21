from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.platform_db import Base, utc_now


class DisplayDevice(Base):
    """A counter laptop enrolled once; its token stays valid until revoked, never by age."""
    __tablename__ = 'display_devices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[Optional[str]] = mapped_column(ForeignKey('users.id'))


class DisplayEnrollment(Base):
    """A one-time pairing code. The device token is minted at claim and only becomes a device on confirmation."""
    __tablename__ = 'display_enrollments'
    __table_args__ = (CheckConstraint(
        "status IN ('pending','awaiting_confirmation','confirmed','rejected','expired')", name='ck_display_enrollment_status'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey('workspaces.id'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    link_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='pending')
    verification: Mapped[Optional[str]] = mapped_column(String(4))
    device_token_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[Optional[str]] = mapped_column(ForeignKey('users.id'))
    display_id: Mapped[Optional[str]] = mapped_column(ForeignKey('display_devices.id'))
