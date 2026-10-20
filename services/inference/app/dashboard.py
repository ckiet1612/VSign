"""Read-only, workspace-scoped dashboard aggregates. No job recovery or writes."""
from collections import defaultdict
from datetime import timedelta, timezone

from sqlalchemy import func, select

from app.evaluation_db import EvaluationRun, EvaluationWorkerState
from app.integration_db import IntegrationWorkerState
from app.model_registry_db import DeploymentTarget, RegisteredModel
from app.platform_db import AuditEvent, utc_now
from app.workspace_data_db import DataSample, DatasetVersion, LabelVersion


def dashboard_snapshot(database, workspace_id: str, days: int):
    now = utc_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)

    def aware(value):
        return value.replace(tzinfo=value.tzinfo or timezone.utc)

    def online(heartbeat, ttl=45):
        return heartbeat is not None and aware(heartbeat) > now - timedelta(seconds=ttl)

    with database.session() as session:
        # Python's legacy SQLite driver does not begin transactions for SELECT.
        # Pin all aggregates to one read snapshot while collection keeps writing.
        if database.engine.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN")
        else:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})

        def count(model, *conditions):
            return session.scalar(select(func.count()).select_from(model).where(model.workspace_id == workspace_id, *conditions)) or 0

        def period(model, timestamp):
            return count(model, timestamp >= start, timestamp <= now)

        daily = dict((str(day), total) for day, total in session.execute(
            select(func.date(DataSample.created_at), func.count()).where(DataSample.workspace_id == workspace_id,
                DataSample.created_at >= start, DataSample.created_at <= now).group_by(func.date(DataSample.created_at))))
        counts = dict(session.execute(select(DataSample.expected_label, func.count()).where(
            DataSample.workspace_id == workspace_id).group_by(DataSample.expected_label)).all())
        targets = defaultdict(int)
        for quota, entries in session.execute(select(DatasetVersion.quota_per_label, LabelVersion.entries_json).join(
            LabelVersion, (LabelVersion.id == DatasetVersion.label_version_id) &
            (LabelVersion.workspace_id == DatasetVersion.workspace_id)).where(DatasetVersion.workspace_id == workspace_id)):
            for entry in entries:
                targets[entry["name"]] += quota
        labels = sorted(set(targets) | set(counts), key=lambda label: (-counts.get(label, 0), label))
        deployments = session.scalars(select(DeploymentTarget).where(DeploymentTarget.workspace_id == workspace_id)).all()
        evaluators = session.scalars(select(EvaluationWorkerState).where(EvaluationWorkerState.workspace_id == workspace_id)).all()
        integration = session.get(IntegrationWorkerState, workspace_id)
        # Deployment readiness requires both a live lease and the observed pointer.
        deploy_status = "not_configured" if not deployments else "online" if all(
            target.worker_id and online(target.heartbeat_at, 30) and target.observed_model_id == target.active_model_id
            for target in deployments) else "offline"
        events = session.scalars(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id,
            AuditEvent.occurred_at >= start, AuditEvent.occurred_at <= now)
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(8)).all()
        evaluations = session.execute(select(EvaluationRun, RegisteredModel.model_version).join(
            RegisteredModel, (RegisteredModel.id == EvaluationRun.model_id) &
            (RegisteredModel.workspace_id == EvaluationRun.workspace_id)).where(EvaluationRun.workspace_id == workspace_id,
            EvaluationRun.created_at >= start, EvaluationRun.created_at <= now)
            .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc()).limit(5)).all()
        return {
            "workspace_id": workspace_id, "generated_at": now, "days": days, "start_date": start.date(),
            "totals": {"samples": count(DataSample), "datasets_draft": count(DatasetVersion, DatasetVersion.status == "draft"),
                "datasets_sealed": count(DatasetVersion, DatasetVersion.status == "sealed"),
                "models": count(RegisteredModel), "evaluations": count(EvaluationRun)},
            "period": {"samples": period(DataSample, DataSample.created_at), "evaluations": period(EvaluationRun, EvaluationRun.created_at),
                "events": period(AuditEvent, AuditEvent.occurred_at)},
            "daily_samples": [{"date": (start + timedelta(days=offset)).date(),
                "count": daily.get((start + timedelta(days=offset)).date().isoformat(), 0)} for offset in range(days)],
            "label_progress": [{"label": label, "count": counts.get(label, 0), "target": targets[label]} for label in labels],
            "workers": {"deployment": deploy_status,
                "evaluation": "not_configured" if not evaluators else "online" if any(online(row.heartbeat_at) for row in evaluators) else "offline",
                "integration": "not_configured" if integration is None else "online" if online(integration.heartbeat_at) else "offline"},
            "recent_activity": [{"id": row.id, "event_type": row.event_type, "outcome": row.outcome,
                "occurred_at": aware(row.occurred_at)} for row in events],
            "recent_evaluations": [{"id": row.id, "model_version": version, "status": row.status, "progress": row.progress,
                "created_at": aware(row.created_at)} for row, version in evaluations],
        }
