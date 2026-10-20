from __future__ import annotations

from typing import Any
import re

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.platform_auth import Principal
from app.platform_db import AuditEvent, Database, utc_now
from contracts.v1.workspace import WorkspaceClientEventRequest


def public_audit_metadata(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[redacted]"
    if isinstance(value, dict):
        return {key: public_audit_metadata(item, depth + 1) for key, item in value.items()
                if not any(part in re.sub(r"[^a-z0-9]", "", key.casefold()) for part in
                           ("password", "passwd", "secret", "token", "cookie", "authorization", "apikey", "credential", "accountkey", "addresskey"))}
    if isinstance(value, list):
        return [public_audit_metadata(item, depth + 1) for item in value]
    return value


def store_client_event(database: Database, workspace_id: str, actor: Principal, payload: WorkspaceClientEventRequest) -> bool:
    event_id = str(payload.event_id)
    resource_type = "recognition_session" if payload.event_type == "model.switched" else "collection_session"
    metadata = payload.model_dump(mode="json", exclude={"event_id", "event_type", "resource_id"}, exclude_none=True)
    metadata["source"] = "browser_report"

    def check_existing(event: AuditEvent) -> bool:
        if (event.workspace_id != workspace_id or event.actor_type != "user" or event.actor_id != actor.user.id or
                event.event_type != payload.event_type or event.resource_id != str(payload.resource_id) or
                event.resource_type != resource_type or event.metadata_json != metadata or event.outcome != "success"):
            raise HTTPException(status_code=409, detail="Event ID đã được dùng cho nội dung khác")
        return False

    try:
        with database.session() as session:
            existing = session.get(AuditEvent, event_id)
            if existing is not None:
                return check_existing(existing)
            session.add(AuditEvent(id=event_id, workspace_id=workspace_id, event_type=payload.event_type,
                                   actor_type="user", actor_id=actor.user.id, occurred_at=utc_now(),
                                   resource_type=resource_type, resource_id=str(payload.resource_id),
                                   outcome="success", metadata_json=metadata))
            session.commit()
            return True
    except IntegrityError:
        # A concurrent retry may win the unique event ID race.
        with database.session() as session:
            existing = session.get(AuditEvent, event_id)
            if existing is None:
                raise
            return check_existing(existing)
