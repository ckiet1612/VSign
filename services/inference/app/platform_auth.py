from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
from uuid import NAMESPACE_URL, uuid4, uuid5

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException
from sqlalchemy import select

from app.config import Settings
from app.platform_db import (
    AuditEvent,
    AuthSession,
    Database,
    Membership,
    User,
    Workspace,
    hash_session_token,
    normalize_email,
    utc_now,
)


SESSION_COOKIE_NAME = "vsign_session"


def local_admin_id(workspace_id: str, role: str = "admin") -> str:
    namespace = "vsign-local-system-admin" if role == "system_admin" else "vsign-local-admin"
    return str(uuid5(NAMESPACE_URL, f"{namespace}:{workspace_id}"))


ROLE_PERMISSIONS = {
    "owner": frozenset({
        "workspace:read", "recognize:use", "data:use", "evaluation:read", "monitoring:read",
        "models:read", "activity:read", "integrations:manage", "members:read", "settings:read",
    }),
    "admin": frozenset({
        "workspace:read", "recognize:use", "data:use", "evaluation:read", "monitoring:read",
        "models:read", "activity:read", "integrations:manage", "members:read", "settings:read",
    }),
    "operator": frozenset({"workspace:read", "recognize:use", "data:use", "monitoring:read", "activity:read"}),
    "reviewer": frozenset({"workspace:read", "recognize:use", "evaluation:read", "monitoring:read", "activity:read"}),
    "viewer": frozenset({"workspace:read", "recognize:use", "monitoring:read", "activity:read"}),
}

for _role in ("operator", "reviewer", "viewer"):
    ROLE_PERMISSIONS[_role] |= frozenset({"models:read"})
for _role in ("owner", "admin", "operator", "reviewer", "viewer"):
    ROLE_PERMISSIONS[_role] |= frozenset({"data:read"})
for _role in ("owner", "admin"):
    ROLE_PERMISSIONS[_role] |= frozenset({"data:manage", "evaluation:create", "evaluation:cancel", "members:manage"})
    ROLE_PERMISSIONS[_role] |= frozenset({"settings:manage"})
# Internal membership is provisioned out of band, never by workspace bootstrap.
ROLE_PERMISSIONS["model_admin"] = frozenset({
    "workspace:read", "monitoring:read", "models:read", "activity:read", "recognize:use",
    "models:register", "models:validate", "models:approve", "models:deploy",
})
for _role in ROLE_PERMISSIONS:
    ROLE_PERMISSIONS[_role] |= frozenset({"settings:preferences"})
ROLE_PERMISSIONS["system_admin"] = ROLE_PERMISSIONS["admin"] | ROLE_PERMISSIONS["model_admin"]



@dataclass(frozen=True)
class Principal:
    user: User
    workspace: Workspace
    role: str

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())


def capabilities_for(
    role: Optional[str],
    collection_enabled: bool,
) -> dict[str, bool]:
    permissions = ROLE_PERMISSIONS.get(role or "", frozenset())
    return {
        "overview": role is None or "workspace:read" in permissions,
        "recognize": role is None or "recognize:use" in permissions,
        "data": role is not None and "data:read" in permissions,
        "evaluation": role is not None and "evaluation:read" in permissions,
        "monitoring": role is None or "monitoring:read" in permissions,
        "models": role is None or "models:read" in permissions,
        "activity": role is not None and "activity:read" in permissions,
        "integrations": role is not None and "integrations:manage" in permissions,
        "team": role is not None and "members:read" in permissions,
        "settings": role is not None and "settings:preferences" in permissions,
    }


def bootstrap_platform(database: Database, settings: Settings, hasher: PasswordHasher) -> None:
    with database.session() as session:
        if settings.local_admin_enabled and session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        workspace = session.get(Workspace, settings.workspace_id)
        if workspace is None:
            workspace = Workspace(
                id=settings.workspace_id,
                name=settings.workspace_name,
                environment=settings.app_environment,
            )
            session.add(workspace)
            session.flush()

        if settings.local_admin_enabled:
            identity = local_admin_id(workspace.id, settings.local_admin_role)
            prefix = "local-system-admin" if settings.local_admin_role == "system_admin" else "local-admin"
            email = f"{prefix}+{workspace.id}@vsign.invalid"
            user = session.get(User, identity)
            if user is None:
                if session.scalar(select(User).where(User.email == email)) is not None:
                    raise RuntimeError("Local admin identity conflicts with an existing account")
                user = User(id=identity, email=email, display_name="Admin hệ thống local" if settings.local_admin_role == "system_admin" else "Admin local", password_hash="!")
                session.add(user)
                session.flush()
                session.add(Membership(workspace_id=workspace.id, user_id=identity, role=settings.local_admin_role))
            elif user.email != email or user.password_hash != "!":
                raise RuntimeError("Local admin identity conflicts with an existing account")

        if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
            session.commit()
            return
        if len(settings.bootstrap_admin_password) < 12:
            raise RuntimeError("BOOTSTRAP_ADMIN_PASSWORD phải có ít nhất 12 ký tự")

        email = normalize_email(settings.bootstrap_admin_email)
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                id=str(uuid4()),
                email=email,
                display_name=settings.bootstrap_admin_name,
                password_hash=hasher.hash(settings.bootstrap_admin_password),
            )
            session.add(user)
            session.flush()
        membership = session.scalar(
            select(Membership).where(
                Membership.workspace_id == workspace.id,
                Membership.user_id == user.id,
            )
        )
        if membership is None:
            session.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
        session.commit()


