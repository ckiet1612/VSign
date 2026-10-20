from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.backends.base import BackendPrediction, DecodedFrame
from app.config import Settings
from app.deployment_worker import DeploymentWorker
from app.main import create_app
from app.model_manifest import labels_digest
from app.model_registry import WORKER_TTL
from app.model_registry_db import DeploymentJob, DeploymentTarget
from app.models import PredictionStatus
from app.platform_db import AuditEvent, Membership, create_database, utc_now


LABELS = ["Hello", "Bye"]
BASELINE_VERSION = "recovery-baseline"
CANDIDATE_VERSION = "recovery-candidate"


class RecoveryBackend:
    name = "onnx"
    is_mock = False
    candidate_labels_unverified = False

    def __init__(self, settings):
        self.model_version = settings.model_version
        self.labels = json.loads(settings.label_map_path.read_text())
        self.confidence_threshold = settings.confidence_threshold
        self.margin_threshold = settings.margin_threshold

    def predict(self, frames, sequence):
        return BackendPrediction(PredictionStatus.UNCERTAIN, None, None, [])


def _model_files(root, version):
    directory = root / version
    directory.mkdir(parents=True)
    artifact = directory / "model.onnx"
    artifact.write_bytes(version.encode("ascii"))
    labels = directory / "labels.json"
    labels.write_text(json.dumps(LABELS))
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps({
        "model_version": version,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "labels_sha256": labels_digest(LABELS),
        "backend": "onnx", "protocol_version": "1.0",
        "frame_count": 16, "frame_size": 224,
        "preprocessing_version": "rgb16-224-imagenet-v1",
        "confidence_threshold": .7, "margin_threshold": .15,
        "source_run_id": f"train-{version}", "status": "candidate",
    }))
    return {"manifest_path": str(manifest), "artifact_path": str(artifact),
            "labels_path": str(labels)}


@pytest.fixture
def managed_settings(tmp_path):
    root = tmp_path.resolve()
    baseline = _model_files(root, BASELINE_VERSION)
    return Settings(
        database_url=f"sqlite:///{root / 'recovery.db'}",
        app_environment="development", database_auto_create=True,
        bootstrap_admin_email="recovery@example.com",
        bootstrap_admin_password="Recovery Test Password 123",
        model_registry_roots=(root,), model_evaluation_roots=(root,),
        collection_dir=root/'collection',
        inference_backend="onnx", model_version=BASELINE_VERSION,
        labels_verified=True, onnx_model_path=Path(baseline["artifact_path"]),
        label_map_path=Path(baseline["labels_path"]),
        model_deployment_worker=True,
    )


def _app(settings):
    return create_app(settings, backend=RecoveryBackend(settings),
                      runtime_backend_factory=RecoveryBackend)


def _login(client):
    with client.app.state.platform_database.session() as session:
        session.scalar(select(Membership)).role = "model_admin"
        session.commit()
    response = client.post("/api/v1/auth/login", json={
        "email": "recovery@example.com", "password": "Recovery Test Password 123",
    })
    assert response.status_code == 200, response.text


def _snapshot(client):
    response = client.get("/api/v1/workspace/models")
    assert response.status_code == 200, response.text
    return response.json()


def _approved_candidate(client, root):
    files = _model_files(root, CANDIDATE_VERSION)
    response = client.post("/api/v1/workspace/models", json=files)
    assert response.status_code == 201, response.text
    snapshot = response.json()
    candidate = next(m for m in snapshot["models"] if m["origin"] == "candidate")
    baseline = next(m for m in snapshot["models"]
                    if m["id"] == snapshot["target"]["active_model_id"])
    metrics = {"macro_f1": .95, "false_accept_rate": .01, "latency_p95_ms": 100,
               "per_class": [{"label": label, "support": 10, "recall": .95}
                             for label in LABELS]}
    report = root / "evaluation.json"
    report.write_text(json.dumps({
        "schema_version": "1", "candidate_artifact_sha256": candidate["artifact_sha256"],
        "baseline_artifact_sha256": baseline["artifact_sha256"],
        "labels_sha256": candidate["labels_sha256"], "source_run_id": candidate["source_run_id"],
        "preprocessing_version": "rgb16-224-imagenet-v1", "protocol_version": "1.0",
        "confidence_threshold": .7, "margin_threshold": .15,
        "baseline_confidence_threshold": .7, "baseline_margin_threshold": .15,
        "dataset_snapshot_sha256": "a" * 64, "held_out": True,
        "independent_negatives": True, "positive_count": 20, "negative_count": 30,
        "baseline": metrics, "candidate": metrics,
    }))
    response = client.post(f'/api/v1/workspace/models/{candidate["id"]}/validate',
                           json={"report_path": str(report)})
    assert response.status_code == 200, response.text
    from tests.evaluation_fixtures import seed_computed_validation
    seed_computed_validation(client,candidate['id'],json.loads(report.read_text()))
    response=client.get('/api/v1/workspace/models')
    candidate = next(m for m in response.json()["models"] if m["id"] == candidate["id"])
    assert candidate["validation"]["passed"] is True
    response = client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',
                           json={"validation_id": candidate["validation"]["id"]})
    assert response.status_code == 200, response.text
    return candidate, files


