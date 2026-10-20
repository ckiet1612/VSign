from __future__ import annotations

from datetime import timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.evaluation_db import EvaluationRun, EvaluationWorkerState
from app.model_registry import ModelRegistry, iso
from app.model_registry_db import RegisteredModel
from app.platform_db import AuditEvent, utc_now
from app.workspace_data import WorkspaceData
from app.workspace_data_db import DatasetSnapshot, DatasetVersion

LEASE_SECONDS = 45
MAX_SAMPLES = 1000


def alive(heartbeat):
    return heartbeat is not None and heartbeat.replace(tzinfo=timezone.utc) > utc_now() - timedelta(seconds=LEASE_SECONDS)


def evaluation_audit(session, run, event, actor=None, outcome='success'):
    session.add(AuditEvent(id=str(uuid4()), workspace_id=run.workspace_id, event_type='evaluation.' + event,
        actor_type='user' if actor else 'service', actor_id=actor, resource_type='evaluation_run',
        resource_id=run.id, outcome=outcome, metadata_json={'source':'server', 'model_id':run.model_id,
            'dataset_version':run.frozen_json['dataset_version'], 'snapshot_id':run.snapshot_id}))


def recover_expired(session, workspace_id):
    runs = session.scalars(select(EvaluationRun).where(EvaluationRun.workspace_id == workspace_id,
        EvaluationRun.status == 'running')).all()
    for run in runs:
        if not alive(run.heartbeat_at):
            run.status, run.error, run.finished_at = 'failed', 'Worker bị gián đoạn; hãy tạo lượt đánh giá mới.', utc_now()
            evaluation_audit(session, run, 'failed', outcome='failure')


class Evaluations:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings
        self.data, self.registry = WorkspaceData(database, settings), ModelRegistry(database, settings)

    def create(self, actor, payload):
        from app.evaluation_evidence import provenance
        with self.data.write(actor) as session:
            existing = session.get(EvaluationRun, str(payload.request_id))
            if existing:
                if (existing.workspace_id != actor.workspace.id or existing.requested_by != actor.user.id or
                    existing.model_id != str(payload.model_id) or existing.snapshot_id != str(payload.snapshot_id)):
                    raise HTTPException(409, 'Mã yêu cầu đã được dùng cho nội dung khác')
                return
            model = self.registry.get_model(session, str(payload.model_id))
            snapshot = self.data.get(session, DatasetSnapshot, actor, payload.snapshot_id)
            target = self.registry.target(session, required=False)
            if target is None:
                raise HTTPException(409, 'Chưa có model production để so sánh')
            baseline = self.registry.get_model(session, target.active_model_id)
            candidate_manifest, labels = self.registry.verify(model)
            baseline_manifest, baseline_labels = self.registry.verify(baseline)
            if (labels != baseline_labels or candidate_manifest.backend != baseline_manifest.backend or
                candidate_manifest.preprocessing_version != baseline_manifest.preprocessing_version):
                raise HTTPException(409, 'Hai model phải cùng bộ nhãn, backend và cách xử lý đầu vào')
            if not 1 <= snapshot.sample_count <= MAX_SAMPLES:
                raise HTTPException(409, 'Snapshot cần từ 1 đến 1000 mẫu')
            manifest = self.data.read_manifest(actor, snapshot)
            signs = {entry['name'] for entry in manifest['labels'] if entry['kind'] == 'sign'}
            if not signs or not signs.issubset(set(labels)) or 'Không ký hiệu' in signs:
                raise HTTPException(409, 'Bộ nhãn snapshot không tương thích với model')
            recover_expired(session, actor.workspace.id)
            if session.scalar(select(EvaluationRun.id).where(EvaluationRun.workspace_id == actor.workspace.id,
                    EvaluationRun.status.in_(['queued','running'])).limit(1)):
                raise HTTPException(409, 'Workspace đang có lượt đánh giá chưa kết thúc')
            frozen = dict(candidate=model.manifest_json, baseline=baseline.manifest_json,
                snapshot_sha256=snapshot.sha256, dataset_version=snapshot.dataset_version_id,
                label_version=snapshot.label_version_id, sample_count=snapshot.sample_count,
                provenance_sha256=None)
            evidence, digest = provenance(self.settings, actor.workspace.id, snapshot.sha256,
                                          manifest, frozen, expected_hash=None)
            if evidence:
                frozen['provenance_sha256'] = digest
            run = EvaluationRun(id=str(payload.request_id), workspace_id=actor.workspace.id,
                model_id=model.id, baseline_model_id=baseline.id, snapshot_id=snapshot.id,
                requested_by=actor.user.id, status='queued', frozen_json=frozen)
            session.add(run)
            evaluation_audit(session, run, 'requested', actor.user.id)

    def cancel(self, actor, identity):
        with self.data.write(actor) as session:
            run = self.data.get(session, EvaluationRun, actor, identity)
            if run.status == 'cancelled':
                return
            if run.status not in ('queued', 'running'):
                raise HTTPException(409, 'Lượt đánh giá đã kết thúc')
            run.status, run.finished_at = 'cancelled', utc_now()
            evaluation_audit(session, run, 'cancelled', actor.user.id)

    def overview(self, actor):
        with self.database.session() as session:
            target = self.registry.target(session, required=False)
            active = target.active_model_id if target else None
            def scoped(table):
                return select(table).where(table.workspace_id == actor.workspace.id)
            models = session.scalars(scoped(RegisteredModel).order_by(RegisteredModel.created_at.desc())).all()
            datasets = {row.id:row for row in session.scalars(scoped(DatasetVersion)).all()}
            snapshots = session.scalars(scoped(DatasetSnapshot).order_by(DatasetSnapshot.created_at.desc())).all()
            workers = session.scalars(scoped(EvaluationWorkerState)).all()
            runs = session.scalars(scoped(EvaluationRun).order_by(EvaluationRun.created_at.desc(),
                EvaluationRun.id.desc()).limit(50)).all()
            return dict(api_version='1', workspace_id=actor.workspace.id,
                permissions=dict(create=actor.can('evaluation:create'), cancel=actor.can('evaluation:cancel')),
                active_model_id=active, workers={row.backend:alive(row.heartbeat_at) for row in workers},
                models=[dict(id=row.id, model_version=row.model_version, backend=row.manifest_json['backend'],
                             active=row.id == active) for row in models],
                snapshots=[dict(id=row.id, dataset_version=row.dataset_version_id,
                    dataset_name=datasets[row.dataset_version_id].name, sample_count=row.sample_count,
                    sha256=row.sha256) for row in snapshots],
                runs=[dict(id=row.id, model_id=row.model_id, baseline_model_id=row.baseline_model_id,
                    model_version=row.frozen_json['candidate']['model_version'],
                    baseline_model_version=row.frozen_json['baseline']['model_version'],
                    snapshot_id=row.snapshot_id, dataset_version=row.frozen_json['dataset_version'],
                    snapshot_sha256=row.frozen_json['snapshot_sha256'], backend=row.frozen_json['candidate']['backend'],
                    sample_count=row.frozen_json['sample_count'], status=row.status, progress=row.progress,
                    requested_by=row.requested_by, created_at=iso(row.created_at), started_at=iso(row.started_at),
                    finished_at=iso(row.finished_at), error=row.error, report=row.report_json,
                    gate=row.gate_json, baseline_current=row.baseline_model_id == active) for row in runs])
