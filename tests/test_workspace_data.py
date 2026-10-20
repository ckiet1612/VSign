from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.platform_db import Membership
from test_local_admin import local_settings
from tests.test_personal_collection import sample_payload

BASE = "/api/v1/workspace/data"


@pytest.fixture
def configured(monkeypatch, tmp_path):
    return replace(local_settings(monkeypatch, tmp_path), collection_enabled=True,
                   collection_dir=tmp_path / "media")


def post(client, path, body, status=200):
    response = client.post(BASE + path, json=body)
    assert response.status_code == status, response.text
    return response.json()


def prepare(client, quota=100):
    labels_id, label_id, dataset_id, session_id = [str(uuid4()) for _ in range(4)]
    post(client, "/labels", {"request_id": labels_id, "name": "Sales", "entries": [
        {"id": label_id, "name": "Cho", "kind": "sign"}]}, 201)
    post(client, "/datasets", {"request_id": dataset_id, "name": "Đợt thu 1",
        "label_version_id": labels_id, "quota_per_label": quota}, 201)
    post(client, "/sessions", {"request_id": session_id, "dataset_version_id": dataset_id}, 201)
    return labels_id, label_id, dataset_id, session_id


def save(client, session_id, **overrides):
    return client.post(BASE + f"/sessions/{session_id}/samples", json=sample_payload(**overrides))


def test_data_overview_is_scoped_and_never_imports_legacy(configured):
    old = configured.collection_dir / "batches/personal-100/cho/right/old.mp4"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"legacy")
    with TestClient(create_app(configured)) as client:
        response = client.get(BASE)
        assert response.status_code == 200
        assert response.json()["workspace_id"] == configured.workspace_id
        assert response.json()["datasets"] == []
        assert response.json()["sessions"] == []
        assert response.json()["snapshots"] == []
        assert response.json()["permissions"] == {"manage": True, "collect": True}
    assert old.read_bytes() == b"legacy"


def test_session_counts_retries_and_persistence(configured):
    with TestClient(create_app(configured)) as client:
        _, _, dataset_id, session_id = prepare(client)
        payload = sample_payload()
        first = save(client, session_id)
        assert first.status_code == 200, first.text
        assert first.json()["label_count"] == 1
        assert save(client, session_id).json() == first.json()
        assert save(client, session_id, duration_ms=2200).status_code == 409
        post(client, f"/sessions/{session_id}/state", {"state": "paused"})
        assert save(client, session_id, sample_key=str(uuid4())).status_code == 409
        post(client, f"/sessions/{session_id}/state", {"state": "running"})
        assert save(client, session_id, sample_key=str(uuid4()), hand="left").status_code == 200
        post(client, f"/sessions/{session_id}/state", {"state": "stopped"})
        assert save(client, session_id).status_code == 200  # lost ACK after closure
        assert save(client, session_id, sample_key=str(uuid4())).status_code == 409
        assert payload["expected_label"] == "Cho"
    with TestClient(create_app(configured)) as client:
        overview = client.get(BASE).json()
        dataset = next(item for item in overview["datasets"] if item["id"] == dataset_id)
        assert dataset["sample_count"] == 2
        assert dataset["counts"]["Cho"] == {"right": 1, "left": 1}
        assert overview["sessions"][0]["sample_count"] == 2
        assert overview["sessions"][0]["state"] == "stopped"


def test_quota_is_atomic_across_sessions_and_hands(configured):
    with TestClient(create_app(configured)) as client:
        _, _, dataset_id, first = prepare(client, quota=1)
        second = str(uuid4())
        post(client, "/sessions", {"request_id": second, "dataset_version_id": dataset_id}, 201)
        def submit(pair):
            session_id, hand = pair
            return save(client, session_id, hand=hand, sample_key=str(uuid4())).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(submit, [(first, "right"), (second, "left")])) == [200, 409]
        assert client.get(BASE).json()["datasets"][0]["sample_count"] == 1


