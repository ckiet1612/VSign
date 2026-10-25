from dataclasses import replace
from uuid import uuid4
from pathlib import Path
import os
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import Settings
from app.main import create_app
from app.platform_auth import ROLE_PERMISSIONS, capabilities_for
from app.platform_db import Membership
from test_local_admin import local_settings
from test_model_registry import model_files
from test_workspace_team import add_member, invitation


def system_settings(monkeypatch, tmp_path):
    local_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCAL_ADMIN_ROLE", "system_admin")
    return replace(Settings.from_env(), model_registry_roots=(tmp_path,),
                   model_evaluation_roots=(tmp_path,), collection_dir=tmp_path / "collection")


def test_system_role_combines_existing_permissions_without_promoting_business_roles():
    assert ROLE_PERMISSIONS.get("system_admin") == ROLE_PERMISSIONS["admin"] | ROLE_PERMISSIONS["model_admin"]
    assert all(capabilities_for("system_admin", True).values())
    for role in ("owner", "admin", "operator", "reviewer", "viewer"):
        assert not (ROLE_PERMISSIONS[role] & {"models:register", "models:validate", "models:approve", "models:deploy"})


def test_local_system_identity_is_explicit_separate_and_not_repaired(monkeypatch, tmp_path):
    ordinary = local_settings(monkeypatch, tmp_path)
    with TestClient(create_app(ordinary)) as client:
        business = client.get("/api/v1/auth/me").json()["user"]
    settings = system_settings(monkeypatch, tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 200, response.text
        actor = response.json()["user"]
        assert actor["role"] == "system_admin"
        assert actor["id"] != business["id"]
        assert "set-cookie" not in response.headers
        with app.state.platform_database.session() as session:
            old = session.scalar(select(Membership).where(Membership.user_id == business["id"]))
            assert old.role == "admin"
            current = session.scalar(select(Membership).where(Membership.user_id == actor["id"]))
            current.role = "viewer"
            session.commit()
        assert client.get("/api/v1/workspace/models").status_code == 503
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/auth/me").status_code == 503


@pytest.mark.parametrize("path", ["/members", "/data", "/evaluations", "/integrations", "/team", "/team/roles",
                                  "/team/invitations", "/team/audit", "/settings", "/models", "/audit/events"])
def test_system_admin_can_load_every_existing_administration_api(monkeypatch, tmp_path, path):
    with TestClient(create_app(system_settings(monkeypatch, tmp_path))) as client:
        assert client.get("/api/v1/auth/me").json()["user"]["role"] == "system_admin"
        response = client.get("/api/v1/workspace" + path)
        assert response.status_code == 200, response.text


def test_system_candidate_registration_keeps_lifecycle_gates(monkeypatch, tmp_path):
    with TestClient(create_app(system_settings(monkeypatch, tmp_path))) as client:
        before = client.get("/metadata").json()
        assert all(client.get("/api/v1/workspace/models").json()["permissions"].values())
        response = client.post("/api/v1/workspace/models", json=model_files(tmp_path, "candidate"))
        assert response.status_code == 201, response.text
        candidate = response.json()["models"][0]
        assert candidate["status"] == "candidate"
        assert response.json()["deployments"] == []
        assert client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',
                           json={"validation_id": str(uuid4())}).status_code == 409
        assert client.post("/api/v1/workspace/models/deployments", json={"request_id": str(uuid4()),
                           "model_id": candidate["id"], "expected_revision": 0}).status_code in (409, 503)
        assert client.get("/metadata").json() == before
        assert client.post("/api/v1/workspace/models", json={},
                           headers={"Origin": "https://evil.example"}).status_code == 403


