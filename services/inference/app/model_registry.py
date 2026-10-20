from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.model_gate import POLICY_VERSION, evaluate_gate
from app.model_registry_db import DeploymentJob, DeploymentTarget, ModelValidation, RegisteredModel
from app.platform_auth import Principal
from app.platform_db import AuditEvent, Database, utc_now
from app.registry_artifacts import RegistryManifest, checked_local_path, read_json, sha256_file, verify_artifacts
from contracts.model_lifecycle_lock import lifecycle_lock

WORKER_TTL = 30


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def worker_online(target: DeploymentTarget) -> bool:
    return bool(target.worker_id and target.heartbeat_at and
                target.heartbeat_at.replace(tzinfo=timezone.utc) > utc_now() - timedelta(seconds=WORKER_TTL))


def audit(session, workspace_id, event_type, actor_id, resource_id, metadata=None, outcome="success"):
    session.add(AuditEvent(id=str(uuid4()), workspace_id=workspace_id, event_type=event_type,
                          actor_type="user" if actor_id else "service", actor_id=actor_id,
                          resource_type="deployment" if event_type.startswith("deployment.") else "model",
                          resource_id=resource_id, outcome=outcome, metadata_json={"source":"server", **(metadata or {})}))


class ModelRegistry:
    def __init__(self, database: Database, settings: Settings):
        self.database, self.settings = database, settings
        self.workspace_id = settings.workspace_id
        self.target_key = (settings.workspace_id, settings.model_deployment_target)

    def get_model(self, session, model_id: str) -> RegisteredModel:
        model = session.get(RegisteredModel, model_id)
        if model is None or model.workspace_id != self.workspace_id:
            raise HTTPException(404, "Không tìm thấy mô hình")
        return model

    def target(self, session, required=True) -> DeploymentTarget | None:
        target = session.get(DeploymentTarget, self.target_key)
        if target is None and required:
            raise HTTPException(503, "Runtime triển khai chưa được kết nối")
        return target

    def verify(self, model: RegisteredModel):
        manifest = RegistryManifest.model_validate(model.manifest_json)
        artifact = checked_local_path(model.artifact_path, self.settings.model_registry_roots)
        labels = checked_local_path(model.labels_path, self.settings.model_registry_roots)
        return manifest, verify_artifacts(manifest, artifact, labels)

    def latest_validation(self, session, model_id):
        return session.scalar(select(ModelValidation).where(ModelValidation.workspace_id == self.workspace_id,
            ModelValidation.model_id == model_id).order_by(ModelValidation.created_at.desc(), ModelValidation.id.desc()).limit(1))

    def require_gate(self, session, model, target):
        validation = self.latest_validation(session, model.id)
        if (validation is None or not validation.result_json["passed"] or validation.policy_version != POLICY_VERSION
                or validation.baseline_model_id != target.active_model_id or model.approved_validation_id != validation.id):
            raise HTTPException(409, "Cần kiểm định đạt với baseline hiện tại và phê duyệt riêng trước khi deploy")
        from app.evaluation_evidence import require_evaluation_evidence
        require_evaluation_evidence(self,session,validation)

    def snapshot(self, actor: Principal) -> dict:
        with self.database.session() as session:
            if session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN")
            target = self.target(session, required=False)
            models = session.scalars(select(RegisteredModel).where(RegisteredModel.workspace_id == self.workspace_id)
                                     .order_by(RegisteredModel.created_at.desc(), RegisteredModel.id.desc())).all()
            rows = []
            for model in models:
                manifest = model.manifest_json
                validation = self.latest_validation(session, model.id)
                valid = validation is not None and validation.result_json["passed"] and validation.policy_version == POLICY_VERSION
                approved = bool(valid and model.approved_validation_id == validation.id)
                status = "approved" if approved else "validated" if valid else model.origin
                if target and target.active_model_id == model.id:
                    status = "active"
                rows.append(dict(id=model.id, model_version=model.model_version, backend=manifest["backend"],
                    artifact_sha256=manifest["artifact_sha256"], labels_sha256=manifest["labels_sha256"],
                    labels_count=model.labels_count, source_run_id=manifest["source_run_id"], created_at=iso(model.created_at),
                    origin=model.origin, status=status, approved_validation_id=model.approved_validation_id,
                    approved_by=model.approved_by, approved_at=iso(model.approved_at),
                    validation=None if validation is None else dict(id=validation.id, baseline_model_id=validation.baseline_model_id,
                        report_sha256=validation.report_sha256, created_at=iso(validation.created_at), **validation.result_json)))
            jobs = session.scalars(select(DeploymentJob).where(DeploymentJob.workspace_id == self.workspace_id,
                DeploymentJob.target_id == self.settings.model_deployment_target)
                .order_by(DeploymentJob.created_at.desc(), DeploymentJob.id.desc()).limit(30)).all()
            return dict(api_version="1", workspace_id=self.workspace_id, models=rows,
                permissions={key:actor.can(f"models:{key}") for key in ("register", "validate", "approve", "deploy")},
                target=None if target is None else dict(target_id=target.target_id,runtime_url=target.runtime_url,backend=target.backend,
                    active_model_id=target.active_model_id,previous_model_id=target.previous_model_id,revision=target.revision,
                    pending_job_id=target.pending_job_id,worker_online=worker_online(target),observed_model_id=target.observed_model_id),
                deployments=[dict(id=job.id,operation=job.operation,from_model_id=job.from_model_id,to_model_id=job.to_model_id,
                    expected_revision=job.expected_revision,status=job.status,requested_by=job.requested_by,
                    created_at=iso(job.created_at),finished_at=iso(job.finished_at),error=job.error) for job in jobs])

    def register(self, actor: Principal, payload):
        with lifecycle_lock(self.settings.database_url):
            return self._register(actor,payload)

    def _register(self, actor: Principal, payload):
        manifest_path = checked_local_path(payload.manifest_path, self.settings.model_registry_roots)
        manifest = RegistryManifest.model_validate(read_json(manifest_path, 16384))
        if manifest.status != "candidate":
            raise ValueError("Chỉ đăng ký manifest có status=candidate")
        artifact = checked_local_path(payload.artifact_path, self.settings.model_registry_roots)
        labels = checked_local_path(payload.labels_path, self.settings.model_registry_roots)
        ordered_labels = verify_artifacts(manifest, artifact, labels)
        with self.database.session() as session:
            existing = session.scalar(select(RegisteredModel).where(RegisteredModel.workspace_id == self.workspace_id,
                                                               RegisteredModel.model_version == manifest.model_version))
            if existing is not None:
                if (existing.manifest_json != manifest.model_dump() or existing.artifact_path != str(artifact)
                        or existing.labels_path != str(labels)):
                    raise HTTPException(409, "Phiên bản đã được đăng ký với artifact bất biến khác")
                return
            model_id = str(uuid4())
            session.add(RegisteredModel(id=model_id,workspace_id=self.workspace_id,model_version=manifest.model_version,
                artifact_path=str(artifact),labels_path=str(labels),labels_count=len(ordered_labels),manifest_json=manifest.model_dump(),
                origin="candidate",created_by=actor.user.id))
            audit(session,self.workspace_id,"model.registered",actor.user.id,model_id,{"model_version":manifest.model_version})
            try:
                session.commit()
            except IntegrityError as exc:
                raise HTTPException(409, "Phiên bản mô hình vừa được đăng ký; hãy làm mới") from exc

    def validate(self, actor: Principal, model_id: str, report_path: str):
        path = checked_local_path(report_path, self.settings.model_evaluation_roots)
        report = read_json(path)
        if not isinstance(report, dict):
            raise ValueError("Báo cáo đánh giá phải là object JSON")
        report_hash = sha256_file(path)
        with self.database.session() as session:
            if session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            model = self.get_model(session,model_id)
            target = self.target(session)
            if model.origin != "candidate" or model.id == target.active_model_id:
                raise HTTPException(409, "Chỉ kiểm định candidate chưa active")
            baseline = self.get_model(session,target.active_model_id)
            candidate_manifest, labels = self.verify(model)
            baseline_manifest, _ = self.verify(baseline)
            result = evaluate_gate(report,candidate_manifest,baseline_manifest,labels)
            result['checks'].append(dict(name='computed_evaluation', passed=False,
                detail='Báo cáo nhập chỉ để tham khảo; cần lượt đánh giá do worker tính trên snapshot đã xác minh.'))
            result['passed'] = False
            validation = ModelValidation(id=str(uuid4()),workspace_id=self.workspace_id,model_id=model.id,
                baseline_model_id=baseline.id,report_sha256=report_hash,policy_version=POLICY_VERSION,
                result_json=result,created_by=actor.user.id)
            session.add(validation)
            model.approved_validation_id = model.approved_by = model.approved_at = None
            audit(session,self.workspace_id,"model.validation_passed" if result["passed"] else "model.validation_failed",
                  actor.user.id,model.id,{"model_id":model.id,"baseline_model_id":baseline.id},
                  outcome="success" if result["passed"] else "failure")
            session.commit()

    def approve(self, actor: Principal, model_id: str, validation_id: str):
        with self.database.session() as session:
            if session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            model = self.get_model(session,model_id)
            target = self.target(session,required=False)
            validation = self.latest_validation(session,model.id)
            if (target is None or validation is None or validation.id != validation_id or not validation.result_json["passed"]
                    or validation.policy_version != POLICY_VERSION or validation.baseline_model_id != target.active_model_id):
                raise HTTPException(409, "Cần kiểm định đạt mới nhất với baseline hiện tại")
            from app.evaluation_evidence import require_evaluation_evidence
            require_evaluation_evidence(self,session,validation)
            self.verify(model)
            self.verify(self.get_model(session,target.active_model_id))
            model.approved_validation_id, model.approved_by, model.approved_at = validation.id,actor.user.id,utc_now()
            audit(session,self.workspace_id,"model.approved",actor.user.id,model.id,{"model_id":model.id,"validation_id":validation.id})
            session.commit()

    def enqueue(self, actor: Principal, request_id: str, expected_revision: int, model_id: str | None):
        operation = "deploy" if model_id is not None else "rollback"
        with self.database.session() as session:
            if session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            existing = session.get(DeploymentJob, request_id)
            if existing is not None:
                if (existing.workspace_id != self.workspace_id or existing.target_id != self.target_key[1]
                    or existing.requested_by != actor.user.id or existing.operation != operation
                    or existing.expected_revision != expected_revision or (model_id is not None and existing.to_model_id != model_id)):
                    raise HTTPException(409, "Request ID đã được dùng cho yêu cầu khác")
                return
            target = self.target(session)
            if not worker_online(target) or target.observed_model_id != target.active_model_id:
                raise HTTPException(503, "Runtime triển khai ngoại tuyến hoặc chưa xác nhận active model")
            if target.pending_job_id or target.revision != expected_revision:
                raise HTTPException(409, "Active pointer đã thay đổi hoặc đang có yêu cầu triển khai")
            destination = model_id or target.previous_model_id
            if not destination or destination == target.active_model_id:
                raise HTTPException(409, "Không có mô hình trước đó để rollback hoặc model đã active")
            model = self.get_model(session,destination)
            if model.manifest_json["backend"] != target.backend:
                raise HTTPException(409, "Candidate cần export và kiểm định đúng backend của runtime")
            if operation == "deploy":
                self.require_gate(session,model,target)
            self.verify(model)
            changed = session.execute(update(DeploymentTarget).where(
                DeploymentTarget.workspace_id == self.workspace_id,DeploymentTarget.target_id == self.target_key[1],
                DeploymentTarget.revision == expected_revision,DeploymentTarget.pending_job_id.is_(None),
                DeploymentTarget.worker_id == target.worker_id).values(pending_job_id=request_id)).rowcount
            if changed != 1:
                raise HTTPException(409, "Có yêu cầu khác vừa cập nhật active pointer")
            session.add(DeploymentJob(id=request_id,workspace_id=self.workspace_id,target_id=target.target_id,
                operation=operation,from_model_id=target.active_model_id,to_model_id=model.id,
                expected_revision=expected_revision,status="queued",requested_by=actor.user.id))
            audit(session,self.workspace_id,f"deployment.{operation}_requested",actor.user.id,request_id,
                  {"previous_model_id":target.active_model_id,"new_model_id":model.id})
            session.commit()
