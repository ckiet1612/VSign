from __future__ import annotations

import gc
import io
import platform
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import av
import numpy as np
from PIL import Image

from app.backends import create_backend
from app.backends.base import DecodedFrame
from app.evaluation_db import EvaluationRun
from app.evaluation_evidence import verify_inputs, provenance
from app.evaluations import alive, evaluation_audit
from app.model_gate import POLICY_VERSION, evaluate_workspace_gate
from app.model_registry import ModelRegistry
from app.model_registry_db import ModelValidation
from app.models import PredictionStatus
from app.platform_db import utc_now
from app.workspace_data import WorkspaceData, canonical


def metrics(rows, labels):
    per_class = []
    for label in labels:
        support = sum(row['kind'] == 'sign' and row['expected'] == label for row in rows)
        tp = sum(row['kind'] == 'sign' and row['expected'] == label and row['predicted'] == label for row in rows)
        predicted = sum(row['predicted'] == label for row in rows)
        recall = tp / support if support else None
        precision = tp / predicted if predicted else 0.0 if support else None
        f1 = 2 * tp / (support + predicted) if support else None
        per_class.append(dict(label=label, support=support, recall=recall, precision=precision,
                              f1=f1, errors=support-tp))
    negatives = [row for row in rows if row['kind'] == 'negative']
    false_accepts = sum(row['predicted'] is not None for row in negatives)
    correct = sum((row['kind'] == 'negative' and row['predicted'] is None) or
                  (row['kind'] == 'sign' and row['expected'] == row['predicted']) for row in rows)
    return dict(accuracy=correct / len(rows) if rows else None,
        macro_f1=float(np.mean([row['f1'] for row in per_class])) if per_class and all(row['f1'] is not None for row in per_class) else None,
        false_accept_rate=false_accepts / len(negatives) if negatives else None,
        latency_p95_ms=float(np.percentile([row['latency_ms'] for row in rows], 95)),
        per_class=per_class, negative_count=len(negatives), false_accepts=false_accepts,
        uncertain_count=sum(row['predicted'] is None for row in rows))


def video_frames(path):
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Video exceeds evaluation limit')
    images = []
    try:
        with av.open(str(path)) as container:
            for frame in container.decode(video=0):
                if len(images) >= 600 or frame.width * frame.height > 1920 * 1080:
                    raise ValueError('Video exceeds evaluation decode limit')
                image = frame.to_image().convert('RGB')
                images.append(image.resize((224,224), Image.Resampling.BILINEAR))
                image.close()
        if not images:
            raise ValueError('Empty evaluation video')
        indices = np.rint(np.linspace(0, len(images)-1, 16)).astype(int)
        result = []
        for index in indices:
            encoded = io.BytesIO()
            images[index].save(encoded, format='JPEG', quality=90)
            raw = encoded.getvalue()
            # Match the wire path: models receive decoded JPEG, not pre-JPEG RGB.
            with Image.open(io.BytesIO(raw)) as decoded:
                result.append(DecodedFrame(decoded.convert('RGB'), raw))
        return result
    finally:
        for image in images:
            image.close()


def model_settings(settings, model):
    manifest = model.manifest_json
    return replace(settings, inference_backend=manifest['backend'], model_version=manifest['model_version'],
        model_manifest_path=None, label_map_path=Path(model.labels_path), labels_verified=True,
        onnx_model_path=Path(model.artifact_path) if manifest['backend'] == 'onnx' else None,
        coreml_model_path=Path(model.artifact_path) if manifest['backend'] == 'coreml' else None,
        pytorch_model_path=Path(model.artifact_path) if manifest['backend'] == 'pytorch' else None,
        confidence_threshold=manifest['confidence_threshold'], margin_threshold=manifest['margin_threshold'])


def owned(run, worker_id):
    return run is not None and run.status == 'running' and run.worker_id == worker_id and alive(run.heartbeat_at)


