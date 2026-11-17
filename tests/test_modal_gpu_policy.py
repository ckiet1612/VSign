from dataclasses import replace

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.platform_db import Membership, User


PATH = "/api/v1/inference/modal-policy"
LOGIN = {"email": "admin@example.com", "password": "Correct Horse Battery Staple"}


def settings_for(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'platform.db'}",
        auth_required=True,
        bootstrap_admin_email=LOGIN["email"],
        bootstrap_admin_password=LOGIN["password"],
        inference_token_secret="fixture-inference-secret-not-for-production",
    )


def login(client):
    assert client.post("/api/v1/auth/login", json=LOGIN).status_code == 200


def promote_system_admin(app):
    with app.state.platform_database.session() as session:
        membership = session.query(Membership).join(User).filter(User.email == LOGIN["email"]).one()
        membership.role = "system_admin"
        session.commit()


def test_only_system_admin_can_change_modal_policy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        assert client.post(PATH, json={"enabled": False}).status_code == 401
        login(client)
        assert client.get(PATH).json() == {"enabled": True}
        assert client.post(PATH, json={"enabled": False}).status_code == 403
        promote_system_admin(app)
        assert client.post(PATH, json={"enabled": False}, headers={"origin": "https://other.example"}).status_code == 403
        assert client.post(PATH, json={"enabled": "false"}).status_code == 422
        assert client.get(PATH).json() == {"enabled": True}


def test_modal_policy_survives_a_restart_and_can_be_reenabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        promote_system_admin(app)
        login(client)
        off = client.post(PATH, json={"enabled": False})
        assert off.status_code == 200 and off.json() == {"enabled": False}

    with TestClient(create_app(replace(settings, bootstrap_admin_email=None, bootstrap_admin_password=None))) as client:
        login(client)
        assert client.get(PATH).json() == {"enabled": False}
        assert client.post(PATH, json={"enabled": True}).json() == {"enabled": True}
        assert client.get(PATH).json() == {"enabled": True}