def test_snapshot_is_nonempty_closed_immutable_and_verified(configured):
    with TestClient(create_app(configured)) as client:
        _, _, dataset_id, session_id = prepare(client)
        snapshot_id = str(uuid4())
        assert client.post(BASE + f"/datasets/{dataset_id}/snapshot", json={"request_id": snapshot_id}).status_code == 409
        assert save(client, session_id).status_code == 200
        assert client.post(BASE + f"/datasets/{dataset_id}/snapshot", json={"request_id": snapshot_id}).status_code == 409
        post(client, f"/sessions/{session_id}/state", {"state": "stopped"})
        overview = post(client, f"/datasets/{dataset_id}/snapshot", {"request_id": snapshot_id}, 201)
        assert overview["datasets"][0]["status"] == "sealed"
        snapshot = overview["snapshots"][0]
        assert snapshot["sample_count"] == 1
        assert len(snapshot["sha256"]) == 64
        assert post(client, f"/datasets/{dataset_id}/snapshot", {"request_id": snapshot_id}, 201)["snapshots"] == overview["snapshots"]
        assert client.post(BASE + "/sessions", json={"request_id": str(uuid4()), "dataset_version_id": dataset_id}).status_code == 409
        assert client.post(BASE + f"/datasets/{dataset_id}/quota", json={"quota_per_label": 200}).status_code == 409
        manifest = client.get(BASE + f"/snapshots/{snapshot_id}/manifest")
        assert manifest.status_code == 200
        assert manifest.json()["workspace_id"] == configured.workspace_id
        assert manifest.json()["dataset_version_id"] == dataset_id
        # Snapshot copies are independent of the draft's source files.
        draft_file = next((configured.collection_dir / "workspaces" / configured.workspace_id / "datasets").rglob("*.mp4"))
        draft_file.write_bytes(b"changed source")
        assert client.get(BASE + f"/snapshots/{snapshot_id}/manifest").status_code == 200
        frozen_file = next((configured.collection_dir / "workspaces" / configured.workspace_id / "snapshots").rglob("*.mp4"))
        frozen_file.write_bytes(b"tampered snapshot")
        assert client.get(BASE + f"/snapshots/{snapshot_id}/manifest").status_code == 409


def test_workspace_does_not_expose_or_accept_other_workspace_ids(configured):
    with TestClient(create_app(configured)) as client:
        labels_id, _, dataset_id, session_id = prepare(client)
    with TestClient(create_app(replace(configured, workspace_id="other"))) as client:
        assert client.get(BASE).json()["datasets"] == []
        assert client.post(BASE + "/datasets", json={"request_id": str(uuid4()), "name": "other",
            "label_version_id": labels_id}).status_code == 404
        assert client.post(BASE + "/sessions", json={"request_id": str(uuid4()), "dataset_version_id": dataset_id}).status_code == 404
        assert save(client, session_id).status_code == 404


def test_label_versions_preserve_ids_and_existing_dataset(configured):
    with TestClient(create_app(configured)) as client:
        labels_id, label_id, dataset_id, _ = prepare(client)
        new_id = str(uuid4())
        post(client, "/labels", {"request_id": new_id, "name": "Sales v2", "parent_id": labels_id,
            "entries": [{"id": label_id, "name": "Cho mới", "kind": "sign"}]}, 201)
        overview = client.get(BASE).json()
        assert next(item for item in overview["labels"] if item["id"] == labels_id)["entries"][0]["name"] == "Cho"
        assert overview["datasets"][0]["label_version_id"] == labels_id
        assert overview["datasets"][0]["id"] == dataset_id
        assert client.post(BASE + "/labels", json={"request_id": str(uuid4()), "name": "Duplicate",
            "entries": [{"id": str(uuid4()), "name": "Cho", "kind": "sign"},
                        {"id": str(uuid4()), "name": "cho", "kind": "sign"}]}).status_code == 422


@pytest.mark.parametrize("role,manage,collect", [("owner", True, True), ("admin", True, True),
    ("operator", False, True), ("reviewer", False, False), ("viewer", False, False), ("model_admin", False, False)])
