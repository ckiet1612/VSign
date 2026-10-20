from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from uuid import uuid4

import av
import pytest
from fastapi.testclient import TestClient

from app.backends.base import BackendCandidate, BackendPrediction
from app.config import Settings
from app.main import create_app
from app.dev_test_store import TrialStore, digest_bytes
from app.models import PredictionStatus
from tests.test_inference_api import image_data_url


class TestBackend:
    __test__ = False
    name, model_version = "test-fixture", "test-manual-v1"
    labels = ["Mua", "Tôi", "Không ký hiệu"]
    is_mock, candidate_labels_unverified = False, False

    def __init__(self, status="ok", label="Mua", fail=False):
        self.status, self.label, self.fail, self.calls = status, label, fail, 0

    def predict(self, frames, sequence):
        self.calls += 1
        assert len(frames) == 16
        if self.fail:
            raise RuntimeError("fixture inference failure")
        return BackendPrediction(PredictionStatus(self.status), self.label if self.status == "ok" else None,
                                 .95 if self.status == "ok" else None,
                                 [BackendCandidate(self.label or "Mua", .95)])


def settings(tmp_path):
    return Settings(app_environment="development", dev_test_enabled=True, dev_test_dir=tmp_path / "tests",
                    collection_dir=tmp_path / "collection")


def client_for(tmp_path, backend=None, **changes):
    return TestClient(create_app(replace(settings(tmp_path), **changes), backend or TestBackend()),
                      client=("127.0.0.1", 50100))


def payload(**changes):
    return {"trial_id": str(uuid4()), "session_id": str(uuid4()), "signer_id": "tester-1",
            "expected_label": "Mua", "hand": "right", "distance": "standard", "lighting": "normal",
            "negative_action": None, "captured_at": 1791650000000, "duration_ms": 1500,
            "frames": [image_data_url()] * 16, "source_frames": [image_data_url()] * 20,
            "pipeline": "manual-server-uniform-center-square-v1", **changes}


@pytest.mark.parametrize("environment,enabled", [("production", False), ("production", True), ("development", False)])
def test_dev_routes_are_absent_unless_both_development_gates_are_enabled(tmp_path, environment, enabled):
    with client_for(tmp_path, app_environment=environment, dev_test_enabled=enabled) as client:
        assert client.get("/dev-tests/config").status_code == 404
        assert client.post("/dev-tests/trials", json=payload()).status_code == 404
        assert not any(path.startswith("/dev-tests") for path in client.get("/openapi.json").json()["paths"])
    assert not (tmp_path / "tests").exists()


def test_remote_peer_cannot_read_or_write_dev_data(tmp_path):
    with TestClient(create_app(settings(tmp_path), TestBackend()), client=("203.0.113.10", 50000)) as client:
        assert client.get("/dev-tests/config").status_code == 403
        assert client.post("/dev-tests/trials", json=payload()).status_code == 403


@pytest.mark.parametrize("status,label,expected,result", [
    ("ok", "Mua", "Mua", "correct"), ("ok", "Tôi", "Mua", "wrong"),
    ("uncertain", None, "Mua", "uncertain"),
    ("uncertain", None, "Không ký hiệu", "correct_rejection"),
    ("ok", "Mua", "Không ký hiệu", "false_accept"),
])
def test_backend_classifies_outcomes_and_keeps_exact_encoded_inference_evidence(tmp_path, status, label, expected, result):
    request = payload(expected_label=expected, negative_action="still" if expected == "Không ký hiệu" else None)
    with client_for(tmp_path, TestBackend(status, label)) as client:
        saved = client.post("/dev-tests/trials", json=request)
        assert saved.status_code == 200, saved.text
        trial = saved.json()
        assert trial["outcome"] == result
        assert trial["prediction"]["label"] == label
        assert trial["model_version"] == "test-manual-v1"
        assert trial["confidence_threshold"] == .7 and trial["margin_threshold"] == .15
        video = client.get(f"/dev-tests/trials/{trial['trial_id']}/video")
        assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
        with av.open(io.BytesIO(video.content)) as container:
            assert len(list(container.decode(video=0))) == 20
        evidence = client.get(f"/dev-tests/trials/{trial['trial_id']}/frames").json()
        assert evidence["frames"] == request["frames"]
    assert not (tmp_path / "collection").exists()


def test_model_processing_failure_is_recorded_separately_not_as_uncertain(tmp_path):
    with client_for(tmp_path, TestBackend(fail=True)) as client:
        saved = client.post("/dev-tests/trials", json=payload()).json()
        assert saved["outcome"] == "technical_error"
        assert saved["error_stage"] == "inference"
        assert saved["prediction"] is None
        assert client.get(f"/dev-tests/trials/{saved['trial_id']}/video").status_code == 200


