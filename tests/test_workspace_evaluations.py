from dataclasses import replace
from uuid import uuid4
import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.platform_db import Membership
from test_local_admin import local_settings
from tests.test_personal_collection import sample_payload

BASE = '/api/v1/workspace/evaluations'


@pytest.fixture
def settings(monkeypatch, tmp_path):
    return replace(local_settings(monkeypatch, tmp_path), collection_enabled=True,
                   collection_dir=tmp_path / 'media', model_registry_roots=(tmp_path,),
                   model_evaluation_roots=(tmp_path / 'evidence',))


def test_evaluation_overview_is_empty_scoped_and_enabled(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get(BASE)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['workspace_id'] == settings.workspace_id
        assert body['runs'] == body['snapshots'] == body['models'] == []
        assert body['permissions'] == {'create': True, 'cancel': True}
        assert client.get('/api/v1/workspace/capabilities').json()['capabilities']['evaluation'] is True


@pytest.mark.parametrize('role,read,write', [('owner',True,True), ('admin',True,True),
    ('reviewer',True,False), ('operator',False,False), ('viewer',False,False), ('model_admin',False,False)])
def test_evaluation_permissions_before_body(settings, role, read, write):
    settings = replace(settings, local_admin_enabled=False, bootstrap_admin_email='admin@example.com',
                       bootstrap_admin_password='test-password-12345')
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = role
            session.commit()
        assert client.post('/api/v1/auth/login', json={'email':settings.bootstrap_admin_email,
            'password':settings.bootstrap_admin_password}).status_code == 200
        assert client.get(BASE).status_code == (200 if read else 403)
        assert client.post(BASE, json={}).status_code == (422 if write else 403)
        assert client.post(BASE + f'/{uuid4()}/cancel', json={}).status_code == (404 if write else 403)


def test_evaluation_auth_origin_body_and_foreign_identity(settings):
    with TestClient(create_app(replace(settings, local_admin_enabled=False))) as client:
        assert client.get(BASE).status_code == 401
        assert client.post(BASE, json={}).status_code == 401
    with TestClient(create_app(settings)) as client:
        assert client.post(BASE, json={}, headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.post(BASE, content='x' * 9000).status_code == 413
        assert client.post(BASE, json={'request_id':str(uuid4()), 'model_id':str(uuid4()),
            'snapshot_id':str(uuid4())}).status_code == 404


def prepare_evaluation(client, settings, tmp_path):
    from app.model_manifest import labels_digest
    from app.model_registry_db import RegisteredModel, DeploymentTarget
    from app.platform_auth import local_admin_id
    from test_model_registry import model_files
    database = client.app.state.platform_database
    ids = [str(uuid4()), str(uuid4())]
    with database.session() as session:
        for identity, version in zip(ids, ('baseline', 'candidate')):
            files = model_files(tmp_path, version)
            Path(files['labels_path']).write_text(json.dumps(['Hello']))
            manifest = json.loads(Path(files['manifest_path']).read_text())
            manifest['labels_sha256'] = labels_digest(['Hello'])
            session.add(RegisteredModel(id=identity, workspace_id=settings.workspace_id, model_version=version,
                artifact_path=files['artifact_path'], labels_path=files['labels_path'], labels_count=1,
                manifest_json=manifest, origin='baseline' if version == 'baseline' else 'candidate',
                created_by=local_admin_id(settings.workspace_id)))
        session.flush()
        session.add(DeploymentTarget(workspace_id=settings.workspace_id, target_id=settings.model_deployment_target,
            runtime_url='http://127.0.0.1:9999', backend='onnx', active_model_id=ids[0], observed_model_id=ids[0], revision=0))
        session.commit()
    data = '/api/v1/workspace/data'
    label_version, dataset, collection, snapshot = [str(uuid4()) for _ in range(4)]
    response = client.post(data + '/labels', json={'request_id':label_version, 'name':'Evaluation', 'entries':[
        {'id':str(uuid4()), 'name':'Hello', 'kind':'sign'}, {'id':str(uuid4()), 'name':'Không ký hiệu', 'kind':'negative'}]})
    assert response.status_code == 201, response.text
    assert client.post(data + '/datasets', json={'request_id':dataset, 'name':'Holdout', 'label_version_id':label_version}).status_code == 201
    assert client.post(data + '/sessions', json={'request_id':collection, 'dataset_version_id':dataset}).status_code == 201
    for label in ('Hello','Không ký hiệu'):
        response = client.post(data + f'/sessions/{collection}/samples', json=sample_payload(
            expected_label=label, sample_key=str(uuid4())))
        assert response.status_code == 200, response.text
    assert client.post(data + f'/sessions/{collection}/state', json={'state':'stopped'}).status_code == 200
    response = client.post(data + f'/datasets/{dataset}/snapshot', json={'request_id':snapshot})
    assert response.status_code == 201, response.text
    return {'request_id':str(uuid4()), 'model_id':ids[1], 'snapshot_id':snapshot}


def test_queue_freezes_identity_retries_cancels_and_never_changes_production(settings, tmp_path):
    from app.model_registry_db import DeploymentTarget
    with TestClient(create_app(settings)) as client:
        payload = prepare_evaluation(client, settings, tmp_path)
        response = client.post(BASE, json=payload)
        assert response.status_code == 201, response.text
        first = response.json()['runs'][0]
        assert first['status'] == 'queued' and first['report'] is None
        assert first['model_version'] == 'candidate' and first['baseline_model_version'] == 'baseline'
        assert client.post(BASE, json=payload).json()['runs'] == [first]
        assert client.post(BASE, json={**payload,'model_id':first['baseline_model_id']}).status_code == 409
        assert client.post(BASE, json={**payload,'request_id':str(uuid4())}).status_code == 409
        assert client.post(BASE + f'/{first["id"]}/cancel').json()['runs'][0]['status'] == 'cancelled'
        assert client.post(BASE + f'/{first["id"]}/cancel').status_code == 200
        assert client.post(BASE, json=payload).json()['runs'][0]['status'] == 'cancelled'
        events=client.get('/api/v1/workspace/audit/events?group=evaluation').json()['events']
        assert {row['event_type'] for row in events} == {'evaluation.requested','evaluation.cancelled'}
        assert all(row['resource_id'] == first['id'] and row['metadata']['source'] == 'server' for row in events)
        with client.app.state.platform_database.session() as session:
            target = session.get(DeploymentTarget, (settings.workspace_id,settings.model_deployment_target))
            assert target.active_model_id == first['baseline_model_id'] and target.revision == 0
            assert target.pending_job_id is None


def test_metrics_count_rejections_negatives_and_missing_support():
    from app.evaluation_engine import metrics
    result = metrics([
        {'expected':'A','kind':'sign','predicted':'A','latency_ms':10},
        {'expected':'A','kind':'sign','predicted':None,'latency_ms':20},
        {'expected':'B','kind':'sign','predicted':'A','latency_ms':30},
        {'expected':'negative','kind':'negative','predicted':'A','latency_ms':40},
        {'expected':'negative','kind':'negative','predicted':None,'latency_ms':50},
    ], ['A','B','C'])
    assert result['accuracy'] == .4
    assert result['false_accept_rate'] == .5 and result['false_accepts'] == 1
    assert result['uncertain_count'] == 2
    assert result['macro_f1'] is None  # C has no support, never silently omit it
    assert result['per_class'][0] == {'label':'A','support':2,'precision':1/3,'recall':.5,'f1':.4,'errors':1}
    assert result['per_class'][2]['recall'] is None
    assert metrics([{'expected':'A','kind':'sign','predicted':'A','latency_ms':1}], ['A'])['false_accept_rate'] is None


def test_engine_completes_real_snapshot_but_missing_provenance_blocks_gate(settings, tmp_path):
    from app.evaluation_worker import claim_run
    from app.evaluation_engine import execute_run
    from app.backends.base import BackendPrediction
    from app.models import PredictionStatus
    from app.model_registry_db import DeploymentTarget, ModelValidation
    from app.evaluation_db import EvaluationRun

    class Backend:
        name, labels, is_mock, candidate_labels_unverified = 'onnx', ['Hello'], False, False
        def __init__(self, config):
            self.model_version = config.model_version
        def predict(self, frames, sequence):
            assert len(frames) == 16 and frames[0].image.size == (224,224)
            return BackendPrediction(PredictionStatus.UNCERTAIN,None,.1,[])

    with TestClient(create_app(settings)) as client:
        payload = prepare_evaluation(client, settings, tmp_path)
        assert client.post(BASE, json=payload).status_code == 201
        db = client.app.state.platform_database
        assert claim_run(db, settings, 'onnx', 'worker-1') == payload['request_id']
        execute_run(db, settings, payload['request_id'], 'worker-1', Backend)
        run = client.get(BASE).json()['runs'][0]
        assert run['status'] == 'completed', run
        assert run['progress'] == run['sample_count'] * 2
        assert run['report']['candidate']['accuracy'] == .5
        assert run['report']['candidate']['false_accept_rate'] == 0
        assert not run['gate']['passed']
        assert not next(check for check in run['gate']['checks'] if check['name'] == 'trusted_provenance')['passed']
        with db.session() as session:
            target = session.get(DeploymentTarget,(settings.workspace_id, settings.model_deployment_target))
            assert target.revision == 0 and target.pending_job_id is None
            validation = session.scalar(select(ModelValidation))
            assert validation.evaluation_run_id == payload['request_id']
            assert session.get(EvaluationRun,payload['request_id']).report_sha256


def test_worker_expiry_fences_cancelled_and_lost_runs(settings, tmp_path):
    from app.evaluation_worker import claim_run, finish_failure
    from app.evaluation_db import EvaluationRun
    from app.platform_db import utc_now
    with TestClient(create_app(settings)) as client:
        payload = prepare_evaluation(client, settings, tmp_path)
        assert client.post(BASE, json=payload).status_code == 201
        db = client.app.state.platform_database
        assert claim_run(db, settings, 'coreml', 'worker-other') is None
        assert claim_run(db, settings, 'onnx', 'worker-1') == payload['request_id']
        assert claim_run(db, settings, 'onnx', 'worker-2') is None
        with db.session() as session:
            session.get(EvaluationRun,payload['request_id']).heartbeat_at = utc_now() - timedelta(seconds=60)
            session.commit()
        assert claim_run(db, settings, 'onnx', 'worker-2') is None
        assert client.get(BASE).json()['runs'][0]['status'] == 'failed'
        assert not finish_failure(db, settings, payload['request_id'], 'worker-1', 'late failure')


def test_snapshot_tampering_rejected_before_queue(settings, tmp_path):
    with TestClient(create_app(settings)) as client:
        payload = prepare_evaluation(client, settings, tmp_path)
        video = next((settings.collection_dir / 'workspaces' / settings.workspace_id / 'snapshots').rglob('*.mp4'))
        video.write_bytes(b'tampered')
        assert client.post(BASE,json=payload).status_code == 409
        assert client.get(BASE).json()['runs'] == []


def write_provenance(client, settings, payload, *, overlap=False):
    from app.workspace_data import canonical
    from app.model_registry_db import RegisteredModel
    # Resolve the sealed manifest through the same public read endpoint.
    manifest = client.get('/api/v1/workspace/data/snapshots/' + payload['snapshot_id'] + '/manifest').json()
    digest = client.get('/api/v1/workspace/data').json()['snapshots'][0]['sha256']
    with client.app.state.platform_database.session() as session:
        models = session.scalars(select(RegisteredModel)).all()
        proof = dict(schema_version='1',workspace_id=settings.workspace_id,snapshot_sha256=digest,
            complete_training_lineage=True,evaluation_groups={row['video_sha256']:'heldout' for row in manifest['samples']},
            models={row.manifest_json['artifact_sha256']:dict(source_run_id=row.manifest_json['source_run_id'],
                training_video_sha256=['f'*64],training_group_ids=['heldout' if overlap else 'training']) for row in models})
    directory = settings.model_evaluation_roots[0]
    directory.mkdir(exist_ok=True)
    path = directory / f'provenance-{digest}.json'
    path.write_bytes(canonical(proof))
    return path


def test_trusted_evaluation_requires_separate_approval_and_rechecks_evidence(settings, tmp_path, monkeypatch):
    from itertools import count
    import app.evaluation_engine as engine
    from app.evaluation_worker import claim_run
    from app.backends.base import BackendPrediction
    from app.models import PredictionStatus
    from app.model_registry import ModelRegistry
    from app.platform_auth import resolve_local_admin
    from app.model_registry_db import ModelValidation, RegisteredModel
    from fastapi import HTTPException
    clock = count()
    monkeypatch.setattr(engine,'perf_counter',lambda: next(clock)*.1)
    class Backend:
        name, labels, is_mock, candidate_labels_unverified = 'onnx',['Hello'],False,False
        def __init__(self,config): self.model_version = config.model_version
        def predict(self,frames,sequence): return BackendPrediction(PredictionStatus.UNCERTAIN,None,.1,[])
    with TestClient(create_app(settings)) as client:
        payload = prepare_evaluation(client,settings,tmp_path)
        proof = write_provenance(client,settings,payload)
        assert client.post(BASE,json=payload).status_code == 201
        db = client.app.state.platform_database
        claim_run(db,settings,'onnx','worker')
        engine.execute_run(db,settings,payload['request_id'],'worker',Backend)
        run = client.get(BASE).json()['runs'][0]
        assert run['gate']['passed'],run
        registry = ModelRegistry(db,settings)
        with db.session() as session:
            candidate = session.get(RegisteredModel,payload['model_id'])
            assert candidate.approved_validation_id is None
            validation = session.scalar(select(ModelValidation))
            validation_id = validation.id
            with pytest.raises(HTTPException): registry.require_gate(session,candidate,registry.target(session))
        actor = resolve_local_admin(db,settings.workspace_id)
        registry.approve(actor,payload['model_id'],validation_id)
        with db.session() as session:
            registry.require_gate(session,registry.get_model(session,payload['model_id']),registry.target(session))
        proof.write_text('{}')
        with db.session() as session, pytest.raises(HTTPException):
            registry.require_gate(session,registry.get_model(session,payload['model_id']),registry.target(session))
        with pytest.raises(HTTPException): registry.approve(actor,payload['model_id'],validation_id)


def test_provenance_overlap_is_not_trusted_and_late_file_cannot_upgrade_existing_run(settings,tmp_path):
    from app.evaluation_db import EvaluationRun
    with TestClient(create_app(settings)) as client:
        payload = prepare_evaluation(client,settings,tmp_path)
        write_provenance(client,settings,payload,overlap=True)
        assert client.post(BASE,json=payload).status_code == 201
        write_provenance(client,settings,payload,overlap=False)
        with client.app.state.platform_database.session() as session:
            assert session.get(EvaluationRun,payload['request_id']).frozen_json['provenance_sha256'] is None


def test_cancel_during_inference_never_publishes_late_results(settings,tmp_path):
    from app.evaluation_worker import claim_run
    from app.evaluation_engine import execute_run
    from app.backends.base import BackendPrediction
    from app.models import PredictionStatus
    from app.model_registry_db import ModelValidation
    with TestClient(create_app(settings)) as client:
        payload = prepare_evaluation(client,settings,tmp_path)
        assert client.post(BASE,json=payload).status_code == 201
        db = client.app.state.platform_database
        claim_run(db,settings,'onnx','worker')
        class Backend:
            name,labels,is_mock,candidate_labels_unverified='onnx',['Hello'],False,False
            def __init__(self,config): self.model_version=config.model_version
            def predict(self,frames,sequence):
                assert client.post(BASE + '/' + payload['request_id'] + '/cancel').status_code == 200
                return BackendPrediction(PredictionStatus.UNCERTAIN,None,.1,[])
        execute_run(db,settings,payload['request_id'],'worker',Backend)
        run = client.get(BASE).json()['runs'][0]
        assert run['status'] == 'cancelled' and run['report'] is None and run['gate'] is None
        with db.session() as session: assert session.scalar(select(ModelValidation)) is None


def test_expired_lease_cannot_be_renewed_by_original_worker(settings,tmp_path):
    from app.evaluation_worker import claim_run,heartbeat
    from app.evaluation_db import EvaluationRun,EvaluationWorkerState
    from app.platform_db import utc_now
    with TestClient(create_app(settings)) as client:
        payload=prepare_evaluation(client,settings,tmp_path)
        assert client.post(BASE,json=payload).status_code == 201
        db=client.app.state.platform_database
        claim_run(db,settings,'onnx','original-worker')
        with db.session() as session:
            expired=utc_now()-timedelta(seconds=60)
            session.get(EvaluationRun,payload['request_id']).heartbeat_at=expired
            session.get(EvaluationWorkerState,(settings.workspace_id,'onnx')).heartbeat_at=expired
            session.commit()
        assert heartbeat(db,settings,'onnx','original-worker',payload['request_id']) is False
        assert client.get(BASE).json()['runs'][0]['status'] == 'failed'


def test_malformed_provenance_still_allows_informational_evaluation(settings,tmp_path):
    with TestClient(create_app(settings)) as client:
        payload=prepare_evaluation(client,settings,tmp_path)
        path=write_provenance(client,settings,payload)
        document=json.loads(path.read_text())
        document['evaluation_groups']=list(document['evaluation_groups'])
        path.write_text(json.dumps(document))
        response=client.post(BASE,json=payload)
        assert response.status_code == 201,response.text


def test_other_tenant_model_and_runs_are_not_visible_or_actionable(settings,tmp_path):
    from app.model_registry_db import RegisteredModel
    from app.evaluation_db import EvaluationRun
    from app.platform_db import Workspace
    with TestClient(create_app(settings)) as client:
        payload=prepare_evaluation(client,settings,tmp_path)
        assert client.post(BASE,json=payload).status_code == 201
        foreign_model,foreign_run=str(uuid4()),str(uuid4())
        with client.app.state.platform_database.session() as session:
            session.add(Workspace(id='other-tenant',name='Other',environment='development'))
            session.flush()
            model=session.get(RegisteredModel,payload['model_id'])
            session.add(RegisteredModel(id=foreign_model,workspace_id='other-tenant',model_version='private-v1',
                artifact_path=model.artifact_path,labels_path=model.labels_path,labels_count=1,
                manifest_json={**model.manifest_json,'model_version':'private-v1'},origin='candidate'))
            session.flush()
            original=session.get(EvaluationRun,payload['request_id'])
            session.add(EvaluationRun(id=foreign_run,workspace_id='other-tenant',model_id=foreign_model,
                baseline_model_id=original.baseline_model_id,snapshot_id=original.snapshot_id,requested_by=original.requested_by,
                frozen_json=original.frozen_json,status='queued'))
            session.commit()
        overview=client.get(BASE).json()
        assert all(row['id'] != foreign_model for row in overview['models'])
        assert all(row['id'] != foreign_run for row in overview['runs'])
        assert client.post(BASE,json={**payload,'request_id':str(uuid4()),'model_id':foreign_model}).status_code == 404
        assert client.post(BASE+'/'+foreign_run+'/cancel').status_code == 404
