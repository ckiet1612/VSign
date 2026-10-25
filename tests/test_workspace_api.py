from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_workspace_context_is_scoped_to_explicit_local_configuration() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/api/v1/workspace")

    assert response.status_code == 200
    assert response.headers["x-vsign-api-version"] == "1"
    body = response.json()
    assert body == {
        "api_version": "1",
        "workspace_id": "local",
        "name": "VSign workspace",
        "environment": "production",
        "scope_source": "local-config",
        "auth_required": False,
    }


def test_workspace_capabilities_report_only_backed_contracts() -> None:
    with TestClient(create_app(Settings(collection_enabled=True))) as client:
        response = client.get("/api/v1/workspace/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "api_version": "1",
        "workspace_id": "local",
        "capabilities": {
            "overview": True,
            "recognize": True,
            "data": False,
            "evaluation": False,
            "monitoring": True,
            "models": True,
            "activity": False,
            "reports": False,
            "integrations": False,
            "team": False,
            "settings": False,
        },
    }


def test_workspace_audit_contract_returns_persisted_login_event() -> None:
    settings = Settings(
        auth_required=True,
        database_url="sqlite:///:memory:",
        database_auto_create=True,
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password="Correct Horse Battery Staple",
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Correct Horse Battery Staple"},
        ).status_code == 200
        response = client.get("/api/v1/workspace/audit/events?limit=20")

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "1"
    assert body["workspace_id"] == "local"
    assert body["events"][0]["event_type"] == "auth.login"
    assert body["next_cursor"] is None
    assert body["has_more"] is False
    assert body["source"] == "store"


def test_local_anonymous_user_cannot_read_members_or_private_audit() -> None:
    with TestClient(create_app(Settings())) as client:
        assert client.get("/api/v1/workspace/members").status_code == 401
        assert client.get("/api/v1/workspace/audit/events").status_code == 401


def test_workspace_audit_cursor_is_keyset_and_rejects_negative_offsets() -> None:
    settings = Settings(
        auth_required=True,
        database_url="sqlite:///:memory:",
        database_auto_create=True,
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password="Correct Horse Battery Staple",
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Correct Horse Battery Staple"},
        ).status_code == 200
        assert client.get("/api/v1/workspace/audit/events?cursor=-1").status_code == 422
        assert client.get("/api/v1/workspace/audit/events?cursor=invalid").status_code == 422


def test_request_id_is_preserved_when_it_is_safe() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/api/v1/workspace", headers={"X-Request-ID": "browser-123"})

    assert response.headers["x-request-id"] == "browser-123"


def test_request_id_is_generated_when_missing() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/health")

    request_id = response.headers["x-request-id"]
    assert len(request_id) == 36
    assert request_id.count("-") == 4


def test_existing_health_contract_is_unchanged_while_receiving_platform_headers() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/health")

    assert response.json() == {
        "status": "ok",
        "backend": "mock",
        "model_version": "mock-common-20-v1",
        "protocol_version": "1.0",
    }
    assert response.headers["x-vsign-api-version"] == "1"


def test_workspace_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSPACE_ID", "acme-prod")
    monkeypatch.setenv("WORKSPACE_NAME", "Acme Production")
    monkeypatch.setenv("APP_ENV", "development")

    settings = Settings.from_env()

    assert settings.workspace_id == "acme-prod"
    assert settings.workspace_name == "Acme Production"
    assert settings.app_environment == "development"


def test_local_vite_ports_are_allowed_by_default() -> None:
    settings = Settings.from_env()
    assert "http://localhost:5174" in settings.allowed_origins
    assert "http://127.0.0.1:5174" in settings.allowed_origins
    assert "http://localhost:5175" in settings.allowed_origins
    assert "http://127.0.0.1:5175" in settings.allowed_origins


def test_workspace_id_rejects_unsafe_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSPACE_ID", "../production")

    with pytest.raises(RuntimeError, match="WORKSPACE_ID"):
        Settings.from_env()
