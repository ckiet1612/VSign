from __future__ import annotations

from datetime import timedelta
from dataclasses import replace

import pytest

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.platform_db import AuthSession, Database, Membership, User, Workspace, utc_now


def auth_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        database_auto_create=True,
        auth_required=True,
        bootstrap_admin_email="admin@example.com",
        bootstrap_admin_password="Correct Horse Battery Staple",
        bootstrap_admin_name="Workspace Admin",
    )


def test_bootstrap_owner_can_login_read_workspace_and_logout() -> None:
    app = create_app(auth_settings("sqlite:///:memory:"))

    with TestClient(app) as client:
        unauthenticated = client.get("/api/v1/workspace")
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "ADMIN@example.com", "password": "Correct Horse Battery Staple"},
        )
        workspace = client.get("/api/v1/workspace")
        me = client.get("/api/v1/auth/me")
        logout = client.post("/api/v1/auth/logout")
        after_logout = client.get("/api/v1/auth/me")

    assert unauthenticated.status_code == 401
    assert login.status_code == 200
    assert login.json()["user"] == {
        "id": login.json()["user"]["id"],
        "email": "admin@example.com",
        "display_name": "Workspace Admin",
        "role": "owner",
    }
    assert workspace.status_code == 200
    assert workspace.json()["workspace_id"] == "local"
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "owner"
    assert logout.status_code == 200
    assert after_logout.status_code == 401


def test_login_rejects_wrong_password_without_creating_a_session() -> None:
    with TestClient(create_app(auth_settings("sqlite:///:memory:"))) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong password"},
        )

    assert response.status_code == 401
    assert "vsign_session" not in response.cookies


def test_login_rejects_short_password_as_invalid_credentials() -> None:
    with TestClient(create_app(auth_settings("sqlite:///:memory:"))) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "x"},
        )

    assert response.status_code == 401


def test_bootstrap_does_not_promote_an_existing_membership(tmp_path) -> None:
    settings = auth_settings(f"sqlite:///{tmp_path / 'bootstrap.db'}")
    app = create_app(settings)
    with TestClient(app):
        database: Database = app.state.platform_database
        with database.session() as session:
            membership = session.query(Membership).one()
            membership.role = "reviewer"
            session.commit()

    restarted = create_app(settings)
    with TestClient(restarted):
        with restarted.state.platform_database.session() as session:
            assert session.query(Membership).one().role == "reviewer"


def test_session_is_bound_to_the_workspace() -> None:
    settings = auth_settings("sqlite:///:memory:")
    app = create_app(settings)
    with TestClient(app) as client:
        database: Database = app.state.platform_database
        assert client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Correct Horse Battery Staple"},
        ).status_code == 200
        token = client.cookies.get("vsign_session")

        assert token
        with database.session() as session:
            auth_session = session.query(AuthSession).one()
            assert auth_session.workspace_id == "local"


def test_login_and_audit_events_are_persisted_across_app_restart(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'platform.db'}"
    settings = auth_settings(database_url)
    with TestClient(create_app(settings)) as client:
        assert client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Correct Horse Battery Staple"},
        ).status_code == 200

    with TestClient(create_app(settings)) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Correct Horse Battery Staple"},
        )
        events = client.get("/api/v1/workspace/audit/events")

    assert login.status_code == 200
    assert events.status_code == 200
    assert events.json()["source"] == "store"
    assert [event["event_type"] for event in events.json()["events"]].count("auth.login") >= 2


def test_viewer_capabilities_are_read_only() -> None:
    settings = auth_settings("sqlite:///:memory:")
    app = create_app(settings)
    with TestClient(app) as client:
        database: Database = app.state.platform_database
        with database.session() as session:
            viewer = User(
                id="viewer-1", email="viewer@example.com", display_name="Viewer",
                password_hash=app.state.password_hasher.hash("Viewer Password 123"),
            )
            session.add(viewer)
            session.flush()
            session.add(Membership(workspace_id="local", user_id=viewer.id, role="viewer"))
            session.commit()
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer Password 123"},
        )
        capabilities = client.get("/api/v1/workspace/capabilities")

    assert login.status_code == 200
    assert capabilities.status_code == 200
    assert capabilities.json()["capabilities"] == {
        "overview": True,
        "recognize": True,
        "data": True,
        "evaluation": False,
        "monitoring": True,
        "models": True,
        "activity": True,
        "reports": True,
        "integrations": False,
        "team": False,
        "settings": True,
    }


def test_app_factory_does_not_open_a_database_before_startup(tmp_path) -> None:
    path = tmp_path / "new-directory" / "platform.db"
    app = create_app(auth_settings(f"sqlite:///{path}"))

    assert app.state.platform_database is None
    with TestClient(app) as client:
        assert client.get("/api/v1/workspace").status_code == 401
        assert path.exists()


def test_unmigrated_platform_database_does_not_break_inference_health(tmp_path) -> None:
    settings = replace(auth_settings(f"sqlite:///{tmp_path / 'missing.db'}"), database_auto_create=False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/workspace").status_code == 503


def test_login_rejects_a_foreign_origin() -> None:
    with TestClient(create_app(auth_settings("sqlite:///:memory:"))) as client:
        response = client.post("/api/v1/auth/login", headers={"Origin": "https://foreign.example"}, json={
            "email": "admin@example.com", "password": "Correct Horse Battery Staple",
        })
    assert response.status_code == 403


def test_login_is_rate_limited_after_repeated_invalid_attempts() -> None:
    with TestClient(create_app(auth_settings("sqlite:///:memory:"))) as client:
        for _ in range(10):
            assert client.post("/api/v1/auth/login", json={
                "email": "admin@example.com", "password": "wrong",
            }).status_code == 401
        response = client.post("/api/v1/auth/login", json={
            "email": "admin@example.com", "password": "wrong",
        })
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_login_body_is_bounded_even_without_content_length() -> None:
    with TestClient(create_app(auth_settings("sqlite:///:memory:"))) as client:
        response = client.post("/api/v1/auth/login", content=iter([b"x" * 5000]), headers={"Content-Type": "application/json"})
    assert response.status_code == 413


@pytest.mark.parametrize("role,can_read_members", [("owner", True), ("admin", True), ("operator", False), ("reviewer", False), ("viewer", False)])
def test_roles_enforce_member_read_permissions(role: str, can_read_members: bool) -> None:
    app = create_app(auth_settings("sqlite:///:memory:"))
    with TestClient(app) as client:
        with app.state.platform_database.session() as session:
            membership = session.query(Membership).one()
            membership.role = role
            session.commit()
        assert client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Correct Horse Battery Staple"}).status_code == 200
        response = client.get("/api/v1/workspace/members")
    assert response.status_code == (200 if can_read_members else 403)


def test_expired_session_is_rejected() -> None:
    app = create_app(auth_settings("sqlite:///:memory:"))
    with TestClient(app) as client:
        client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "Correct Horse Battery Staple"})
        with app.state.platform_database.session() as session:
            session.query(AuthSession).one().expires_at = utc_now() - timedelta(seconds=1)
            session.commit()
        assert client.get("/api/v1/auth/me").status_code == 401


def test_every_role_permission_has_a_label_in_the_team_page():
    """The Roles tab rejects a role list that names an unlabelled permission, so a new permission needs a label."""
    import re
    from pathlib import Path
    from app.platform_auth import ROLE_PERMISSIONS

    labels = set(re.findall(r"'([a-z_]+:[a-z_]+)'\s*:", Path('apps/web/src/lib/teamLabels.ts').read_text(encoding='utf-8')))
    assert set().union(*ROLE_PERMISSIONS.values()) - labels == set()