def execute_run(database, settings, run_id, worker_id, factory=create_backend):
    registry, data = ModelRegistry(database, settings), WorkspaceData(database, settings)
    with database.session() as session:
        run = session.get(EvaluationRun, run_id)
        if not owned(run, worker_id) or run.workspace_id != settings.workspace_id:
            return
        candidate, baseline, manifest, actor = verify_inputs(registry, session, run)
        frozen = run.frozen_json
        root = data.directory(actor, 'snapshots', run.snapshot_id)
    classes = [label for label in registry.verify(candidate)[1] if label != 'Không ký hiệu']
    kinds = {entry['name']:entry['kind'] for entry in manifest['labels']}
    results = {}
    progress = 0
    for key, model in (('baseline',baseline), ('candidate',candidate)):
        backend = factory(model_settings(settings, model))
        if (backend.is_mock or backend.candidate_labels_unverified or backend.name != frozen[key]['backend'] or
            backend.model_version != model.model_version or list(backend.labels) != registry.verify(model)[1]):
            raise ValueError('Backend identity mismatch')
        rows = []
        try:
            for index, sample in enumerate(manifest['samples']):
                with database.session() as session:
                    if not owned(session.get(EvaluationRun, run_id), worker_id):
                        return
                frames = video_frames(data.media(root, sample['video']))
                try:
                    if index == 0:
                        backend.predict(frames, 0)  # One unmeasured warmup for each model.
                    start = perf_counter()
                    prediction = backend.predict(frames, index + 1)
                    latency = max(.001, (perf_counter() - start) * 1000)
                    if prediction.status not in (PredictionStatus.OK, PredictionStatus.UNCERTAIN):
                        raise ValueError('Inference failed during evaluation')
                    predicted = prediction.label if prediction.status == PredictionStatus.OK else None
                    if predicted == 'Không ký hiệu':
                        predicted = None
                    if predicted is not None and predicted not in classes:
                        raise ValueError('Invalid evaluation prediction')
                    if prediction.status == PredictionStatus.OK and prediction.label is None:
                        raise ValueError('Invalid accepted prediction')
                    rows.append(dict(expected=sample['expected_label'], kind=kinds[sample['expected_label']],
                                     predicted=predicted, latency_ms=latency))
                finally:
                    for frame in frames:
                        frame.image.close()
                progress += 1
                with data.write(actor) as session:
                    current = session.get(EvaluationRun,run_id)
                    if not owned(current, worker_id):
                        return
                    current.progress = progress
            results[key] = metrics(rows, classes)
        finally:
            del backend
            gc.collect()
    with data.write(actor) as session:
        run = session.get(EvaluationRun, run_id)
        if not owned(run, worker_id):
            return
        candidate, baseline, manifest, _ = verify_inputs(registry, session, run)
        trusted, _ = provenance(settings, run.workspace_id, frozen['snapshot_sha256'], manifest, frozen,
                                expected_hash=frozen['provenance_sha256'])
        trusted = trusted and frozen['provenance_sha256'] is not None
        cm, labels = registry.verify(candidate)
        bm, _ = registry.verify(baseline)
        report = dict(schema_version='1', candidate_artifact_sha256=cm.artifact_sha256,
            baseline_artifact_sha256=bm.artifact_sha256, labels_sha256=cm.labels_sha256,
            source_run_id=cm.source_run_id, preprocessing_version=cm.preprocessing_version,
            protocol_version=cm.protocol_version, confidence_threshold=cm.confidence_threshold,
            margin_threshold=cm.margin_threshold, baseline_confidence_threshold=bm.confidence_threshold,
            baseline_margin_threshold=bm.margin_threshold, dataset_snapshot_sha256=frozen['snapshot_sha256'],
            held_out=bool(trusted), independent_negatives=bool(trusted),
            positive_count=sum(kinds[sample['expected_label']] == 'sign' for sample in manifest['samples']),
            negative_count=sum(kinds[sample['expected_label']] == 'negative' for sample in manifest['samples']),
            runtime=dict(backend=cm.backend, system=platform.system(), machine=platform.machine(),
                pytorch_device=settings.pytorch_device, coreml_compute_units=settings.coreml_compute_units,
                latency_scope='predict-only; warmup excluded; not camera-to-result'), **results)
        gate = evaluate_workspace_gate(report,cm,bm,labels,bool(trusted))
        digest = sha256(canonical(report)).hexdigest()
        run.status, run.finished_at = 'completed', utc_now()
        run.report_json, run.gate_json, run.report_sha256 = report,gate,digest
        session.add(ModelValidation(id=str(uuid4()), workspace_id=run.workspace_id,
            model_id=run.model_id, baseline_model_id=run.baseline_model_id, report_sha256=digest,
            evaluation_run_id=run.id, policy_version=POLICY_VERSION, result_json=gate, created_by=run.requested_by))
        candidate.approved_validation_id = candidate.approved_by = candidate.approved_at = None
        evaluation_audit(session,run,'completed')
