"""Synthetic, trusted DB evidence for deployment mechanics tests, not quality evidence."""
import hashlib
from pathlib import Path
import tempfile
from uuid import uuid4

from app.evaluation_db import EvaluationRun
from app.model_gate import POLICY_VERSION, evaluate_workspace_gate
from app.model_registry_db import RegisteredModel, ModelValidation
from app.platform_db import utc_now
from app.registry_artifacts import RegistryManifest
from app.workspace_data import canonical
from app.workspace_data_db import LabelVersion, DatasetVersion, DatasetSnapshot


def seed_computed_validation(client, candidate_id, report):
    settings, database = client.app.state.settings, client.app.state.platform_database
    actor_id = client.get('/api/v1/auth/me').json()['user']['id']
    snapshot_id, dataset_id, label_id, run_id = [str(uuid4()) for _ in range(4)]
    root = settings.collection_dir / 'workspaces' / settings.workspace_id / 'snapshots' / snapshot_id
    assert root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()), 'Fixture media must stay in temporary roots'
    root.mkdir(parents=True)
    with database.session() as session:
        from app.model_registry_db import DeploymentTarget
        target = session.get(DeploymentTarget,(settings.workspace_id,settings.model_deployment_target))
        candidate, baseline = session.get(RegisteredModel,candidate_id), session.get(RegisteredModel,target.active_model_id)
        labels = [row['label'] for row in report['candidate']['per_class']]
        entries = [dict(id=str(uuid4()),name=name,kind='sign') for name in labels]
        entries.append(dict(id=str(uuid4()),name='Negative fixture',kind='negative'))
        samples = []
        for index, entry in enumerate(entries):
            name = f'samples/{index}.mp4'
            path = root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(f'mechanics-fixture-{index}'.encode())
            path.with_suffix('.json').write_bytes(b'{}')
            samples.append(dict(id=str(uuid4()),collection_session_id=str(uuid4()),label_id=entry['id'],
                expected_label=entry['name'],hand='right',video=name,
                video_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),metadata_sha256=hashlib.sha256(b'{}').hexdigest()))
        manifest = dict(schema_version='1',workspace_id=settings.workspace_id,snapshot_id=snapshot_id,
            dataset_version_id=dataset_id,label_version_id=label_id,labels=entries,quota_per_label=100,samples=samples)
        encoded = canonical(manifest)
        (root / 'manifest.json').write_bytes(encoded)
        digest = hashlib.sha256(encoded).hexdigest()
        for key in ('candidate','baseline'):
            report[key] = {**report[key], 'accuracy':1.0,'negative_count':1,'false_accepts':0,'uncertain_count':0,
                'per_class':[{**row,'support':1,'errors':0,'precision':1.0,'f1':1.0} for row in report[key]['per_class']]}
        report.update(dataset_snapshot_sha256=digest,positive_count=len(labels),negative_count=1,
                      runtime={'backend':'onnx','fixture':'synthetic deployment mechanics only'})
        report.pop('fixture_only',None)
        report.pop('evidence_note',None)
        frozen = dict(candidate=candidate.manifest_json,baseline=baseline.manifest_json,
            snapshot_sha256=digest,dataset_version=dataset_id,label_version=label_id,sample_count=len(samples))
        proof = dict(schema_version='1',workspace_id=settings.workspace_id,snapshot_sha256=digest,
            complete_training_lineage=True,evaluation_groups={row['video_sha256']:'heldout-fixture' for row in samples},
            models={model.manifest_json['artifact_sha256']:dict(source_run_id=model.manifest_json['source_run_id'],
                training_video_sha256=['f'*64],training_group_ids=['training-fixture']) for model in (candidate,baseline)})
        proof_path = settings.model_evaluation_roots[0] / f'provenance-{digest}.json'
        proof_path.write_bytes(canonical(proof))
        frozen['provenance_sha256'] = hashlib.sha256(canonical(proof)).hexdigest()
        gate = evaluate_workspace_gate(report,RegistryManifest.model_validate(candidate.manifest_json),
            RegistryManifest.model_validate(baseline.manifest_json),labels,True)
        session.add(LabelVersion(id=label_id,workspace_id=settings.workspace_id,name='Fixture',entries_json=entries,
            request_hash='a'*64,created_by=actor_id))
        session.flush()
        session.add(DatasetVersion(id=dataset_id,workspace_id=settings.workspace_id,name='Fixture',label_version_id=label_id,
            quota_per_label=100,status='sealed',request_hash='b'*64,created_by=actor_id))
        session.flush()
        session.add(DatasetSnapshot(id=snapshot_id,workspace_id=settings.workspace_id,dataset_version_id=dataset_id,
            label_version_id=label_id,sample_count=len(samples),sha256=digest,created_by=actor_id))
        session.flush()
        report_hash = hashlib.sha256(canonical(report)).hexdigest()
        session.add(EvaluationRun(id=run_id,workspace_id=settings.workspace_id,model_id=candidate.id,
            baseline_model_id=baseline.id,snapshot_id=snapshot_id,requested_by=actor_id,status='completed',
            frozen_json=frozen,report_json=report,gate_json=gate,report_sha256=report_hash,progress=len(samples)*2,
            started_at=utc_now(),finished_at=utc_now()))
        session.add(ModelValidation(id=str(uuid4()),workspace_id=settings.workspace_id,model_id=candidate.id,
            baseline_model_id=baseline.id,report_sha256=report_hash,policy_version=POLICY_VERSION,
            evaluation_run_id=run_id,result_json=gate,created_by=actor_id))
        session.commit()
