from datetime import timedelta
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.main import create_app
from app.platform_db import AuditEvent, Base, Workspace, utc_now
from app.workspace_data_db import DataSample, DataSession, DatasetVersion, LabelVersion
from test_local_admin import local_settings
from test_system_admin import system_settings


def seed(app):
    now = utc_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    with app.state.platform_database.session() as session:
        session.add(Workspace(id="other", name="Hidden", environment="development"))
        for workspace in ("local", "other"):
            label, dataset, capture = (str(uuid4()) for _ in range(3))
            session.add(LabelVersion(id=label, workspace_id=workspace, name="Sales", parent_id=None,
                entries_json=[{"id": str(uuid4()), "name": "Cho", "kind": "sign"},
                              {"id": str(uuid4()), "name": "Mua", "kind": "sign"}],
                request_hash="a" * 64, created_by="fixture"))
            session.flush()
            session.add(DatasetVersion(id=dataset, workspace_id=workspace, name="Draft", label_version_id=label,
                quota_per_label=5, status="draft", request_hash="a" * 64, created_by="fixture"))
            session.flush()
            session.add(DataSession(id=capture, workspace_id=workspace, dataset_version_id=dataset,
                state="running", created_by="fixture", request_hash="a" * 64))
            session.flush()
            for timestamp in (start, start - timedelta(microseconds=1), now - timedelta(minutes=1), now + timedelta(days=1)):
                session.add(DataSample(id=str(uuid4()), workspace_id=workspace, dataset_version_id=dataset,
                    collection_session_id=capture, label_id=label, expected_label="Cho", hand="right",
                    relative_path="private-file", video_sha256="a" * 64, metadata_sha256="a" * 64,
                    request_hash="a" * 64, created_at=timestamp))
            session.add(AuditEvent(id=str(uuid4()), workspace_id=workspace, event_type="fixture.event",
                actor_type="user", actor_id="fixture", outcome="success", occurred_at=now,
                metadata_json={"secret": "do-not-return"}))
        session.commit()


def test_dashboard_zero_is_real_and_get_does_not_mutate(monkeypatch, tmp_path):
    app = create_app(system_settings(monkeypatch, tmp_path))
    with TestClient(app) as client:
        database = app.state.platform_database
        with database.engine.connect() as connection:
            before = {table.name: connection.execute(select(table)).all() for table in Base.metadata.sorted_tables}
        response = client.get("/api/v1/workspace/dashboard?days=30")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["totals"] == {"samples": 0, "datasets_draft": 0, "datasets_sealed": 0, "models": 0, "evaluations": 0}
        assert len(body["daily_samples"]) == 30
        assert all(row["count"] == 0 for row in body["daily_samples"])
        assert body["label_progress"] == []
        assert body["workers"]["deployment"] == "not_configured"
        with database.engine.connect() as connection:
            assert {table.name: connection.execute(select(table)).all() for table in Base.metadata.sorted_tables} == before


def test_dashboard_scopes_period_bounds_and_catalog_quotas(monkeypatch, tmp_path):
    app = create_app(system_settings(monkeypatch, tmp_path))
    with TestClient(app) as client:
        seed(app)
        response = client.get("/api/v1/workspace/dashboard?days=7")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["workspace_id"] == "local"
        assert body["timezone"] == "UTC"
        assert body["totals"]["samples"] == 4
        assert body["totals"]["datasets_draft"] == 1
        assert body["period"]["samples"] == 2
        assert sum(row["count"] for row in body["daily_samples"]) == 2
        assert body["daily_samples"][0]["count"] == 1
        assert body["label_progress"] == [{"label": "Cho", "count": 4, "target": 5}, {"label": "Mua", "count": 0, "target": 5}]
        assert len(body["recent_activity"]) == 1
        assert "do-not-return" not in response.text
        assert "private-file" not in response.text
        assert "Hidden" not in response.text


@pytest.mark.parametrize("days", [0, 8, 91, "bad"])
def test_dashboard_rejects_unsupported_ranges(monkeypatch, tmp_path, days):
    with TestClient(create_app(system_settings(monkeypatch, tmp_path))) as client:
        assert client.get(f"/api/v1/workspace/dashboard?days={days}").status_code == 422


