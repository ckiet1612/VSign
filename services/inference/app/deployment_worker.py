from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, update
from PIL import Image

from app.backends.base import DecodedFrame
from app.models import PredictionCandidate, PredictionMessage, PredictionStatus
from app.model_registry import ModelRegistry, WORKER_TTL, audit, worker_online
from app.model_registry_db import DeploymentJob, DeploymentTarget, RegisteredModel
from app.model_manifest import ModelManifest, labels_digest
from app.platform_auth import ROLE_PERMISSIONS
from app.platform_db import Membership, User, utc_now
from app.registry_artifacts import PREPROCESSING_VERSION, RegistryManifest, artifact_digest, checked_local_path, verify_artifacts
from contracts.model_lifecycle_lock import lifecycle_lock

logger = logging.getLogger("vsign.deployment")


class DeploymentWorker:
    def __init__(self, app, registry: ModelRegistry, factory):
        self.app, self.registry, self.factory = app, registry, factory
        self.settings = registry.settings
        self.worker_id = str(uuid4())
        self.tasks = []
        self.active_model_id = None
        self.activation_uncertain = False

    def _owned_target(self, session):
        target = self.registry.target(session)
        if target.worker_id != self.worker_id or not worker_online(target):
            raise RuntimeError("Deployment worker lease lost")
        return target

    def _initialize(self):
        with self.registry.database.session() as session:
            needs_bootstrap = self.registry.target(session, required=False) is None
        if needs_bootstrap:
            with lifecycle_lock(self.settings.database_url):
                return self._initialize_target()
        return self._initialize_target()

    def _initialize_target(self):
        registry, settings = self.registry, self.settings
        if settings.inference_backend not in {"coreml", "onnx", "pytorch"}:
            raise RuntimeError("Managed runtime requires a real supported backend")
        with registry.database.session() as session:
            target = registry.target(session, required=False)
            if target is None:
                configured_artifact = getattr(settings, f"{settings.inference_backend}_model_path")
                if not configured_artifact or not settings.label_map_path or not settings.labels_verified:
                    raise RuntimeError("Managed baseline requires verified artifact and label paths")
                artifact = checked_local_path(configured_artifact,settings.model_registry_roots)
                labels_path = checked_local_path(settings.label_map_path,settings.model_registry_roots)
                backend = self.app.state.backend
                if backend.name != settings.inference_backend or backend.model_version != settings.model_version:
                    raise RuntimeError("Configured baseline does not match serving backend")
                manifest = RegistryManifest(model_version=settings.model_version,backend=backend.name,
                    artifact_sha256=artifact_digest(artifact,backend.name),labels_sha256=labels_digest(backend.labels),
                    protocol_version="1.0",frame_count=16,frame_size=224,preprocessing_version=PREPROCESSING_VERSION,
                    confidence_threshold=settings.confidence_threshold,margin_threshold=settings.margin_threshold,
                    source_run_id="observed-baseline",status="production")
                verify_artifacts(manifest,artifact,labels_path)
                baseline = session.scalar(select(RegisteredModel).where(RegisteredModel.workspace_id==registry.workspace_id,
                    RegisteredModel.model_version==settings.model_version))
                if baseline is None:
                    baseline = RegisteredModel(id=str(uuid4()),workspace_id=registry.workspace_id,model_version=settings.model_version,
                        artifact_path=str(artifact),labels_path=str(labels_path),labels_count=len(backend.labels),
                        manifest_json=manifest.model_dump(),origin="baseline",created_by=None)
                    session.add(baseline)
                    session.flush()
                elif (baseline.artifact_path != str(artifact) or baseline.manifest_json["artifact_sha256"] != manifest.artifact_sha256
                      or baseline.manifest_json["labels_sha256"] != manifest.labels_sha256):
                    raise RuntimeError("Observed baseline conflicts with immutable registry version")
                target = DeploymentTarget(workspace_id=registry.workspace_id,target_id=registry.target_key[1],
                    runtime_url=settings.model_deployment_runtime_url,backend=backend.name,
                    active_model_id=baseline.id,revision=0,worker_id=self.worker_id,heartbeat_at=utc_now())
                session.add(target)
                audit(session,registry.workspace_id,"model.baseline_observed",None,baseline.id,{"model_version":settings.model_version})
            else:
                if worker_online(target):
                    raise RuntimeError("Another deployment worker already owns this target")
                old_worker = target.worker_id
                changed = session.execute(update(DeploymentTarget).where(
                    DeploymentTarget.workspace_id==registry.workspace_id,DeploymentTarget.target_id==registry.target_key[1],
                    DeploymentTarget.worker_id==old_worker,
                    (DeploymentTarget.heartbeat_at.is_(None)) | (DeploymentTarget.heartbeat_at < utc_now()-timedelta(seconds=WORKER_TTL)))
                    .values(worker_id=self.worker_id,heartbeat_at=utc_now(),observed_model_id=None)
                    .execution_options(synchronize_session=False)).rowcount
                if changed != 1:
                    raise RuntimeError("Deployment lease was claimed concurrently")
                session.refresh(target)
                if target.backend != settings.inference_backend or target.runtime_url != settings.model_deployment_runtime_url:
                    raise RuntimeError("Runtime target configuration changed; explicit migration is required")
                if target.pending_job_id:
                    job = session.get(DeploymentJob,target.pending_job_id)
                    if job and job.status == "loading":
                        job.status,job.error,job.finished_at="failed","Runtime đã dừng trong khi nạp; active pointer được giữ nguyên.",utc_now()
                        audit(session,registry.workspace_id,"deployment.failed",job.requested_by,job.id,{"reason":"worker_interrupted"},"failure")
                        target.pending_job_id=None
            active = registry.get_model(session,target.active_model_id)
            session.commit()
            return active

    def _load(self, model):
        manifest, labels = self.registry.verify(model)
        if manifest.backend != self.settings.inference_backend:
            raise RuntimeError("Unsupported deployment backend for this runtime")
        settings = replace(self.settings,model_version=manifest.model_version,model_manifest_path=None,labels_verified=True,
            label_map_path=Path(model.labels_path),confidence_threshold=manifest.confidence_threshold,margin_threshold=manifest.margin_threshold,
            **{f"{manifest.backend}_model_path":Path(model.artifact_path)})
        # Initial app construction may predate verified registration or restoration.
        backend=self.factory(settings)
        if (backend.name != manifest.backend or backend.model_version != manifest.model_version
                or labels_digest(backend.labels) != manifest.labels_sha256 or backend.is_mock or backend.candidate_labels_unverified
                or backend.confidence_threshold != manifest.confidence_threshold
                or backend.margin_threshold != manifest.margin_threshold):
            raise RuntimeError("Loaded backend identity is not verified")
        image=Image.new("RGB",(224,224))
        frames=[DecodedFrame(image=image,encoded_bytes=b"") for _ in range(16)]
        try:
            result=backend.predict(frames,0)
            if result.status in {PredictionStatus.ERROR,PredictionStatus.BUSY}:
                raise RuntimeError("Backend warm-up failed")
            if ((result.label is not None and result.label not in labels)
                    or any(item.label not in labels for item in result.top_k)):
                raise RuntimeError("Backend warm-up returned unknown labels")
            PredictionMessage(sequence=0,model_version=manifest.model_version,status=result.status,
                label=result.label,confidence=result.confidence,
                top_k=[PredictionCandidate(label=item.label,confidence=item.confidence) for item in result.top_k])
        finally:
            image.close()
        self.registry.verify(model)
        runtime_manifest = {key:manifest.model_dump()[key] for key in ModelManifest.__dataclass_fields__}
        return backend,settings,ModelManifest(**{**runtime_manifest,"status":"production"})

    def _set_runtime(self, loaded, model_id):
        backend,settings,manifest=loaded
        self.app.state.backend=backend
        self.app.state.runtime_settings=settings
        self.app.state.model_manifest=manifest
        self.active_model_id=model_id
        self.activation_uncertain=False
        self.app.state.deployment_ready=True

    async def start(self):
        active=await run_in_threadpool(self._initialize)
        # Keep the lease alive while a large artifact is restored before serving.
        self.tasks=[asyncio.create_task(self._heartbeat_loop())]
        loaded=await run_in_threadpool(self._load,active)
        await run_in_threadpool(self._heartbeat)
        with self.registry.database.session() as session:
            target=self._owned_target(session)
            if target.active_model_id != active.id:
                raise RuntimeError("Active pointer changed during startup")
            target.observed_model_id=active.id
            session.commit()
            self._set_runtime(loaded,active.id)
        self.tasks.append(asyncio.create_task(self._job_loop()))

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks,return_exceptions=True)
        with self.registry.database.session() as session:
            session.execute(update(DeploymentTarget).where(DeploymentTarget.workspace_id==self.registry.workspace_id,
                DeploymentTarget.target_id==self.registry.target_key[1],DeploymentTarget.worker_id==self.worker_id)
                .values(worker_id=None,heartbeat_at=None,observed_model_id=None))
            session.commit()

    def _heartbeat(self):
        try:
            with self.registry.database.session() as session:
                # Slow native loads can delay renewal; a takeover changes the fenced ID.
                changed=session.execute(update(DeploymentTarget).where(DeploymentTarget.workspace_id==self.registry.workspace_id,
                    DeploymentTarget.target_id==self.registry.target_key[1],DeploymentTarget.worker_id==self.worker_id)
                    .values(heartbeat_at=utc_now())).rowcount
                session.commit()
                if changed != 1:
                    raise RuntimeError("Deployment lease lost")
                target=self._owned_target(session)
                if self.active_model_id is not None and (target.active_model_id != self.active_model_id
                        or target.observed_model_id != self.active_model_id):
                    raise RuntimeError("Serving model does not match committed pointer")
        except Exception:
            self.app.state.deployment_ready=False
            raise

    async def _heartbeat_loop(self):
        while True:
            await asyncio.sleep(2)
            try:
                await run_in_threadpool(self._heartbeat)
                if self.active_model_id is not None and not self.activation_uncertain:
                    self.app.state.deployment_ready=True
            except Exception as exc:
                self.app.state.deployment_ready=False
                logger.error("Deployment heartbeat failed (%s)",type(exc).__name__)

    def _claim_job(self):
        if self.activation_uncertain:
            return None
        with self.registry.database.session() as session:
            if session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            target=self._owned_target(session)
            if not target.pending_job_id:
                return None
            job=session.get(DeploymentJob,target.pending_job_id)
            if job is None or job.status != "queued":
                return None
            job.status,job.worker_id="loading",self.worker_id
            model=self.registry.get_model(session,job.to_model_id)
            session.commit()
            return job,model

    def _activate(self,job,loaded):
        with self.registry.database.session() as session:
            # Serialize pointer, approval and membership checks with concurrent writes.
            if session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            target=self._owned_target(session)
            current=session.get(DeploymentJob,job.id)
            if (target.pending_job_id != job.id or target.revision != job.expected_revision
                    or target.active_model_id != job.from_model_id or current.status != "loading" or current.worker_id != self.worker_id):
                raise RuntimeError("Deployment request or pointer changed")
            membership=session.scalar(select(Membership).where(Membership.workspace_id==self.registry.workspace_id,Membership.user_id==job.requested_by))
            user=session.get(User,job.requested_by)
            if user is None or not user.is_active or membership is None or "models:deploy" not in ROLE_PERMISSIONS.get(membership.role,()):
                raise RuntimeError("Deployment permission was revoked")
            model=self.registry.get_model(session,job.to_model_id)
            self.registry.verify(model)
            if job.operation == "deploy":
                self.registry.require_gate(session,model,target)
            elif target.previous_model_id != model.id:
                raise RuntimeError("Rollback destination changed")
            target.previous_model_id,target.active_model_id=target.active_model_id,model.id
            target.observed_model_id,target.pending_job_id=model.id,None
            target.revision+=1
            current.status,current.finished_at="succeeded",utc_now()
            audit(session,self.registry.workspace_id,"deployment.succeeded",job.requested_by,job.id,
                  {"previous_model_id":job.from_model_id,"new_model_id":model.id,"operation":job.operation,"revision":target.revision})
            # A lost commit acknowledgement must not leave the old runtime healthy.
            self.activation_uncertain=True
            self.app.state.deployment_ready=False
            session.commit()
            # No await between durable pointer commit and the in-memory serving switch.
            self._set_runtime(loaded,model.id)

    def _fail(self,job):
        with self.registry.database.session() as session:
            target=self._owned_target(session)
            current=session.get(DeploymentJob,job.id)
            if current is None or current.status != "loading" or current.worker_id != self.worker_id:
                if self.activation_uncertain:
                    target.observed_model_id=None
                    session.commit()
                return
            current.status,current.finished_at="failed",utc_now()
            current.error="Không thể nạp hoặc xác minh mô hình; active model không thay đổi."
            if target.pending_job_id == job.id:
                target.pending_job_id=None
            audit(session,self.registry.workspace_id,"deployment.failed",job.requested_by,job.id,{"reason":"load_or_gate_failed"},"failure")
            session.commit()
            if target.active_model_id == self.active_model_id and target.observed_model_id == self.active_model_id:
                self.activation_uncertain=False
                self.app.state.deployment_ready=True

    async def _job_loop(self):
        while True:
            job=None
            try:
                claimed=await run_in_threadpool(self._claim_job)
                if claimed:
                    job,model=claimed
                    loaded=await run_in_threadpool(self._load,model)
                    await run_in_threadpool(self._heartbeat)
                    async with self.app.state.inference_slots:
                        await run_in_threadpool(self.registry.verify,model)
                        self._activate(job,loaded)
            except Exception as exc:
                logger.error("Deployment failed (%s)",type(exc).__name__)
                if job is not None:
                    try:
                        await run_in_threadpool(self._fail,job)
                    except Exception as fail_exc:
                        logger.error("Deployment failure recording failed (%s)",type(fail_exc).__name__)
            await asyncio.sleep(.25)