def _enqueue(client, candidate):
    request_id = str(uuid4())
    response = client.post("/api/v1/workspace/models/deployments", json={
        "request_id": request_id, "model_id": candidate["id"], "expected_revision": 0,
    })
    assert response.status_code == 202, response.text
    return request_id


def _wait_job(client, request_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        snapshot = _snapshot(client)
        job = next(j for j in snapshot["deployments"] if j["id"] == request_id)
        if job["status"] in {"succeeded", "failed"}:
            return snapshot, job
        time.sleep(.02)
    pytest.fail(f"Deployment {request_id} did not finish")


def _assert_old_model(app, client, snapshot, baseline_id, backend):
    target = snapshot["target"]
    assert target["active_model_id"] == baseline_id
    assert target["observed_model_id"] == baseline_id
    assert target["previous_model_id"] is None
    assert target["revision"] == 0
    assert target["pending_job_id"] is None
    assert app.state.backend is backend
    response = client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json()["model_version"] == BASELINE_VERSION


@pytest.mark.parametrize("pending_status", ["queued", "loading"])
def test_crashed_worker_stale_heartbeat_recovers_pending_job(
    managed_settings, monkeypatch, pending_status,
):
    settings = managed_settings
    app = _app(settings)
    with monkeypatch.context() as paused:
        paused.setattr(DeploymentWorker, "_claim_job", lambda self: None)
        with TestClient(app) as client:
            _login(client)
            candidate, _ = _approved_candidate(client, settings.onnx_model_path.parent.parent)
            request_id = _enqueue(client, candidate)
            with app.state.platform_database.session() as session:
                target = session.get(DeploymentTarget, (settings.workspace_id, settings.model_deployment_target))
                crashed_worker_id, baseline_id = target.worker_id, target.active_model_id

    # Persist the state left by a crash, rather than the lease cleared by graceful stop.
    database = create_database(settings.database_url)
    try:
        with database.session() as session:
            target = session.get(DeploymentTarget, (settings.workspace_id, settings.model_deployment_target))
            target.worker_id = crashed_worker_id
            target.heartbeat_at = utc_now() - timedelta(seconds=WORKER_TTL + 10)
            job = session.get(DeploymentJob, request_id)
            job.status = pending_status
            job.worker_id = crashed_worker_id if pending_status == "loading" else None
            session.commit()
        with database.session() as session:
            target = session.get(DeploymentTarget, (settings.workspace_id, settings.model_deployment_target))
            assert target.heartbeat_at.tzinfo is None
    finally:
        database.dispose()

    restored = _app(settings)
    with TestClient(restored) as client:
        backend = restored.state.backend
        _login(client)
        snapshot, job = _wait_job(client, request_id)
        with restored.state.platform_database.session() as session:
            target = session.get(DeploymentTarget, (settings.workspace_id, settings.model_deployment_target))
            assert target.worker_id and target.worker_id != crashed_worker_id
        assert snapshot["target"]["worker_online"] is True
        if pending_status == "queued":
            assert job["status"] == "succeeded", job
            assert snapshot["target"]["active_model_id"] == candidate["id"]
            assert snapshot["target"]["observed_model_id"] == candidate["id"]
            assert snapshot["target"]["previous_model_id"] == baseline_id
            assert snapshot["target"]["revision"] == 1
            assert snapshot["target"]["pending_job_id"] is None
            assert client.get("/health").json()["model_version"] == CANDIDATE_VERSION
        else:
            assert job["status"] == "failed", job
            assert job["finished_at"] is not None
            _assert_old_model(restored, client, snapshot, baseline_id, backend)


def _write_tiny_onnx(path, values=(2., 0.)):
    onnx = pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    helper, tensor_type = onnx.helper, onnx.TensorProto
    logits = helper.make_tensor("value", tensor_type.FLOAT, [1, 2], values)
    graph = helper.make_graph(
        [helper.make_node("Constant", [], ["logits"], value=logits)], "recovery-model",
        [helper.make_tensor_value_info("frames", tensor_type.FLOAT, [1, 3, 16, 224, 224])],
        [helper.make_tensor_value_info("logits", tensor_type.FLOAT, [1, 2])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


@pytest.mark.parametrize("override", [
    {"confidence_threshold": .95}, {"margin_threshold": .95},
], ids=["confidence", "margin"])
def test_restart_restores_manifest_thresholds_in_real_onnx_backend(managed_settings, override):
    settings = managed_settings
    _write_tiny_onnx(settings.onnx_model_path)
    with TestClient(create_app(settings)):
        pass

    restarted = create_app(replace(settings, **override))
    with TestClient(restarted) as client:
        metadata = client.get("/metadata")
        assert metadata.status_code == 200, metadata.text
        backend = restarted.state.backend
        with Image.new("RGB", (224, 224)) as image:
            frames = [DecodedFrame(image=image, encoded_bytes=b"") for _ in range(16)]
            prediction = backend.predict(frames, 1)
        assert (backend.confidence_threshold, backend.margin_threshold, prediction.status) == (
            .7, .15, PredictionStatus.OK,
        )
        assert prediction.label == LABELS[0]
        assert prediction.confidence == pytest.approx(.880797, abs=1e-5)
        assert metadata.json()["confidence_threshold"] == backend.confidence_threshold
        assert metadata.json()["margin_threshold"] == backend.margin_threshold


def test_candidate_tampered_while_waiting_for_inference_slot_preserves_pointer(
    managed_settings, monkeypatch,
):
    settings = managed_settings
    candidate_loaded = Event()
    original_load = DeploymentWorker._load

    def observe_verified_load(self, model, *args, **kwargs):
        loaded = original_load(self, model, *args, **kwargs)
        if model.model_version == CANDIDATE_VERSION:
            candidate_loaded.set()
        return loaded

    monkeypatch.setattr(DeploymentWorker, "_load", observe_verified_load)
    app = _app(settings)
    with TestClient(app) as client:
        _login(client)
        candidate, files = _approved_candidate(client, settings.onnx_model_path.parent.parent)
        baseline_id = _snapshot(client)["target"]["active_model_id"]
        backend = app.state.backend
        assert client.portal is not None
        client.portal.call(app.state.inference_slots.acquire)
        try:
            request_id = _enqueue(client, candidate)
            assert candidate_loaded.wait(5), "Candidate never completed load verification"
            assert _snapshot(client)["target"]["active_model_id"] == baseline_id
            Path(files["artifact_path"]).write_bytes(b"changed-after-load-before-activation")
        finally:
            client.portal.call(app.state.inference_slots.release)
        snapshot, job = _wait_job(client, request_id)
        assert job["status"] == "failed", job
        _assert_old_model(app, client, snapshot, baseline_id, backend)

    with TestClient(_app(settings)) as client:
        assert client.get("/health").json()["model_version"] == BASELINE_VERSION


def test_bootstrap_reloads_bytes_verified_after_initial_backend_creation(managed_settings):
    from contracts.model_lifecycle_lock import lifecycle_lock
    settings = managed_settings
    _write_tiny_onnx(settings.onnx_model_path)
    app = create_app(settings)
    initial_backend = app.state.backend
    with lifecycle_lock(settings.database_url, training=True):
        _write_tiny_onnx(settings.onnx_model_path, values=(0., 2.))
    with TestClient(app) as client:
        _login(client)
        snapshot = _snapshot(client)
        baseline = next(model for model in snapshot["models"] if model["id"] == snapshot["target"]["active_model_id"])
        assert baseline["artifact_sha256"] == hashlib.sha256(settings.onnx_model_path.read_bytes()).hexdigest()
        assert app.state.backend is not initial_backend
        with Image.new("RGB", (224, 224)) as image:
            prediction = app.state.backend.predict([DecodedFrame(image=image, encoded_bytes=b"") for _ in range(16)], 1)
        assert prediction.label == LABELS[1]
        assert client.get("/health").status_code == 200


def test_startup_renews_expired_unclaimed_lease_after_slow_load(managed_settings, monkeypatch):
    original_load = DeploymentWorker._load

    def slow_load(self, model):
        loaded = original_load(self, model)
        with self.registry.database.session() as session:
            target = self.registry.target(session)
            target.heartbeat_at = utc_now() - timedelta(seconds=WORKER_TTL + 10)
            session.commit()
        return loaded

    monkeypatch.setattr(DeploymentWorker, "_load", slow_load)
    with TestClient(_app(managed_settings)) as client:
        assert client.get("/health").status_code == 200


def test_late_heartbeat_renews_only_same_fenced_owner(managed_settings):
    from app.model_registry import ModelRegistry, worker_online
    app = _app(managed_settings)
    with TestClient(app):
        registry = ModelRegistry(app.state.platform_database, managed_settings)
        worker = DeploymentWorker(app, registry, RecoveryBackend)
        with registry.database.session() as session:
            target = registry.target(session)
            worker.worker_id = target.worker_id
            target.heartbeat_at = utc_now() - timedelta(seconds=WORKER_TTL + 10)
            session.commit()
        worker._heartbeat()
        with registry.database.session() as session:
            target = registry.target(session)
            assert worker_online(target)
            target.worker_id = str(uuid4())
            session.commit()
        with pytest.raises(RuntimeError, match="lease lost"):
            worker._heartbeat()
        assert app.state.deployment_ready is False


def test_lost_activation_commit_ack_fails_closed_until_restart(managed_settings, monkeypatch):
    settings = managed_settings
    app = _app(settings)
    injected = Event()
    original_commit = Session.commit

    def lose_ack(session):
        activation = any(isinstance(row, AuditEvent) and row.event_type == "deployment.succeeded" for row in session.new)
        original_commit(session)
        if activation and not injected.is_set():
            injected.set()
            raise OperationalError("COMMIT", {}, RuntimeError("lost commit acknowledgement"))

    with TestClient(app) as client:
        _login(client)
        candidate, _ = _approved_candidate(client, settings.onnx_model_path.parent.parent)
        monkeypatch.setattr(Session, "commit", lose_ack)
        request_id = _enqueue(client, candidate)
        snapshot, job = _wait_job(client, request_id)
        assert injected.is_set()
        assert job["status"] == "succeeded"
        assert snapshot["target"]["active_model_id"] == candidate["id"]
        assert app.state.backend.model_version == BASELINE_VERSION
        assert client.get("/health").status_code == 503
        assert client.get("/metadata").status_code == 503
        deadline = time.monotonic() + 3
        while _snapshot(client)["target"]["observed_model_id"] is not None and time.monotonic() < deadline:
            time.sleep(.02)
        assert _snapshot(client)["target"]["observed_model_id"] is None
        assert client.post("/api/v1/workspace/models/rollback", json={"request_id": str(uuid4()), "expected_revision": 1}).status_code == 503
        time.sleep(2.2)
        assert client.get("/health").status_code == 503

    with TestClient(_app(settings)) as client:
        assert client.get("/health").json()["model_version"] == CANDIDATE_VERSION


def test_failed_activation_commit_preserves_runtime_pointer_and_audit(managed_settings):
    settings = managed_settings
    app = _app(settings)
    commit_rejected = Event()

    def fail_activation_commit(session):
        if not commit_rejected.is_set() and any(
            isinstance(row, AuditEvent) and row.event_type == "deployment.succeeded"
            for row in session.new
        ):
            session.flush()
            commit_rejected.set()
            raise OperationalError("COMMIT", {}, RuntimeError("injected activation commit failure"))

    with TestClient(app) as client:
        _login(client)
        candidate, _ = _approved_candidate(client, settings.onnx_model_path.parent.parent)
        baseline_id = _snapshot(client)["target"]["active_model_id"]
        backend = app.state.backend
        event.listen(Session, "before_commit", fail_activation_commit)
        try:
            request_id = _enqueue(client, candidate)
            snapshot, job = _wait_job(client, request_id)
        finally:
            event.remove(Session, "before_commit", fail_activation_commit)
        assert commit_rejected.is_set(), "Activation commit failure was not injected"
        assert job["status"] == "failed", job
        _assert_old_model(app, client, snapshot, baseline_id, backend)
        with app.state.platform_database.session() as session:
            events = session.scalars(select(AuditEvent).where(AuditEvent.resource_id == request_id)).all()
        assert not any(row.event_type == "deployment.succeeded" for row in events)
        assert sum(row.event_type == "deployment.failed" for row in events) == 1

    with TestClient(_app(settings)) as client:
        assert client.get("/health").json()["model_version"] == BASELINE_VERSION
