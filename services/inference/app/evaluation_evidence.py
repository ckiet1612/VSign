from __future__ import annotations

from hashlib import sha256
from types import SimpleNamespace

from fastapi import HTTPException

from app.registry_artifacts import checked_local_path, read_json
from app.workspace_data import canonical


def provenance(settings, workspace_id, snapshot_hash, manifest, frozen, expected_hash):
    """Only operator-owned files attest lineage; browser claims never reach this boundary."""
    try:
        paths = [root / f'provenance-{snapshot_hash}.json' for root in settings.model_evaluation_roots]
        paths = [path for path in paths if path.exists()]
        if len(paths) != 1:
            return False, None
        path = checked_local_path(paths[0], settings.model_evaluation_roots)
        document = read_json(path, max_bytes=4 * 1024 * 1024)
        if not isinstance(document,dict) or not isinstance(document.get('models'),dict):
            return False, None
        digest = sha256(canonical(document)).hexdigest()
        if expected_hash is not None and digest != expected_hash:
            return False, digest
        if (document['schema_version'] != '1' or document['workspace_id'] != workspace_id or
            document['snapshot_sha256'] != snapshot_hash or document['complete_training_lineage'] is not True):
            return False, digest
        evaluation = document['evaluation_groups']
        videos = {sample['video_sha256'] for sample in manifest['samples']}
        if not isinstance(evaluation,dict) or set(evaluation) != videos or not all(isinstance(group, str) and group.strip() for group in evaluation.values()):
            return False, digest
        groups = set(evaluation.values())
        for key in ('candidate','baseline'):
            model = frozen[key]
            lineage = document['models'][model['artifact_sha256']]
            if not isinstance(lineage,dict) or lineage['source_run_id'] != model['source_run_id']:
                return False, digest
            training_videos, training_groups = lineage['training_video_sha256'], lineage['training_group_ids']
            if (not isinstance(training_videos, list) or not training_videos or not isinstance(training_groups, list) or
                not training_groups or not all(isinstance(v, str) and len(v) == 64 and all(c in '0123456789abcdef' for c in v)
                    for v in training_videos) or not all(isinstance(v, str) and v.strip() for v in training_groups) or
                videos.intersection(training_videos) or groups.intersection(training_groups)):
                return False, digest
        return True, digest
    except (OSError, ValueError, KeyError, TypeError):
        return False, None


def verify_inputs(registry, session, run):
    from app.workspace_data import WorkspaceData
    from app.workspace_data_db import DatasetSnapshot
    if run.workspace_id != registry.workspace_id:
        raise HTTPException(409, 'Bằng chứng không thuộc workspace')
    frozen = run.frozen_json
    candidate = registry.get_model(session,run.model_id)
    baseline = registry.get_model(session,run.baseline_model_id)
    for key, model in (('candidate',candidate),('baseline',baseline)):
        registry.verify(model)
        if model.manifest_json != frozen[key]:
            raise HTTPException(409, 'Danh tính model đã thay đổi')
    actor = SimpleNamespace(workspace=SimpleNamespace(id=run.workspace_id))
    data = WorkspaceData(registry.database, registry.settings)
    snapshot = data.get(session,DatasetSnapshot,actor,run.snapshot_id)
    if (snapshot.sha256 != frozen['snapshot_sha256'] or snapshot.dataset_version_id != frozen['dataset_version'] or
        snapshot.label_version_id != frozen['label_version'] or snapshot.sample_count != frozen['sample_count']):
        raise HTTPException(409, 'Snapshot đã thay đổi')
    return candidate, baseline, data.read_manifest(actor,snapshot), actor


def require_evaluation_evidence(registry, session, validation):
    from app.evaluation_db import EvaluationRun
    from app.model_gate import evaluate_workspace_gate
    run = session.get(EvaluationRun, validation.evaluation_run_id) if validation.evaluation_run_id else None
    if (run is None or run.workspace_id != registry.workspace_id or run.status != 'completed' or
        run.model_id != validation.model_id or run.baseline_model_id != validation.baseline_model_id or
        not run.report_json or not run.frozen_json.get('provenance_sha256') or
        sha256(canonical(run.report_json)).hexdigest() != run.report_sha256 or
        validation.report_sha256 != run.report_sha256):
        raise HTTPException(409, 'Cần kết quả đánh giá do worker tính trên snapshot độc lập đã xác minh')
    candidate, baseline, manifest, _ = verify_inputs(registry,session,run)
    kinds = {entry['name']:entry['kind'] for entry in manifest['labels']}
    positive_count = sum(kinds[sample['expected_label']] == 'sign' for sample in manifest['samples'])
    negative_count = len(manifest['samples']) - positive_count
    if (run.progress != len(manifest['samples'])*2 or run.report_json.get('positive_count') != positive_count or
        run.report_json.get('negative_count') != negative_count):
        raise HTTPException(409, 'Số mẫu trong báo cáo không khớp snapshot')
    for key in ('candidate','baseline'):
        if any(row['support'] != sum(sample['expected_label'] == row['label'] and kinds[row['label']] == 'sign'
                for sample in manifest['samples']) for row in run.report_json[key]['per_class']):
            raise HTTPException(409, 'Số mẫu từng nhãn không khớp snapshot')
    trusted, _ = provenance(registry.settings,run.workspace_id,run.frozen_json['snapshot_sha256'],manifest,
        run.frozen_json,expected_hash=run.frozen_json['provenance_sha256'])
    cm, labels = registry.verify(candidate)
    bm, _ = registry.verify(baseline)
    gate = evaluate_workspace_gate(run.report_json,cm,bm,labels,trusted)
    if (not gate['passed'] or gate != run.gate_json or gate != validation.result_json or
        run.report_json.get('dataset_snapshot_sha256') != run.frozen_json['snapshot_sha256']):
        raise HTTPException(409, 'Bằng chứng đánh giá không còn đạt chốt chất lượng')
