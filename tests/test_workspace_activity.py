from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.main import create_app
from app.platform_db import AuditEvent, Membership, Workspace


def settings() -> Settings:
    return Settings(database_url="sqlite:///:memory:", database_auto_create=True,
                    auth_required=False, collection_enabled=True,
                    bootstrap_admin_email="owner@example.com",
                    bootstrap_admin_password="Activity Test Password 123")


def login(client: TestClient) -> dict:
    response = client.post("/api/v1/auth/login", json={
        "email": "owner@example.com", "password": "Activity Test Password 123",
    })
    assert response.status_code == 200
    return response.json()["user"]


def model_event() -> dict:
    return {"event_id": str(uuid4()), "event_type": "model.switched", "resource_id": str(uuid4()),
            "model_version": "candidate-v2", "previous_model_version": "current-v1",
            "model_option": "seated", "previous_model_option": "current"}


def test_client_event_body_has_a_small_size_limit() -> None:
    with TestClient(create_app(settings())) as client:
        login(client)
        response = client.post("/api/v1/workspace/audit/client-events", json={**model_event(), "padding": "x" * 5000})
        assert response.status_code == 413


def test_client_event_is_authenticated_idempotent_and_not_a_deployment() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        payload = model_event()
        assert client.post("/api/v1/workspace/audit/client-events", json=payload).status_code == 401
        user = login(client)
        first = client.post("/api/v1/workspace/audit/client-events", json=payload)
        replay = client.post("/api/v1/workspace/audit/client-events", json=payload)
        assert first.status_code == 201
        assert replay.status_code == 200
        assert first.json()["event_id"] == payload["event_id"]
        events = client.get("/api/v1/workspace/audit/events?group=model").json()["events"]
        assert len(events) == 1
        event = events[0]
        assert event["actor_type"] == "user" and event["actor_id"] == user["id"]
        assert event["event_type"] == "model.switched"
        assert event["resource_type"] == "recognition_session"
        assert event["metadata"]["source"] == "browser_report"
        assert event["metadata"]["previous_model_version"] == "current-v1"
        assert event["metadata"]["model_version"] == "candidate-v2"
        collision = client.post("/api/v1/workspace/audit/client-events", json={**payload, "model_version": "different"})
        assert collision.status_code == 409


@pytest.mark.parametrize("event_type", ["auth.login", "permission.denied", "model.deployed", "evaluation.completed", "integration.connected"])
def test_browser_cannot_forge_server_or_unconnected_events(event_type: str) -> None:
    with TestClient(create_app(settings())) as client:
        login(client)
        assert client.post("/api/v1/workspace/audit/client-events", json={**model_event(), "event_type": event_type}).status_code == 422


@pytest.mark.parametrize("extra", [{"actor_id": "someone-else"}, {"workspace_id": "other"}, {"password": "sensitive"}, {"metadata": {"token": "secret"}}])
def test_client_cannot_supply_actor_workspace_or_free_form_secrets(extra: dict) -> None:
    with TestClient(create_app(settings())) as client:
        login(client)
        assert client.post("/api/v1/workspace/audit/client-events", json={**model_event(), **extra}).status_code == 422


def test_collection_events_require_data_permission_and_denials_are_audited() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        with app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = "viewer"
            session.commit()
        user = login(client)
        payload = {"event_id": str(uuid4()), "event_type": "collection.started",
                   "resource_id": str(uuid4()), "model_version": "current-v1", "saved_samples": 0}
        denied = client.post("/api/v1/workspace/audit/client-events", json=payload)
        assert denied.status_code == 403
        events = client.get("/api/v1/workspace/audit/events?group=permission").json()["events"]
        assert len(events) == 1
        assert events[0]["event_type"] == "permission.denied"
        assert events[0]["actor_id"] == user["id"]
        assert events[0]["outcome"] == "failure"
        assert events[0]["metadata"]["permission"] == "data:use"
        assert client.get("/api/v1/workspace/audit/events?group=collection").json()["events"] == []


