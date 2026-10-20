from dataclasses import replace
from datetime import timedelta

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.platform_db import AuthSession, Membership, User, utc_now
from test_platform_auth import auth_settings


def test_username_login_uses_the_reserved_internal_email_and_session():
    settings = replace(auth_settings("sqlite:///:memory:"),
                       bootstrap_admin_email="vsignadmin@vsign.invalid")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/workspace").status_code == 401
        response = client.post("/api/v1/auth/login", json={
            "email": " VSIGNADMIN ", "password": settings.bootstrap_admin_password})
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/api/v1/auth/me").json()["auth_mode"] == "session"
        assert client.get("/api/v1/workspace").status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 200
        assert client.get("/api/v1/workspace").status_code == 401


@pytest.mark.parametrize("method,path", [
    ("post", "/sentence/compose"), ("get", "/collection/summary"),
    ("post", "/collection/samples"),
])
def test_runtime_http_requires_session_when_auth_is_required(method, path):
    with TestClient(create_app(auth_settings("sqlite:///:memory:"))) as client:
        assert getattr(client, method)(path).status_code == 401


def test_runtime_denials_keep_cors_and_authorized_requests_work():
    settings = auth_settings("sqlite:///:memory:")
    with TestClient(create_app(settings)) as client:
        headers = {"Origin": settings.allowed_origins[0]}
        response = client.get("/collection/summary", headers=headers)
        assert response.status_code == 401
        assert response.headers.get("access-control-allow-origin") == settings.allowed_origins[0]
        client.post("/api/v1/auth/login", headers=headers, json={
            "email": "admin@example.com", "password": settings.bootstrap_admin_password})
        assert client.get("/collection/summary", headers=headers).status_code == 200
        assert client.post("/sentence/compose", headers={"Origin": "https://evil.example"},
                           json={"words": []}).status_code == 403


def test_runtime_socket_requires_session_and_rejects_revoked_session():
    app = create_app(auth_settings("sqlite:///:memory:"))
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/ws/inference"):
                pass
        assert denied.value.code == 1008
        client.post("/api/v1/auth/login", json={
            "email": "admin@example.com", "password": "Correct Horse Battery Staple"})
        with client.websocket_connect("/ws/inference") as socket:
            client.post("/api/v1/auth/logout")
            socket.send_text("{}")
            with pytest.raises(WebSocketDisconnect) as revoked:
                socket.receive_json()
            assert revoked.value.code == 1008


@pytest.mark.parametrize("invalidation", ["expired", "revoked", "inactive_user", "suspended_membership"])
def test_runtime_rechecks_session_validity_for_http_and_open_socket(invalidation):
    settings = auth_settings("sqlite:///:memory:")
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={
            "email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password,
        }).status_code == 200
        with client.websocket_connect("/ws/inference") as socket:
            with app.state.platform_database.session() as session:
                if invalidation == "expired":
                    session.query(AuthSession).one().expires_at = utc_now() - timedelta(seconds=1)
                elif invalidation == "revoked":
                    session.query(AuthSession).one().revoked_at = utc_now()
                elif invalidation == "inactive_user":
                    session.query(User).one().is_active = False
                else:
                    session.query(Membership).one().status = "suspended"
                session.commit()
            assert client.get("/collection/summary").status_code == 401
            assert client.post("/sentence/compose", json={"words": []}).status_code == 401
            socket.send_text("{}")
            with pytest.raises(WebSocketDisconnect) as denied:
                socket.receive_json()
            assert denied.value.code == 1008


def test_runtime_collection_requires_data_permission_not_just_a_valid_login():
    settings = auth_settings("sqlite:///:memory:")
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={
            "email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password,
        }).status_code == 200
        with app.state.platform_database.session() as session:
            session.query(Membership).one().role = "viewer"
            session.commit()
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.get("/collection/summary").status_code == 403
        assert client.post("/collection/samples", json={}).status_code == 403


def test_https_login_cookie_and_credentialed_preflight():
    settings = replace(auth_settings("sqlite:///:memory:"), auth_cookie_secure=True,
                       allowed_origins=("https://vsign.io.vn",))
    with TestClient(create_app(settings), base_url="https://api.vsign.io.vn") as client:
        headers = {"Origin": settings.allowed_origins[0]}
        preflight = client.options("/sentence/compose", headers={
            **headers, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == settings.allowed_origins[0]
        assert preflight.headers["access-control-allow-credentials"] == "true"
        response = client.post("/api/v1/auth/login", headers=headers, json={
            "email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password,
        })
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert all(attribute in cookie for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"))
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        assert client.get("/collection/summary", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
        denied = client.get("/collection/summary", headers=headers)
        assert denied.status_code == 401
        assert denied.headers["access-control-allow-origin"] == settings.allowed_origins[0]
        assert denied.headers["access-control-allow-credentials"] == "true"


def test_public_provisioning_is_explicit_and_never_overwrites_existing_accounts():
    from app.provision_admin import provision_admin

    settings = replace(auth_settings("sqlite:///:memory:"),
                       bootstrap_admin_email=None, bootstrap_admin_password=None)
    app = create_app(settings)
    with TestClient(app) as client:
        database = app.state.platform_database
        with pytest.raises(ValueError, match="12"):
            provision_admin(database, settings, "vsignadmin", "short-pass")
        provision_admin(database, settings, "vsignadmin", "short-pass", allow_short_password=True)
        with database.session() as session:
            user = session.query(User).one()
            assert user.email == "vsignadmin@vsign.invalid"
            assert PasswordHasher().verify(user.password_hash, "short-pass")
            assert session.query(Membership).one().role == "system_admin"
            assert session.query(AuthSession).count() == 0
        with pytest.raises(ValueError, match="already exists"):
            provision_admin(database, settings, "vsignadmin", "another-long-password")
        assert client.post("/api/v1/auth/login", json={
            "email": "vsignadmin", "password": "short-pass"}).status_code == 200


def test_public_launcher_keeps_local_database_and_port_separate():
    import os
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/run_public_local.sh"
    for overrides in ({"INFERENCE_PORT": "8000"}, {"LOCAL_ADMIN_ENABLED": "true"},
                      {"DATABASE_URL": "sqlite:///./data/vsign-platform.db"},
                      {"AUTH_REQUIRED": "false"}, {"INFERENCE_HOST": "0.0.0.0"},
                      {"AUTH_COOKIE_SECURE": "false"}):
        result = subprocess.run(["bash", str(script)], env={**os.environ, **overrides},
                                text=True, capture_output=True)
        assert result.returncode != 0
        assert "Public runtime" in result.stderr
