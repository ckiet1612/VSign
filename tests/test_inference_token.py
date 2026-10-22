from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.inference_token import issue_inference_token, verify_inference_token
from app.main import create_app
from test_platform_auth import auth_settings

SECRET = "s" * 40


def test_token_round_trip_and_rejections():
    token, expires_at = issue_inference_token(SECRET, "local", "user-1", ttl_seconds=60, now=1000)
    assert expires_at == 1060
    claims = verify_inference_token(SECRET, token, "local", now=1059)
    assert claims is not None and claims.user_id == "user-1"
    assert verify_inference_token(SECRET, token, "local", now=1060) is None
    assert verify_inference_token("x" * 40, token, "local", now=1000) is None
    assert verify_inference_token(SECRET, token, "other", now=1000) is None
    body, signature = token.split(".")
    assert verify_inference_token(SECRET, body + "A." + signature, "local", now=1000) is None
    for broken in (None, "", "abc", "a.b.c", token + "x"):
        assert verify_inference_token(SECRET, broken, "local", now=1000) is None


def test_inference_only_requires_a_secret():
    with pytest.raises(RuntimeError):
        Settings(runtime_role="inference_only")


def inference_only_settings() -> Settings:
    return Settings(runtime_role="inference_only", inference_token_secret=SECRET)


def test_inference_only_serves_recognition_routes_and_hides_the_platform():
    with TestClient(create_app(inference_only_settings())) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/metadata").status_code == 200
        for path in ("/api/v1/auth/me", "/api/v1/workspace", "/collection/summary"):
            assert client.get(path).status_code == 404
        assert client.post("/sentence/compose", json={"words": []}).status_code == 404
        assert client.post("/api/v1/inference/token").status_code == 404


def test_inference_only_socket_accepts_only_valid_tokens():
    with TestClient(create_app(inference_only_settings())) as client:
        for url in ("/ws/inference", "/ws/inference?token=forged.token"):
            with pytest.raises(WebSocketDisconnect) as denied:
                with client.websocket_connect(url):
                    pass
            assert denied.value.code == 1008
        token, _ = issue_inference_token(SECRET, "local", "user-1")
        with client.websocket_connect(f"/ws/inference?token={token}") as socket:
            socket.send_text("{}")
            assert socket.receive_json()["status"] == "error"


def test_open_token_socket_closes_once_the_token_expires():
    with TestClient(create_app(inference_only_settings())) as client:
        token, _ = issue_inference_token(SECRET, "local", "user-1", ttl_seconds=1)
        with client.websocket_connect(f"/ws/inference?token={token}") as socket:
            import time
            time.sleep(1.1)
            socket.send_text("{}")
            with pytest.raises(WebSocketDisconnect) as expired:
                socket.receive_json()
            assert expired.value.code == 1008


def test_signed_in_user_gets_a_token_that_the_mac_socket_also_accepts():
    settings = replace(auth_settings("sqlite:///:memory:"), inference_token_secret=SECRET)
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/inference/token").status_code == 401
        client.post("/api/v1/auth/login", json={
            "email": settings.bootstrap_admin_email, "password": settings.bootstrap_admin_password})
        assert client.post("/api/v1/inference/token",
                           headers={"Origin": "https://evil.example"}).status_code == 403
        issued = client.post("/api/v1/inference/token")
        assert issued.status_code == 200
        assert issued.headers["cache-control"] == "no-store"
        token = issued.json()["token"]
        assert verify_inference_token(SECRET, token, settings.workspace_id) is not None
        client.post("/api/v1/auth/logout")
        with client.websocket_connect(f"/ws/inference?token={token}") as socket:
            socket.send_text("{}")
            assert socket.receive_json()["status"] == "error"


def test_token_endpoint_is_absent_without_a_secret():
    settings = auth_settings("sqlite:///:memory:")
    with TestClient(create_app(settings)) as client:
        client.post("/api/v1/auth/login", json={
            "email": settings.bootstrap_admin_email, "password": settings.bootstrap_admin_password})
        assert client.post("/api/v1/inference/token").status_code == 404