def resolve_local_admin(database: Database, workspace_id: str, role: str = "admin") -> Optional[Principal]:
    with database.session() as session:
        row = session.execute(select(User, Membership, Workspace)
            .join(Membership, Membership.user_id == User.id)
            .join(Workspace, Workspace.id == Membership.workspace_id)
            .where(User.id == local_admin_id(workspace_id, role), User.is_active.is_(True),
                   User.password_hash == "!", Membership.workspace_id == workspace_id,
                   Membership.role == role, Membership.status == 'active')).first()
        if row is None:
            return None
        user, membership, workspace = row
        return Principal(user=user, workspace=workspace, role=membership.role)


def create_session(database: Database, user: User, workspace_id: str, ttl_seconds: int, previous_token: Optional[str] = None) -> str:
    raw_token = secrets.token_urlsafe(32)
    with database.session() as session:
        # Serialize login with workspace suspension so no fresh session escapes revocation.
        if database.engine.dialect.name == 'sqlite':
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        else:
            session.execute(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        current = session.get(User, user.id)
        membership = session.scalar(select(Membership).where(Membership.workspace_id == workspace_id,
            Membership.user_id == user.id, Membership.status == 'active'))
        if not current or not current.is_active or current.password_hash != user.password_hash or not membership:
            raise HTTPException(401, 'Email hoặc mật khẩu không đúng')
        if previous_token:
            previous = session.scalar(select(AuthSession).where(
                AuthSession.token_hash == hash_session_token(previous_token),
                AuthSession.workspace_id == workspace_id,
            ))
            if previous is not None:
                previous.revoked_at = utc_now()
        session.add(
            AuthSession(
                id=str(uuid4()),
                user_id=user.id,
                workspace_id=workspace_id,
                token_hash=hash_session_token(raw_token),
                expires_at=utc_now() + timedelta(seconds=ttl_seconds),
            )
        )
        session.add(AuditEvent(id=str(uuid4()), workspace_id=workspace_id, event_type="auth.login",
                               actor_type="user", actor_id=user.id, outcome="success", metadata_json={}))
        session.commit()
    return raw_token


def resolve_principal(database: Database, raw_token: Optional[str], workspace_id: str) -> Optional[Principal]:
    if not raw_token or len(raw_token) > 128:
        return None
    with database.session() as session:
        row = session.execute(
            select(User, Membership, Workspace)
            .join(Membership, Membership.user_id == User.id)
            .join(Workspace, Workspace.id == Membership.workspace_id)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_hash == hash_session_token(raw_token),
                AuthSession.workspace_id == workspace_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utc_now(),
                Membership.workspace_id == workspace_id,
                Membership.status == 'active',
                User.is_active.is_(True),
            )
        ).first()
        if row is None:
            return None
        user, membership, workspace = row
        return Principal(user=user, workspace=workspace, role=membership.role)


def revoke_session(database: Database, raw_token: Optional[str], workspace_id: Optional[str] = None) -> Optional[User]:
    if not raw_token:
        return None
    with database.session() as session:
        statement = select(AuthSession).where(AuthSession.token_hash == hash_session_token(raw_token))
        if workspace_id is not None:
            statement = statement.where(AuthSession.workspace_id == workspace_id)
        auth_session = session.scalar(statement)
        if auth_session is None or auth_session.revoked_at is not None:
            return None
        auth_session.revoked_at = utc_now()
        user = session.get(User, auth_session.user_id)
        if auth_session.workspace_id:
            session.add(AuditEvent(id=str(uuid4()), workspace_id=auth_session.workspace_id, event_type="auth.logout",
                                   actor_type="user", actor_id=auth_session.user_id, outcome="success", metadata_json={}))
        session.commit()
        return user


def verify_password(hasher: PasswordHasher, encoded: str, password: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def record_audit(
    database: Database,
    workspace_id: str,
    event_type: str,
    actor_type: str,
    actor_id: Optional[str],
    outcome: str,
    metadata: Optional[dict] = None,
) -> None:
    with database.session() as session:
        session.add(
            AuditEvent(
                id=str(uuid4()),
                workspace_id=workspace_id,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                occurred_at=utc_now(),
                outcome=outcome,
                metadata_json=metadata or {},
            )
        )
        session.commit()