def test_lost_reply_retry_does_not_infer_again_or_duplicate_a_trial(tmp_path):
    backend = TestBackend()
    request = payload()
    with client_for(tmp_path, backend) as client:
        first = client.post("/dev-tests/trials", json=request)
        repeated = client.post("/dev-tests/trials", json=request)
        assert repeated.json() == first.json()
        assert backend.calls == 1
        assert len(client.get("/dev-tests/trials").json()["trials"]) == 1
        assert client.post("/dev-tests/trials", json={**request, "expected_label": "Tôi"}).status_code == 409


def test_review_preserves_original_result_and_reports_excluded_samples_explicitly(tmp_path):
    with client_for(tmp_path) as client:
        trial = client.post("/dev-tests/trials", json=payload()).json()
        review = {"valid": False, "notes": "Cử chỉ chưa đầy đủ", "reviewer": "staff-1"}
        assert client.put(f"/dev-tests/trials/{trial['trial_id']}/review", json=review).status_code == 200
        summary = client.get("/dev-tests/summary").json()["groups"][0]
        word = next(row for row in summary["per_word"] if row["label"] == "Mua")
        assert word["recorded"] == 1 and word["excluded"] == 1
        assert word["evaluated"] == 0 and word["correct_pct"] is None
        row = client.get("/dev-tests/trials").json()["trials"][0]
        assert row["outcome"] == "correct" and row["review"]["valid"] is False
        assert len(row["review_history"]) == 1
        assert client.put(f"/dev-tests/trials/{trial['trial_id']}/review", json={**review, "valid": True}).status_code == 200
        assert len(client.get("/dev-tests/trials").json()["trials"][0]["review_history"]) == 2


def test_exports_preserve_every_trial_and_escape_spreadsheet_formulas(tmp_path):
    with client_for(tmp_path) as client:
        trial = client.post("/dev-tests/trials", json=payload()).json()
        client.put(f"/dev-tests/trials/{trial['trial_id']}/review", json={"valid": False, "notes": "=1+1", "reviewer": "staff"})
        exported = client.get("/dev-tests/export?format=json")
        assert exported.status_code == 200
        assert len(exported.json()["trials"]) == 1
        rows = list(csv.DictReader(io.StringIO(client.get("/dev-tests/export?format=csv").text.lstrip("\ufeff"))))
        assert rows[0]["outcome"] == "correct"
        assert rows[0]["valid"] == "False" and rows[0]["notes"] == "'=1+1"


def test_statistics_keep_technical_and_negative_denominators_separate(tmp_path):
    session = str(uuid4())
    with client_for(tmp_path, TestBackend("ok", "Tôi")) as client:
        client.post("/dev-tests/trials", json=payload(session_id=session))
        client.post("/dev-tests/trials", json=payload(session_id=session, expected_label="Không ký hiệu", negative_action="random_motion"))
        client.post("/dev-tests/trials", json=payload(session_id=session, technical_error="capture failed", frames=[], source_frames=[], duration_ms=0))
        group = client.get("/dev-tests/summary").json()["groups"][0]
        assert group["positive"]["wrong_pct"] == 100.
        assert group["positive"]["evaluated"] == 1 and group["positive"]["technical_error"] == 1
        assert group["negative"]["false_accept_pct"] == 100.


def test_results_persist_across_backend_restart(tmp_path):
    with client_for(tmp_path) as client:
        client.post("/dev-tests/trials", json=payload())
    with client_for(tmp_path) as client:
        assert len(client.get("/dev-tests/trials").json()["trials"]) == 1