def test_data_permissions_enforced_before_body_parsing(configured, role, manage, collect):
    settings = replace(configured, local_admin_enabled=False, bootstrap_admin_email="admin@example.com",
                       bootstrap_admin_password="test-password-12345")
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = role
            session.commit()
        assert client.post("/api/v1/auth/login", json={"email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password}).status_code == 200
        response = client.get(BASE)
        assert response.status_code == (403 if role == "model_admin" else 200)
        assert client.post(BASE + "/datasets", json={}).status_code == (422 if manage else 403)
        assert client.post(BASE + "/sessions", json={}).status_code == (422 if collect else 403)


def test_auth_origin_disabled_collection_and_missing_session(configured):
    with TestClient(create_app(replace(configured, local_admin_enabled=False))) as client:
        assert client.get(BASE).status_code == 401
        assert client.post(BASE + "/datasets", json={}).status_code == 401
    with TestClient(create_app(configured)) as client:
        assert client.post(BASE + "/labels", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    with TestClient(create_app(replace(configured, collection_enabled=False))) as client:
        assert client.get(BASE).status_code == 200
        _, _, dataset_id, _ = prepare_disabled(client)
        assert client.post(BASE + "/sessions", json={"request_id": str(uuid4()), "dataset_version_id": dataset_id}).status_code == 403


def prepare_disabled(client):
    labels_id, label_id, dataset_id = [str(uuid4()) for _ in range(3)]
    post(client, "/labels", {"request_id": labels_id, "name": "Sales", "entries": [
        {"id": label_id, "name": "Cho", "kind": "sign"}]}, 201)
    post(client, "/datasets", {"request_id": dataset_id, "name": "Đợt thu", "label_version_id": labels_id}, 201)
    return labels_id, label_id, dataset_id, None


def test_disabled_collection_cannot_resume_but_can_close_existing_session(configured):
    with TestClient(create_app(configured)) as client:
        _, _, _, session_id = prepare(client)
        post(client, f"/sessions/{session_id}/state", {"state": "paused"})
    with TestClient(create_app(replace(configured, collection_enabled=False))) as client:
        assert client.post(BASE + f"/sessions/{session_id}/state", json={"state": "running"}).status_code == 403
        data = post(client, f"/sessions/{session_id}/state", {"state": "stopped"})
        assert data["sessions"][0]["state"] == "stopped"


def test_encoding_failure_never_counts_partial_media(configured, monkeypatch):
    import app.collection as collection
    def fail(path, *args):
        path.write_bytes(b"partial")
        raise RuntimeError("encoder failed")
    with TestClient(create_app(configured)) as client:
        _, _, _, session_id = prepare(client)
        monkeypatch.setattr(collection, "_encode_video", fail)
        assert save(client, session_id).status_code == 503
        assert client.get(BASE).json()["datasets"][0]["sample_count"] == 0
    assert not list(configured.collection_dir.rglob("*.mp4"))


@pytest.mark.parametrize("target", ["sample", "snapshot"])
def test_published_files_after_failed_commit_are_not_counted_and_retry_recovers(configured, monkeypatch, target):
    from sqlalchemy.orm import Session
    from app.workspace_data_db import DataSample, DatasetSnapshot
    original = Session.commit
    failed = False
    def commit(session):
        nonlocal failed
        if not failed and any(isinstance(row, DataSample if target == "sample" else DatasetSnapshot) for row in session.new):
            failed = True
            raise RuntimeError("commit failed before transaction commit")
        return original(session)
    with TestClient(create_app(configured)) as client:
        _, _, dataset_id, session_id = prepare(client)
        snapshot_id = str(uuid4())
        if target == "snapshot":
            assert save(client, session_id).status_code == 200
            post(client, f"/sessions/{session_id}/state", {"state": "stopped"})
        monkeypatch.setattr(Session, "commit", commit)
        operation = (lambda: save(client, session_id)) if target == "sample" else (
            lambda: client.post(BASE + f"/datasets/{dataset_id}/snapshot", json={"request_id": snapshot_id}))
        assert operation().status_code == 503
        overview = client.get(BASE).json()
        assert overview["datasets"][0]["status"] == "draft"
        assert overview["snapshots"] == []
        assert overview["datasets"][0]["sample_count"] == (0 if target == "sample" else 1)
        if target == "sample":
            residue = next((configured.collection_dir / "workspaces").rglob("*.mp4"))
            residue.write_bytes(b"corrupted-uncommitted-residue")
        assert operation().status_code == (200 if target == "sample" else 201)
        assert client.get(BASE).json()["datasets"][0]["sample_count"] == 1
        if target == "sample":
            assert residue.read_bytes() != b"corrupted-uncommitted-residue"
    assert len(list((configured.collection_dir / "workspaces" / configured.workspace_id / "datasets").rglob("*.mp4"))) == 1


def test_closing_waits_for_an_already_saving_sample(configured, monkeypatch):
    import app.collection as collection
    started, finish = Event(), Event()
    original = collection._encode_video
    def encode(*args):
        started.set()
        assert finish.wait(5)
        original(*args)
    with TestClient(create_app(configured)) as client:
        _, _, _, session_id = prepare(client)
        monkeypatch.setattr(collection, "_encode_video", encode)
        with ThreadPoolExecutor(max_workers=2) as pool:
            sample = pool.submit(save, client, session_id)
            assert started.wait(5)
            closing = pool.submit(client.post, BASE + f"/sessions/{session_id}/state", json={"state": "stopped"})
            finish.set()
            assert sample.result().status_code == 200
            assert closing.result().status_code == 200
        assert client.get(BASE).json()["sessions"][0]["sample_count"] == 1
        assert save(client, session_id, sample_key=str(uuid4())).status_code == 409


def test_quota_is_shared_across_separate_app_instances(configured):
    with TestClient(create_app(configured)) as first, TestClient(create_app(configured)) as second:
        _, _, _, session_id = prepare(first, quota=1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda client: save(client, session_id, sample_key=str(uuid4())), [first, second]))
        assert sorted(response.status_code for response in responses) == [200, 409]
        assert second.get(BASE).json()["datasets"][0]["sample_count"] == 1


def test_snapshot_rejects_source_tampering_and_symlink(configured):
    with TestClient(create_app(configured)) as client:
        _, _, dataset_id, session_id = prepare(client)
        assert save(client, session_id).status_code == 200
        post(client, f"/sessions/{session_id}/state", {"state": "stopped"})
        video = next((configured.collection_dir / "workspaces").rglob("*.mp4"))
        original = video.read_bytes()
        video.write_bytes(b"changed")
        assert client.post(BASE + f"/datasets/{dataset_id}/snapshot", json={"request_id": str(uuid4())}).status_code == 409
        video.write_bytes(original)
        outside = configured.collection_dir / "outside.mp4"
        outside.write_bytes(original)
        video.unlink()
        video.symlink_to(outside)
        assert client.post(BASE + f"/datasets/{dataset_id}/snapshot", json={"request_id": str(uuid4())}).status_code == 409


def test_metadata_model_and_audit_are_independent_of_dataset_labels(configured):
    with TestClient(create_app(configured)) as client:
        before = client.get("/metadata").json()
        prepare(client)
        assert client.get("/metadata").json() == before
        events = client.get("/api/v1/workspace/audit/events?group=data").json()["events"]
        assert {row["event_type"] for row in events} == {"data.labels_created", "data.dataset_created"}
        assert all(row["workspace_id"] == configured.workspace_id for row in events)


def test_whitespace_names_and_reusing_label_id_without_parent_are_rejected(configured):
    with TestClient(create_app(configured)) as client:
        _, label_id, _, _ = prepare(client)
        payload = {"request_id": str(uuid4()), "name": " ", "entries": [{"id": str(uuid4()), "name": "A", "kind": "sign"}]}
        assert client.post(BASE + "/labels", json=payload).status_code == 422
        assert client.post(BASE + "/labels", json={**payload, "name": "Unrelated",
            "entries": [{"id": label_id, "name": "Other", "kind": "sign"}]}).status_code == 409