def test_system_team_can_manage_business_admin_but_cannot_grant_internal_roles(monkeypatch, tmp_path):
    settings = system_settings(monkeypatch, tmp_path)
    with TestClient(create_app(settings)) as client:
        internal = add_member(client, settings, role="model_admin")
        operator = add_member(client, settings)
        body = client.get("/api/v1/workspace/team").json()
        assert "admin" in body["grantable_roles"]
        assert next(r for r in body["members"] if r["id"] == internal)["protected"]
        assert {r["id"] for r in client.get("/api/v1/workspace/team/roles").json()["roles"]} >= {"system_admin", "model_admin"}
        for role in ("system_admin", "model_admin"):
            assert client.post("/api/v1/workspace/team/invitations", json=invitation(role=role)).status_code == 422
        response = client.post(f"/api/v1/workspace/team/members/{operator}/update", json={
            "request_id": str(uuid4()), "expected_revision": 0, "role": "admin"})
        assert response.status_code == 200, response.text
        response = client.post("/api/v1/workspace/team/invitations", json=invitation(role="admin"))
        assert response.status_code == 201, response.text
        assert client.post("/api/v1/invitations/inspect", json={"token": response.json()["secret"]}).status_code == 200


def test_system_role_migration_records_current_schema(monkeypatch, tmp_path):
    app = create_app(system_settings(monkeypatch, tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/me").json()["user"]["role"] == "system_admin"
        with app.state.platform_database.engine.connect() as connection:
            assert connection.execute(text("select version_num from alembic_version")).scalar() == "0013_usage_conversations"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []


def test_system_data_evaluation_and_configuration_writes_are_connected(monkeypatch, tmp_path):
    from test_workspace_evaluations import prepare_evaluation
    settings = replace(system_settings(monkeypatch, tmp_path), collection_enabled=True)
    with TestClient(create_app(settings)) as client:
        payload = prepare_evaluation(client, settings, tmp_path)
        response = client.post('/api/v1/workspace/evaluations', json=payload)
        assert response.status_code == 201, response.text
        run = response.json()['runs'][0]
        assert run['status'] == 'queued'
        response = client.post(f'/api/v1/workspace/evaluations/{run["id"]}/cancel')
        assert response.status_code == 200, response.text
        assert response.json()['runs'][0]['status'] == 'cancelled'
        response = client.post('/api/v1/workspace/settings/update', json={
            'request_id': str(uuid4()), 'expected_revision': 0,
            'workspace': {'name': 'VSign Test System', 'timezone': 'Asia/Ho_Chi_Minh'}})
        assert response.status_code == 200, response.text
        assert response.json()['revision'] == 1
        assert client.get('/api/v1/workspace').json()['name'] == 'VSign Test System'


def test_system_api_keys_never_inherit_administrator_permissions(monkeypatch, tmp_path):
    from test_workspace_integrations import key_payload
    with TestClient(create_app(system_settings(monkeypatch, tmp_path))) as client:
        payload = key_payload()
        response = client.post('/api/v1/workspace/integrations/keys', json=payload)
        assert response.status_code == 201, response.text
        secret = response.json()['secret']
        headers = {'Authorization': 'Bearer ' + secret}
        assert client.get('/api/v1/integrations/models', headers=headers).status_code == 200
        assert client.post('/api/v1/workspace/models', json={}, headers=headers).status_code == 403
        assert secret not in client.get('/api/v1/workspace/integrations').text
        assert client.post(f'/api/v1/workspace/integrations/keys/{payload["request_id"]}/revoke', json={}).status_code == 200
        assert client.get('/api/v1/integrations/models', headers=headers).status_code == 401


def test_invalid_local_admin_role_is_rejected(monkeypatch, tmp_path):
    local_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCAL_ADMIN_ROLE", "owner")
    with pytest.raises(RuntimeError, match="LOCAL_ADMIN_ROLE"):
        Settings.from_env()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "public.example"])
def test_system_launcher_rejects_non_loopback_binding(host):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["bash", str(root / "scripts/run_system_admin_local.sh")],
                            env={**os.environ, "INFERENCE_HOST": host}, text=True, capture_output=True)
    assert result.returncode != 0
    assert "loopback" in result.stderr
