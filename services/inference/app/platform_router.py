from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal, Optional
from uuid import UUID

from argon2 import PasswordHasher
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.activity import public_audit_metadata, store_client_event
from contracts.v1.workspace import WORKSPACE_ROLES, INTERNAL_ROLES, WorkspaceClientEventRequest, WorkspaceClientEventResponse
from app.models import (
    AuthLoginRequest,
    AuthLogoutResponse,
    AuthSessionResponse,
    AuthenticatedUser,
    WorkspaceAuditEvent,
    WorkspaceAuditPageResponse,
    WorkspaceCapabilities,
    WorkspaceCapabilitiesResponse,
    WorkspaceContextResponse,
    WorkspaceMemberResponse,
    WorkspaceMembersResponse,
)
from app.platform_auth import (
    SESSION_COOKIE_NAME,
    Principal,
    capabilities_for,
    create_session,
    login_email,
    record_audit,
    resolve_local_admin,
    resolve_principal,
    revoke_session,
    verify_password,
)
from app.inference_token import issue_inference_token
from app.platform_db import AuditEvent, Database, Membership, User, Workspace, hash_session_token, utc_now


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    return PasswordHasher().hash("vsign-invalid-login-dummy")


def create_platform_router(
    settings: Settings,
    password_hasher: PasswordHasher,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["platform"])

    def get_database(request: Request) -> Database:
        database = request.app.state.platform_database
        if database is None:
            raise HTTPException(status_code=503, detail="Workspace chưa sẵn sàng. Kiểm tra database và migration.")
        return database

    def validate_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin không được phép")
        if not origin and request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            raise HTTPException(status_code=403, detail="Origin không được phép")

    def principal(request: Request, required: bool = False) -> Optional[Principal]:
        if settings.local_admin_enabled:
            current = resolve_local_admin(get_database(request), settings.workspace_id, settings.local_admin_role)
            if current is None:
                raise HTTPException(status_code=503, detail="Quyền admin local chưa sẵn sàng")
            return current
        current = resolve_principal(
            get_database(request),
            request.cookies.get(SESSION_COOKIE_NAME),
            settings.workspace_id,
        )
        if current is None and (required or settings.auth_required):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Đăng nhập để tiếp tục")
        return current

    def require_permission(request: Request, permission: str) -> Optional[Principal]:
        current = principal(request, required=True)
        assert current is not None
        if not current.can(permission):
            record_audit(get_database(request), settings.workspace_id, "permission.denied", "user", current.user.id, "failure",
                         {"permission": permission, "method": request.method, "path": request.url.path})
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bạn không có quyền thực hiện thao tác này")
        return current

    def user_response(current: Principal) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=current.user.id,
            email=current.user.email,
            display_name=current.user.display_name,
            role=current.role,
        )

    def encode_cursor(event: AuditEvent) -> str:
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        payload = {"at": occurred_at.isoformat(), "id": event.id}
        return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()

    def decode_cursor(value: str) -> tuple[datetime, str]:
        try:
            payload = json.loads(base64.urlsafe_b64decode(value.encode()).decode())
            occurred_at = datetime.fromisoformat(payload["at"])
            event_id = payload["id"]
            if not isinstance(event_id, str) or not event_id:
                raise ValueError
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)
            return occurred_at, event_id
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail="Cursor không hợp lệ") from exc

    from app.workspace_data_router import create_workspace_data_router
    router.include_router(create_workspace_data_router(settings, get_database, require_permission, validate_origin))

    from app.dashboard import dashboard_snapshot
    from contracts.v1.dashboard import DashboardResponse

    @router.get("/workspace/dashboard", response_model=DashboardResponse)
    def dashboard(request: Request, response: Response, days: int = Query(default=30)):
        current = require_permission(request, "workspace:read")
        if current.role != "system_admin":
            raise HTTPException(status_code=403, detail="Chỉ quản trị hệ thống được xem dashboard")
        if days not in (7, 30, 90):
            raise HTTPException(status_code=422, detail="Khoảng thống kê phải là 7, 30 hoặc 90 ngày")
        response.headers["Cache-Control"] = "no-store"
        return dashboard_snapshot(get_database(request), current.workspace.id, days)

    @router.post("/auth/login", response_model=AuthSessionResponse)
    def login(request: Request, payload: AuthLoginRequest, response: Response) -> AuthSessionResponse:
        validate_origin(request)
        database = get_database(request)
        email = login_email(payload.email)
        address_key = hash_session_token(request.client.host if request.client else "unknown")
        account_key = hash_session_token(email)
        with database.session() as session:
            failures = session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.workspace_id == settings.workspace_id,
                AuditEvent.event_type == "auth.login_failed",
                AuditEvent.occurred_at > utc_now() - timedelta(seconds=60),
                or_(AuditEvent.metadata_json["address_key"].as_string() == address_key,
                    AuditEvent.metadata_json["account_key"].as_string() == account_key),
            ))
            if failures and failures >= 10:
                raise HTTPException(status_code=429, detail="Thử đăng nhập quá nhiều lần. Vui lòng chờ một phút.", headers={"Retry-After": "60"})
            user = session.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
            membership = None
            if user is not None:
                membership = session.scalar(
                    select(Membership).where(
                        Membership.workspace_id == settings.workspace_id,
                        Membership.user_id == user.id,
                        Membership.status == 'active',
                    )
                )
        password_hash = user.password_hash if user is not None else dummy_password_hash()
        password_valid = verify_password(password_hasher, password_hash, payload.password)
        if user is None or membership is None or not password_valid:
            record_audit(database, settings.workspace_id, "auth.login_failed", "system", None, "failure", {"address_key": address_key, "account_key": account_key})
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tên đăng nhập hoặc mật khẩu không đúng")

        token = create_session(database, user, settings.workspace_id, settings.auth_session_ttl_seconds, request.cookies.get(SESSION_COOKIE_NAME))
        response.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            max_age=settings.auth_session_ttl_seconds,
            httponly=True,
            secure=settings.auth_cookie_secure,
            samesite="lax",
            path="/",
        )
        current = Principal(user=user, workspace=Workspace(id=settings.workspace_id, name=settings.workspace_name, environment=settings.app_environment), role=membership.role)
        return AuthSessionResponse(user=user_response(current))

    @router.post("/auth/logout", response_model=AuthLogoutResponse)
    def logout(request: Request, response: Response) -> AuthLogoutResponse:
        validate_origin(request)
        database = get_database(request)
        token = request.cookies.get(SESSION_COOKIE_NAME)
        revoke_session(database, token, settings.workspace_id)
        response.delete_cookie(
            SESSION_COOKIE_NAME,
            path="/",
            secure=settings.auth_cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return AuthLogoutResponse()

    @router.get("/auth/me", response_model=AuthSessionResponse)
    def me(request: Request) -> AuthSessionResponse:
        current = principal(request, required=True)
        assert current is not None
        return AuthSessionResponse(user=user_response(current), auth_mode="local_admin" if settings.local_admin_enabled else "session")

    @router.post("/inference/token")
    def inference_token(request: Request, response: Response) -> dict:
        """A short-lived token for recognition runtimes that cannot read this database (Modal GPU)."""
        if not settings.inference_token_secret:
            raise HTTPException(status_code=404, detail="Runtime GPU chưa được cấu hình")
        validate_origin(request)
        current = require_permission(request, "recognize:use")
        assert current is not None
        token, expires_at = issue_inference_token(settings.inference_token_secret, settings.workspace_id, current.user.id)
        response.headers["Cache-Control"] = "no-store"
        return {"token": token, "expires_at": expires_at}

    @router.get("/workspace", response_model=WorkspaceContextResponse)
    def workspace_context(request: Request) -> WorkspaceContextResponse:
        principal(request)
        with get_database(request).session() as session:
            workspace = session.get(Workspace, settings.workspace_id)
        if workspace is None:
            raise HTTPException(status_code=503, detail="Workspace chưa sẵn sàng")
        return WorkspaceContextResponse(
            workspace_id=settings.workspace_id,
            name=workspace.name,
            environment=workspace.environment,
            auth_required=settings.auth_required,
        )

    @router.get("/workspace/capabilities", response_model=WorkspaceCapabilitiesResponse)
    def workspace_capabilities(request: Request) -> WorkspaceCapabilitiesResponse:
        current = principal(request)
        return WorkspaceCapabilitiesResponse(
            workspace_id=settings.workspace_id,
            capabilities=WorkspaceCapabilities(
                **capabilities_for(current.role if current else None, settings.collection_enabled)
            ),
        )

    @router.get("/workspace/members", response_model=WorkspaceMembersResponse)
    def workspace_members(request: Request) -> WorkspaceMembersResponse:
        current = require_permission(request, "members:read")
        database = get_database(request)
        with database.session() as session:
            rows = session.execute(
                select(User, Membership)
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.workspace_id == settings.workspace_id,
                       Membership.role.in_((*WORKSPACE_ROLES, *INTERNAL_ROLES) if current.role == "system_admin" else WORKSPACE_ROLES),
                       Membership.status != 'removed')
                .order_by(User.email)
            ).all()
        return WorkspaceMembersResponse(
            workspace_id=settings.workspace_id,
            members=[
                WorkspaceMemberResponse(
                    id=user.id,
                    email=user.email,
                    display_name=user.display_name,
                    role=membership.role,
                    active=user.is_active and membership.status == 'active',
                )
                for user, membership in rows
            ],
        )

    @router.get("/workspace/audit/events", response_model=WorkspaceAuditPageResponse)
    def workspace_audit_events(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        cursor: Optional[str] = Query(default=None, max_length=256),
        group: Optional[Literal["auth", "permission", "model", "collection", "data", "deployment", "evaluation", "integration"]] = None,
        outcome: Optional[Literal["success", "failure"]] = None,
        from_at: Optional[datetime] = None,
        to_at: Optional[datetime] = None,
    ) -> WorkspaceAuditPageResponse:
        require_permission(request, "activity:read")
        database = get_database(request)
        cursor_position = decode_cursor(cursor) if cursor else None
        filters = [AuditEvent.workspace_id == settings.workspace_id]
        current = principal(request, required=True)
        if current.role not in {'owner', 'admin', 'system_admin'}:
            from contracts.v1.team import TEAM_PRIVATE_EVENTS
            filters.append(AuditEvent.event_type.not_in(TEAM_PRIVATE_EVENTS))
            filters.append(or_(~AuditEvent.event_type.startswith('settings.'), and_(
                AuditEvent.event_type == 'settings.notifications_updated', AuditEvent.actor_id == current.user.id)))
            filters.append(~and_(AuditEvent.event_type == 'permission.denied', or_(
                func.coalesce(AuditEvent.metadata_json['permission'].as_string(), '').startswith('members:'),
                func.coalesce(AuditEvent.metadata_json['path'].as_string(), '').startswith('/api/v1/workspace/team'))))
        if from_at is not None:
            from_at = from_at.replace(tzinfo=timezone.utc) if from_at.tzinfo is None else from_at.astimezone(timezone.utc)
        if to_at is not None:
            to_at = to_at.replace(tzinfo=timezone.utc) if to_at.tzinfo is None else to_at.astimezone(timezone.utc)
        if from_at is not None and to_at is not None and from_at > to_at:
            raise HTTPException(status_code=422, detail="Thời gian bắt đầu phải trước thời gian kết thúc")
        if group:
            filters.append(AuditEvent.event_type.startswith(group + "."))
        if outcome:
            filters.append(AuditEvent.outcome == outcome)
        if from_at is not None:
            filters.append(AuditEvent.occurred_at >= from_at)
        if to_at is not None:
            filters.append(AuditEvent.occurred_at <= to_at)
        if cursor_position is not None:
            occurred_at, event_id = cursor_position
            filters.append(
                or_(
                    AuditEvent.occurred_at < occurred_at,
                    and_(AuditEvent.occurred_at == occurred_at, AuditEvent.id < event_id),
                )
            )
        with database.session() as session:
            rows = session.scalars(
                select(AuditEvent)
                .where(*filters)
                .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
                .limit(limit + 1)
            ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return WorkspaceAuditPageResponse(
            workspace_id=settings.workspace_id,
            events=[
                WorkspaceAuditEvent(
                    event_id=UUID(event.id),
                    workspace_id=event.workspace_id,
                    event_type=event.event_type,
                    actor_type=event.actor_type,
                    actor_id=event.actor_id,
                    occurred_at=event.occurred_at.replace(tzinfo=timezone.utc) if event.occurred_at.tzinfo is None else event.occurred_at,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    outcome=event.outcome,
                    metadata=public_audit_metadata(event.metadata_json),
                )
                for event in rows
            ],
            next_cursor=encode_cursor(rows[-1]) if has_more else None,
            has_more=has_more,
            source="store",
        )

    @router.post("/workspace/audit/client-events", response_model=WorkspaceClientEventResponse, status_code=201)
    def client_event(request: Request, payload: WorkspaceClientEventRequest, response: Response) -> WorkspaceClientEventResponse:
        validate_origin(request)
        try:
            current = require_permission(request, "recognize:use" if payload.event_type == "model.switched" else "data:use")
            assert current is not None
            if payload.event_type.startswith("collection.") and not settings.collection_enabled:
                raise HTTPException(status_code=403, detail="Thu dữ liệu chưa được bật")
            created = store_client_event(get_database(request), settings.workspace_id, current, payload)
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail="Không thể ghi nhật ký. Vui lòng thử lại với cùng event ID.") from exc
        response.status_code = 201 if created else 200
        return WorkspaceClientEventResponse(event_id=payload.event_id)

    from app.model_registry_router import create_model_registry_router
    router.include_router(create_model_registry_router(settings, get_database, require_permission, validate_origin))
    from app.evaluation_router import create_evaluation_router
    router.include_router(create_evaluation_router(settings, get_database, require_permission, validate_origin))
    from app.integration_router import create_integration_router
    router.include_router(create_integration_router(settings, get_database, require_permission, validate_origin))
    from app.team_router import create_team_router
    router.include_router(create_team_router(settings, get_database, require_permission, validate_origin, password_hasher))
    from app.workspace_settings_router import create_workspace_settings_router
    router.include_router(create_workspace_settings_router(settings, get_database, require_permission, validate_origin))
    from app.display_router import create_display_router
    router.include_router(create_display_router(settings, get_database, require_permission, validate_origin))
    return router
