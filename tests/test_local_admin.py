from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.platform_db import AuthSession, Membership, User


def local_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.delenv("LOCAL_ADMIN_ENABLED", raising=False)
    monkeypatch.setenv("INFERENCE_BACKEND", "mock")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'platform.db'}")
    monkeypatch.setenv("DATABASE_AUTO_CREATE", "true")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    return Settings.from_env()


def test_development_defaults_to_persistent_admin_without_login(monkeypatch, tmp_path):
    settings = local_settings(monkeypatch, tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 200, response.text
        assert response.json()["auth_mode"] == "local_admin"
        actor = response.json()["user"]
        assert actor["role"] == "admin"
        assert "set-cookie" not in response.headers
        models = client.get("/api/v1/workspace/models")
        assert models.status_code == 200, models.text
        assert not any(models.json()["permissions"].values())
        assert client.get("/api/v1/workspace/audit/events").status_code == 200
        assert client.get("/api/v1/workspace/members").json()["members"][0]["id"] == actor["id"]
        client.cookies.set("vsign_session", "invalid")
        assert client.get("/api/v1/auth/me").json()["user"] == actor
        assert client.post("/api/v1/workspace/models", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.post("/api/v1/auth/login", json={"email": actor["email"], "password": "!"}).status_code == 401
        with app.state.platform_database.session() as session:
            user = session.get(User, actor["id"])
            assert user.password_hash == "!"
            assert session.scalars(select(AuthSession)).all() == []
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/auth/me").json()["user"] == actor


def test_local_admin_does_not_cross_workspace_boundaries(monkeypatch, tmp_path):
    settings = local_settings(monkeypatch, tmp_path)
    with TestClient(create_app(settings)) as client:
        first = client.get("/api/v1/auth/me")
        assert first.status_code == 200
        first_id = first.json()["user"]["id"]
    with TestClient(create_app(replace(settings, workspace_id="other"))) as client:
        second = client.get("/api/v1/auth/me")
        assert second.status_code == 200
        second_id = second.json()["user"]["id"]
        assert first_id != second_id
        assert [member["id"] for member in client.get("/api/v1/workspace/members").json()["members"]] == [second_id]


def test_local_admin_can_be_disabled_for_future_session_auth(monkeypatch, tmp_path):
    local_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCAL_ADMIN_ENABLED", "false")
    with TestClient(create_app(Settings.from_env())) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.get("/api/v1/workspace/models").status_code == 401


@pytest.mark.parametrize("environment,required", [("production", "false"), ("development", "true")])
def test_local_admin_rejects_unsafe_configuration(monkeypatch, tmp_path, environment, required):
    local_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCAL_ADMIN_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("AUTH_REQUIRED", required)
    with pytest.raises(RuntimeError, match="LOCAL_ADMIN_ENABLED"):
        Settings.from_env()


def test_local_admin_is_disabled_by_default_when_auth_is_required(monkeypatch, tmp_path):
    local_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    with TestClient(create_app(Settings.from_env())) as client:
        assert client.get("/api/v1/workspace").status_code == 401


def test_revoked_local_admin_is_not_silently_restored(monkeypatch, tmp_path):
    settings = local_settings(monkeypatch, tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 200
        with app.state.platform_database.session() as session:
            membership = session.scalar(select(Membership))
            membership.role = "viewer"
            session.commit()
        assert client.get("/api/v1/workspace/models").status_code == 503
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/auth/me").status_code == 503
