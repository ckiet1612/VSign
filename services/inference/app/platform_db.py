from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (CheckConstraint("environment IN ('development', 'production')", name="ck_workspace_environment"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list[AuthSession]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_membership_workspace_user"),
        CheckConstraint("role IN ('owner', 'admin', 'operator', 'reviewer', 'viewer', 'model_admin', 'system_admin')", name="ck_membership_role"),
        CheckConstraint("status IN ('active','suspended','removed')", name="ck_membership_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default='active', server_default='active', nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default='0', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor_type IN ('system', 'user', 'service')", name="ck_audit_actor_type"),
        CheckConstraint("outcome IN ('success', 'failure')", name="ck_audit_outcome"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="audit_events")


class Database:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._session_factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
        from app.integration_events import capture_events
        event.listen(self._session_factory, "before_flush", capture_events)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_schema(self) -> None:
        from app.migrate import upgrade_database
        upgrade_database(self)

    def ensure_schema(self, auto_create: bool) -> None:
        from app.migrate import CURRENT_SCHEMA_REVISION, upgrade_database
        from alembic.migration import MigrationContext
        from sqlalchemy import inspect

        with self.engine.connect() as connection:
            existing = set(inspect(connection).get_table_names()) - {"alembic_version"}
            revision = MigrationContext.configure(connection).get_current_revision()
        if not existing and not auto_create:
            raise RuntimeError("Database chưa được migrate; chạy python -m app.migrate")
        if not existing or revision != CURRENT_SCHEMA_REVISION:
            if not auto_create:
                raise RuntimeError("Database chưa được migrate; chạy python -m app.migrate")
            upgrade_database(self)

    def dispose(self) -> None:
        self.engine.dispose()


def _prepare_sqlite_url(database_url: str) -> str:
    if not database_url.startswith("sqlite:///") or database_url == "sqlite:///:memory:":
        return database_url
    path = Path(database_url.removeprefix("sqlite:///"))
    if not path.is_absolute():
        path = Path.cwd() / path
    return f"sqlite:///{path}"


def create_database(database_url: str) -> Database:
    prepared_url = _prepare_sqlite_url(database_url)
    connect_args = {"check_same_thread": False} if prepared_url.startswith("sqlite") else {}
    engine_options: dict[str, Any] = {
        "future": True,
        "pool_pre_ping": True,
        "connect_args": connect_args,
        "hide_parameters": True,
    }
    if prepared_url == "sqlite:///:memory:":
        engine_options["poolclass"] = StaticPool
    engine = create_engine(prepared_url, **engine_options)
    if engine.dialect.name == "sqlite":
        if engine.url.database not in {None, ":memory:"}:
            @event.listens_for(engine, "do_connect")
            def prepare_path(dialect: Any, connection_record: Any, args: Any, kwargs: Any) -> None:
                Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection: Any, connection_record: Any) -> None:
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return Database(engine)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(value: str) -> str:
    return value.strip().casefold()