def test_business_admin_does_not_inherit_system_dashboard(monkeypatch, tmp_path):
    with TestClient(create_app(local_settings(monkeypatch, tmp_path))) as client:
        assert client.get("/api/v1/workspace/dashboard").status_code == 403


def test_dashboard_reports_workers_and_evaluations_without_recovering_expired_jobs(monkeypatch, tmp_path):
    from app.evaluation_db import EvaluationRun, EvaluationWorkerState
    from app.integration_db import IntegrationWorkerState
    from app.model_registry_db import DeploymentTarget
    from test_workspace_evaluations import prepare_evaluation
    settings = replace(system_settings(monkeypatch, tmp_path), collection_enabled=True)
    app = create_app(settings)
    with TestClient(app) as client:
        payload = prepare_evaluation(client, settings, tmp_path)
        response = client.post("/api/v1/workspace/evaluations", json=payload)
        assert response.status_code == 201, response.text
        with app.state.platform_database.session() as session:
            run = session.get(EvaluationRun, payload["request_id"])
            run.status, run.heartbeat_at, run.progress = "running", utc_now() - timedelta(hours=1), 25
            target = session.scalar(select(DeploymentTarget))
            target.worker_id, target.heartbeat_at = "fixture", utc_now()
            session.add(EvaluationWorkerState(workspace_id="local", backend="onnx", worker_id="fixture", heartbeat_at=utc_now() - timedelta(hours=1)))
            session.add(IntegrationWorkerState(workspace_id="local", heartbeat_at=utc_now()))
            session.commit()
        body = client.get("/api/v1/workspace/dashboard").json()
        assert body["totals"] == {"samples": 2, "datasets_draft": 0, "datasets_sealed": 1, "models": 2, "evaluations": 1}
        assert body["period"]["evaluations"] == 1
        assert body["workers"] == {"deployment": "online", "evaluation": "offline", "integration": "online"}
        assert body["recent_evaluations"][0]["status"] == "running"
        assert body["recent_evaluations"][0]["progress"] == 25
        with app.state.platform_database.session() as session:
            assert session.get(EvaluationRun, payload["request_id"]).status == "running"
            target = session.scalar(select(DeploymentTarget))
            target.observed_model_id = None
            session.commit()
        assert client.get("/api/v1/workspace/dashboard").json()["workers"]["deployment"] == "offline"


def test_dashboard_requires_session_and_machine_keys_never_inherit_it(monkeypatch, tmp_path):
    settings = replace(system_settings(monkeypatch, tmp_path), local_admin_enabled=False)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/workspace/dashboard").status_code == 401
    from test_workspace_integrations import key_payload
    with TestClient(create_app(system_settings(monkeypatch, tmp_path))) as client:
        secret = client.post("/api/v1/workspace/integrations/keys", json=key_payload()).json()["secret"]
        assert client.get("/api/v1/workspace/dashboard", headers={"Authorization": "Bearer " + secret}).status_code == 403


def test_dashboard_uses_one_read_snapshot_during_concurrent_collection(monkeypatch, tmp_path):
    app = create_app(system_settings(monkeypatch, tmp_path))
    with TestClient(app) as client:
        seed(app)
        engine = app.state.platform_database.engine
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            sample = dict(connection.execute(select(DataSample.__table__).where(DataSample.workspace_id == "local")).mappings().first())
        sample.update(id=str(uuid4()), created_at=utc_now() - timedelta(minutes=1))
        inserted = False

        def collect_after_chart_read(_conn, _cursor, statement, _params, _context, _many):
            nonlocal inserted
            if not inserted and "SELECT date(data_samples.created_at)" in statement:
                inserted = True
                with engine.begin() as writer:
                    writer.execute(DataSample.__table__.insert().values(**sample))

        event.listen(engine, "after_cursor_execute", collect_after_chart_read)
        try:
            response = client.get("/api/v1/workspace/dashboard?days=7")
        finally:
            event.remove(engine, "after_cursor_execute", collect_after_chart_read)
        assert inserted
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["totals"]["samples"] == 4
        assert body["period"]["samples"] == sum(row["count"] for row in body["daily_samples"]) == 2
        assert body["label_progress"][0]["count"] == 4
