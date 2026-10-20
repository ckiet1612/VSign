from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.platform_db import AuditEvent, Membership
from test_model_registry import FakeBackend, managed_settings, model_files


@pytest.mark.parametrize("role", ["owner", "admin", "operator", "reviewer", "viewer"])
def test_workspace_roles_cannot_mutate_model_lifecycle(tmp_path, role):
    settings = managed_settings(tmp_path)
    files = model_files(tmp_path, "private-candidate")
    app = create_app(settings, backend=FakeBackend(settings), runtime_backend_factory=FakeBackend)
    with TestClient(app) as client:
        with app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = role
            session.commit()
        assert client.post("/api/v1/auth/login", json={"email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password}).status_code == 200
        before = client.get("/api/v1/workspace/models").json()
        assert not any(before["permissions"].values())
        model_id, request_id = str(uuid4()), str(uuid4())
        for suffix, body in [
            ("", files), (f"/{model_id}/validate", {"report_path": str(tmp_path / "report.json")}),
            (f"/{model_id}/approve", {"validation_id": str(uuid4())}),
            ("/deployments", {"request_id": request_id, "model_id": model_id, "expected_revision": 0}),
            ("/rollback", {"request_id": request_id, "expected_revision": 0}),
        ]:
            response = client.post(f"/api/v1/workspace/models{suffix}", json=body)
            assert response.status_code == 403, (suffix, response.text)
        assert client.post("/api/v1/workspace/models", json={}).status_code == 403
        after = client.get("/api/v1/workspace/models").json()
        assert after["target"] == before["target"]
        assert after["models"] == before["models"]
        assert after["deployments"] == []
        assert client.get("/metadata").json()["model_version"] == "baseline-1"
        with app.state.platform_database.session() as session:
            assert len(session.scalars(select(AuditEvent).where(AuditEvent.event_type == "permission.denied")).all()) == 6


def test_default_local_admin_cannot_register_models(tmp_path):
    settings = replace(managed_settings(tmp_path), local_admin_enabled=True,
                       bootstrap_admin_email=None, bootstrap_admin_password=None)
    with TestClient(create_app(settings, backend=FakeBackend(settings), runtime_backend_factory=FakeBackend)) as client:
        assert client.get("/api/v1/auth/me").json()["user"]["role"] == "admin"
        assert client.post("/api/v1/workspace/models", json=model_files(tmp_path, "candidate")).status_code == 403
        assert client.get("/api/v1/workspace/members").status_code == 200


def test_internal_role_is_explicit_and_revocable(tmp_path):
    settings = managed_settings(tmp_path)
    app = create_app(settings, backend=FakeBackend(settings), runtime_backend_factory=FakeBackend)
    with TestClient(app) as client:
        with app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = "model_admin"
            session.commit()
        assert client.post("/api/v1/auth/login", json={"email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password}).status_code == 200
        assert client.get("/api/v1/auth/me").json()["user"]["role"] == "model_admin"
        assert client.post("/api/v1/workspace/models", json=model_files(tmp_path, "candidate")).status_code == 201
        # Switching back to a business role immediately loses internal access.
        with app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = "admin"
            session.commit()
        assert client.post("/api/v1/workspace/models", json=model_files(tmp_path, "second")).status_code == 403


def test_internal_members_are_not_listed_as_customer_members(tmp_path):
    settings = replace(managed_settings(tmp_path), local_admin_enabled=True)
    app = create_app(settings, backend=FakeBackend(settings), runtime_backend_factory=FakeBackend)
    with TestClient(app) as client:
        with app.state.platform_database.session() as session:
            membership = session.scalar(select(Membership).where(Membership.user_id != client.get("/api/v1/auth/me").json()["user"]["id"]))
            membership.role = "model_admin"
            session.commit()
        members = client.get("/api/v1/workspace/members").json()["members"]
        assert len(members) == 1
        assert members[0]["role"] == "admin"