def test_training_directory_cannot_be_used_as_dev_test_storage(tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        create_app(replace(settings(tmp_path), dev_test_dir=tmp_path / "collection"), TestBackend())


def test_unknown_label_and_incomplete_negative_are_rejected_before_inference(tmp_path):
    backend = TestBackend()
    with client_for(tmp_path, backend) as client:
        assert client.post("/dev-tests/trials", json=payload(expected_label="not-supported")).status_code == 422
        assert client.post("/dev-tests/trials", json=payload(expected_label="Không ký hiệu")).status_code == 422
    assert backend.calls == 0


def test_lost_reply_is_recovered_even_after_runtime_changes(tmp_path):
    request = payload()
    with client_for(tmp_path) as client:
        request["runtime_key"] = client.get("/dev-tests/config").json()["runtime_key"]
        saved = client.post("/dev-tests/trials", json=request).json()
    changed = TestBackend()
    changed.model_version = "test-manual-v2"
    with client_for(tmp_path, changed) as client:
        assert client.post("/dev-tests/trials", json=request).json() == saved
        assert changed.calls == 0
        assert client.post("/dev-tests/trials", json={**request, "trial_id": str(uuid4())}).status_code == 409


def test_storage_failure_does_not_leave_counted_or_orphan_evidence_and_can_retry(tmp_path, monkeypatch):
    request = payload()
    original = TrialStore.save
    def fail_once(*args):
        monkeypatch.setattr(TrialStore, "save", original)
        raise OSError("disk temporarily unavailable")
    monkeypatch.setattr(TrialStore, "save", fail_once)
    with TestClient(create_app(settings(tmp_path), TestBackend()), client=("127.0.0.1", 50100),
                    raise_server_exceptions=False) as client:
        assert client.post("/dev-tests/trials", json=request).status_code == 503
        assert client.get("/dev-tests/summary").json()["recorded"] == 0
        assert not (tmp_path / "tests" / request["trial_id"]).exists()
        assert client.post("/dev-tests/trials", json=request).status_code == 200
        assert client.get("/dev-tests/summary").json()["recorded"] == 1


def test_video_encoder_failure_remains_retryable_without_acknowledging_lost_evidence(tmp_path, monkeypatch):
    from app import dev_test
    encode = dev_test._encode_video
    def fail_once(*args):
        monkeypatch.setattr(dev_test, "_encode_video", encode)
        raise OSError("transient video write failure")
    monkeypatch.setattr(dev_test, "_encode_video", fail_once)
    request = payload()
    with client_for(tmp_path) as client:
        assert client.post("/dev-tests/trials", json=request).status_code == 503
        assert client.get("/dev-tests/summary").json()["recorded"] == 0
        assert not (tmp_path / "tests" / request["trial_id"]).exists()
        saved = client.post("/dev-tests/trials", json=request).json()
        assert saved["video_available"] is True
        assert client.get(f"/dev-tests/trials/{saved['trial_id']}/video").status_code == 200
        assert client.get("/dev-tests/summary").json()["recorded"] == 1


def test_oversized_declared_body_is_rejected_before_model_runs(tmp_path):
    backend = TestBackend()
    with client_for(tmp_path, backend) as client:
        response = client.post("/dev-tests/trials", json=payload(), headers={"Content-Length": "999999999"})
        assert response.status_code == 413
    assert backend.calls == 0


def test_model_provenance_uses_active_backend_not_stale_path_setting(tmp_path):
    inactive = tmp_path / "inactive.pt"
    inactive.write_bytes(b"inactive-model")
    active = tmp_path / "active.onnx"
    active.write_bytes(b"active-model")
    backend = TestBackend()
    backend.name = "onnx"
    with client_for(tmp_path, backend, pytorch_model_path=inactive, onnx_model_path=active) as client:
        assert client.get("/dev-tests/config").json()["artifact_sha256"] == digest_bytes(b"active-model")


def test_storage_connections_are_closed_after_use(tmp_path):
    import sqlite3
    store = TrialStore(tmp_path / "evidence", [])
    with store.connect() as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_sessions_and_runtime_keys_are_never_merged(tmp_path):
    session = str(uuid4())
    with client_for(tmp_path) as client:
        client.post("/dev-tests/trials", json=payload(session_id=session))
        client.post("/dev-tests/trials", json=payload())
    with client_for(tmp_path, confidence_threshold=.8) as client:
        client.post("/dev-tests/trials", json=payload(session_id=session))
        groups = client.get("/dev-tests/summary").json()["groups"]
        assert len(groups) == 3
        assert all(group["positive"]["recorded"] == 1 for group in groups)


def test_browser_origin_and_frame_decode_failures_are_explicit(tmp_path):
    backend = TestBackend()
    with client_for(tmp_path, backend) as client:
        assert client.post("/dev-tests/trials", json=payload(), headers={"Origin": "http://evil.invalid"}).status_code == 403
        saved = client.post("/dev-tests/trials", json=payload(frames=["invalid"] * 16)).json()
        assert saved["outcome"] == "technical_error" and saved["error_stage"] == "decode"
        assert saved["prediction"] is None
    assert backend.calls == 0


@pytest.mark.parametrize("namespace", ["private", "cache", "manifests", "development"])
def test_any_repository_dataset_namespace_outside_dev_tests_is_protected(tmp_path, monkeypatch, namespace):
    from app import dev_test
    repo = tmp_path / "repo"
    monkeypatch.setattr(dev_test, "__file__", str(repo / "services/inference/app/dev_test.py"))
    target = repo / "ml/data" / namespace / "manual-tests"
    with pytest.raises(ValueError, match="protected"):
        create_app(replace(settings(tmp_path), dev_test_dir=target), TestBackend())
    assert not target.exists()


@pytest.mark.parametrize("note", ["\n=1+1", "  @SUM(1,2)"])
def test_csv_export_escapes_formulas_hidden_behind_leading_whitespace(tmp_path, note):
    with client_for(tmp_path) as client:
        trial = client.post("/dev-tests/trials", json=payload()).json()
        client.put(f"/dev-tests/trials/{trial['trial_id']}/review", json={"valid": False, "notes": note, "reviewer": "staff"})
        rows = list(csv.DictReader(io.StringIO(client.get("/dev-tests/export?format=csv").text.lstrip("\ufeff"))))
        assert rows[0]["notes"] == "'" + note