def test_collection_transitions_and_acknowledged_samples_are_stored_once() -> None:
    with TestClient(create_app(settings())) as client:
        login(client)
        resource_id = str(uuid4())
        for event_type in ["collection.started", "collection.paused", "collection.resumed", "collection.sample_saved", "collection.stopped", "collection.completed"]:
            payload = {"event_id": str(uuid4()), "event_type": event_type, "resource_id": resource_id,
                       "model_version": "current-v1", "saved_samples": 1 if event_type in {"collection.sample_saved", "collection.completed"} else 0}
            if event_type == "collection.sample_saved":
                payload["sample_id"] = str(uuid4())
            assert client.post("/api/v1/workspace/audit/client-events", json=payload).status_code == 201
        events = client.get("/api/v1/workspace/audit/events?group=collection").json()["events"]
        assert len(events) == 6
        assert all(event["resource_type"] == "collection_session" for event in events)
        assert {event["resource_id"] for event in events} == {resource_id}


def test_filters_pagination_and_workspace_scope_are_applied_together() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        login(client)
        with app.state.platform_database.session() as session:
            session.add(Workspace(id="other", name="Other", environment="production"))
            session.flush()
            for i, (workspace, event_type, outcome, hour) in enumerate([
                ("local", "model.switched", "success", 10), ("local", "model.switched", "success", 10),
                ("local", "model.switched", "success", 11), ("local", "model.switched", "failure", 10),
                ("local", "auth.logout", "success", 10), ("other", "model.switched", "success", 10),
            ]):
                session.add(AuditEvent(id=f"00000000-0000-4000-8000-{i:012d}", workspace_id=workspace,
                                       event_type=event_type, actor_type="system", outcome=outcome,
                                       occurred_at=datetime(2026, 10, 15, hour, tzinfo=timezone.utc), metadata_json={}))
            session.commit()
        query = "/api/v1/workspace/audit/events?group=model&outcome=success&from_at=2026-10-15T09:59:00Z&to_at=2026-10-15T10:01:00Z&limit=1"
        first = client.get(query)
        assert first.status_code == 200
        page = first.json()
        assert len(page["events"]) == 1 and page["has_more"] is True
        assert page["events"][0]["event_id"].endswith("000000000001")
        second = client.get(query, params={"cursor": page["next_cursor"]}).json()
        assert len(second["events"]) == 1 and second["has_more"] is False
        assert second["events"][0]["event_id"].endswith("000000000000")


def test_invalid_filters_fail_instead_of_silently_showing_all_events() -> None:
    with TestClient(create_app(settings())) as client:
        login(client)
        for query in ["group=unknown", "outcome=unknown", "from_at=tomorrow", "from_at=2026-10-16T00:00:00Z&to_at=2026-10-15T00:00:00Z"]:
            assert client.get(f"/api/v1/workspace/audit/events?{query}").status_code == 422


def test_private_values_are_redacted_from_legacy_metadata() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        login(client)
        with app.state.platform_database.session() as session:
            session.add(AuditEvent(id=str(uuid4()), workspace_id="local", event_type="integration.failed", actor_type="system", outcome="failure",
                                   metadata_json={"secret": "raw-secret", "nested": {"access_token": "raw-token", "model_version": "v1"},
                                                  "apiKey": "camel-key", "APIKEY": "upper-key", "api-key": "dash-key",
                                                  "account_key": "private-hash", "list": [{"password": "raw-password"}]}))
            session.commit()
        response = client.get("/api/v1/workspace/audit/events?group=integration")
        assert response.status_code == 200
        assert "raw-secret" not in response.text and "raw-token" not in response.text
        assert "raw-password" not in response.text and "private-hash" not in response.text
        assert "camel-key" not in response.text and "upper-key" not in response.text and "dash-key" not in response.text
        assert response.json()["events"][0]["metadata"]["nested"]["model_version"] == "v1"


def test_cross_origin_client_event_is_rejected_and_database_failure_is_not_acknowledged(monkeypatch) -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        login(client)
        assert client.post("/api/v1/workspace/audit/client-events", json=model_event(), headers={"Origin": "https://foreign.example"}).status_code == 403
        monkeypatch.setattr(app.state.platform_database, "session", lambda: (_ for _ in ()).throw(SQLAlchemyError("store offline")))
        response = client.post("/api/v1/workspace/audit/client-events", json=model_event())
        assert response.status_code == 503
