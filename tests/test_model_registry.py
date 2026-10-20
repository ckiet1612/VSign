from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.model_manifest import labels_digest
from app.backends.base import BackendPrediction
from app.models import PredictionStatus
import time
from app.model_registry_db import DeploymentJob, DeploymentTarget, RegisteredModel
from app.platform_db import Membership, User, Workspace, utc_now
from sqlalchemy import select
from threading import Event
from datetime import timedelta


def test_model_registry_requires_login_even_in_optional_auth_mode():
    with TestClient(create_app(Settings())) as client:
        assert client.get('/api/v1/workspace/models').status_code == 401
        assert client.post('/api/v1/workspace/models', json={}).status_code == 401


def test_managed_runtime_settings_require_explicit_worker_opt_in(monkeypatch,tmp_path):
    monkeypatch.delenv('MODEL_DEPLOYMENT_WORKER',raising=False)
    assert Settings.from_env().model_deployment_worker is False
    monkeypatch.setenv('MODEL_DEPLOYMENT_WORKER','true')
    monkeypatch.setenv('MODEL_REGISTRY_ROOTS',str(tmp_path))
    monkeypatch.setenv('MODEL_EVALUATION_ROOTS',str(tmp_path/'evaluations'))
    settings=Settings.from_env()
    assert settings.model_deployment_worker is True
    assert settings.model_registry_roots==(tmp_path,)
    assert settings.model_evaluation_roots==(tmp_path/'evaluations',)


def model_files(root: Path, version: str) -> dict:
    directory = root / version
    directory.mkdir(parents=True)
    artifact = directory / 'model.onnx'
    artifact.write_bytes(version.encode())
    labels = ['Hello', 'Bye']
    label_file = directory / 'labels.json'
    label_file.write_text(json.dumps(labels))
    manifest = dict(model_version=version, artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    labels_sha256=labels_digest(labels), backend='onnx', protocol_version='1.0',
                    frame_count=16, frame_size=224, preprocessing_version='rgb16-224-imagenet-v1',
                    confidence_threshold=.7, margin_threshold=.15, source_run_id=f'train-{version}', status='candidate')
    manifest_file = directory / 'manifest.json'
    manifest_file.write_text(json.dumps(manifest))
    return dict(manifest_path=str(manifest_file), artifact_path=str(artifact), labels_path=str(label_file))


def configured(tmp_path: Path, **overrides) -> Settings:
    return Settings(database_url=f'sqlite:///{tmp_path / "registry.db"}', app_environment='development',
                    bootstrap_admin_email='admin@example.com', bootstrap_admin_password='Correct Horse Battery Staple',
                    model_registry_roots=(tmp_path,), model_evaluation_roots=(tmp_path,),
                    collection_dir=tmp_path/'collection', **overrides)


def login(client):
    with client.app.state.platform_database.session() as session:
        session.scalar(select(Membership)).role = 'model_admin'
        session.commit()
    assert client.post('/api/v1/auth/login', json=dict(email='admin@example.com', password='Correct Horse Battery Staple')).status_code == 200


def test_register_candidate_is_immutable_and_does_not_deploy(tmp_path):
    files = model_files(tmp_path, 'candidate-1')
    with TestClient(create_app(configured(tmp_path))) as client:
        login(client)
        response = client.post('/api/v1/workspace/models', json=files)
        assert response.status_code == 201, response.text
        snapshot = response.json()
        assert snapshot['target'] is None
        assert snapshot['deployments'] == []
        candidate = snapshot['models'][0]
        assert candidate['origin'] == candidate['status'] == 'candidate'
        assert candidate['approved_validation_id'] is None
        assert candidate['validation'] is None
        assert 'artifact_path' not in candidate
        assert client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve', json={'validation_id':str(uuid4())}).status_code == 409
        assert client.post('/api/v1/workspace/models/deployments', json=dict(request_id=str(uuid4()),model_id=candidate['id'],expected_revision=0)).status_code in (409,503)
        Path(files['artifact_path']).write_bytes(b'tampered')
        assert client.post('/api/v1/workspace/models', json=files).status_code == 422


def test_registration_rejects_outside_roots_symlinks_and_production_manifest(tmp_path):
    files = model_files(tmp_path, 'candidate-1')
    with TestClient(create_app(configured(tmp_path / 'allowed'))) as client:
        login(client)
        assert client.post('/api/v1/workspace/models', json=files).status_code == 422
    link = tmp_path / 'linked.onnx'
    link.symlink_to(files['artifact_path'])
    with TestClient(create_app(configured(tmp_path))) as client:
        login(client)
        assert client.post('/api/v1/workspace/models', json={**files,'artifact_path':str(link)}).status_code == 422
        manifest = Path(files['manifest_path'])
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), 'status':'production'}))
        assert client.post('/api/v1/workspace/models', json=files).status_code == 422


def test_models_mutation_has_origin_and_body_size_guards(tmp_path):
    with TestClient(create_app(configured(tmp_path))) as client:
        login(client)
        assert client.post('/api/v1/workspace/models', json={}, headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.post('/api/v1/workspace/models', content='x'*9000).status_code == 413


def test_registration_is_blocked_for_the_entire_training_write_window(tmp_path):
    from contracts.model_lifecycle_lock import lifecycle_lock
    settings=configured(tmp_path)
    files=model_files(tmp_path,'still-training')
    with TestClient(create_app(settings)) as client:
        login(client)
        with lifecycle_lock(settings.database_url,training=True):
            response=client.post('/api/v1/workspace/models',json=files)
            assert response.status_code==409,response.text
            assert client.get('/api/v1/workspace/models').json()['models']==[]
        assert client.post('/api/v1/workspace/models',json=files).status_code==201


class FakeBackend:
    name = 'onnx'
    labels = ['Hello','Bye']
    candidate_labels_unverified = False
    is_mock = False

    def __init__(self, settings):
        self.model_version = settings.model_version
        self.confidence_threshold=settings.confidence_threshold
        self.margin_threshold=settings.margin_threshold

    def predict(self, frames, sequence):
        return BackendPrediction(PredictionStatus.UNCERTAIN,None,.2,[])


def managed_settings(tmp_path):
    baseline = model_files(tmp_path,'baseline-1')
    return configured(tmp_path,inference_backend='onnx',model_version='baseline-1',labels_verified=True,
        onnx_model_path=Path(baseline['artifact_path']),label_map_path=Path(baseline['labels_path']),
        model_deployment_worker=True)


def evaluation_report(tmp_path, snapshot, candidate, **overrides):
    baseline = next(m for m in snapshot['models'] if m['id'] == snapshot['target']['active_model_id'])
    metrics = dict(macro_f1=.95,false_accept_rate=.01,latency_p95_ms=100,
                   per_class=[dict(label=label,support=10,recall=.95) for label in FakeBackend.labels])
    report = dict(schema_version='1',candidate_artifact_sha256=candidate['artifact_sha256'],
        baseline_artifact_sha256=baseline['artifact_sha256'],labels_sha256=candidate['labels_sha256'],
        source_run_id=candidate['source_run_id'],preprocessing_version='rgb16-224-imagenet-v1',protocol_version='1.0',
        confidence_threshold=.7,margin_threshold=.15,baseline_confidence_threshold=.7,baseline_margin_threshold=.15,
        dataset_snapshot_sha256='a'*64,held_out=True,independent_negatives=True,positive_count=20,negative_count=30,
        baseline=metrics,candidate=metrics,**overrides)
    path = tmp_path / f'report-{uuid4()}.json'
    path.write_text(json.dumps(report))
    return str(path)


def register_and_validate(client,tmp_path,version='candidate-1',negative=True):
    response=client.post('/api/v1/workspace/models',json=model_files(tmp_path,version))
    assert response.status_code == 201,response.text
    snapshot=response.json()
    candidate=next(m for m in snapshot['models'] if m['model_version']==version)
    report=evaluation_report(tmp_path,snapshot,candidate)
    data=json.loads(Path(report).read_text())
    data['independent_negatives']=negative
    Path(report).write_text(json.dumps(data))
    response=client.post(f'/api/v1/workspace/models/{candidate["id"]}/validate',json=dict(report_path=report))
    assert response.status_code == 200,response.text
    if negative:
        from tests.evaluation_fixtures import seed_computed_validation
        seed_computed_validation(client,candidate['id'],data)
        response=client.get('/api/v1/workspace/models')
    snapshot=response.json()
    return snapshot,next(m for m in snapshot['models'] if m['id']==candidate['id'])


def wait_job(client,job_id):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        snapshot=client.get('/api/v1/workspace/models').json()
        job=next(j for j in snapshot['deployments'] if j['id']==job_id)
        if job['status'] in ('succeeded','failed'):
            return snapshot,job
        time.sleep(.05)
    pytest.fail('deployment worker did not finish')


def test_imported_numeric_report_cannot_authorize_approval_or_deploy(tmp_path):
    settings=managed_settings(tmp_path)
    with TestClient(create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=FakeBackend)) as client:
        login(client)
        response=client.post('/api/v1/workspace/models',json=model_files(tmp_path,'untrusted-candidate'))
        snapshot=response.json()
        candidate=next(m for m in snapshot['models'] if m['origin']=='candidate')
        report=evaluation_report(tmp_path,snapshot,candidate)
        response=client.post(f'/api/v1/workspace/models/{candidate["id"]}/validate',json={'report_path':report})
        candidate=next(m for m in response.json()['models'] if m['id']==candidate['id'])
        assert not candidate['validation']['passed']
        assert client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',json={'validation_id':candidate['validation']['id']}).status_code==409
        assert client.post('/api/v1/workspace/models/deployments',json={'request_id':str(uuid4()),'model_id':candidate['id'],'expected_revision':0}).status_code==409


def test_validation_requires_independent_negatives_and_separate_approval(tmp_path):
    settings=managed_settings(tmp_path)
    with TestClient(create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=FakeBackend)) as client:
        login(client)
        snapshot,candidate=register_and_validate(client,tmp_path,negative=False)
        assert candidate['validation']['passed'] is False
        assert any(c['name']=='independent_negatives' and not c['passed'] for c in candidate['validation']['checks'])
        assert client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',json=dict(validation_id=candidate['validation']['id'])).status_code==409
        assert client.get('/metadata').json()['model_version']=='baseline-1'


def test_explicit_deploy_switches_served_identity_and_rollback_reloads_previous(tmp_path):
    settings=replace(managed_settings(tmp_path),dev_test_enabled=True,dev_test_dir=tmp_path/'manual',
                     local_admin_enabled=False)
    app=create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=FakeBackend)
    with TestClient(app,client=('127.0.0.1',50000)) as client:
        login(client)
        actor_id=client.get('/api/v1/auth/me').json()['user']['id']
        snapshot,candidate=register_and_validate(client,tmp_path)
        assert candidate['validation']['passed'] is True
        payload=dict(request_id=str(uuid4()),model_id=candidate['id'],expected_revision=0)
        assert client.post('/api/v1/workspace/models/deployments',json=payload).status_code==409
        assert client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',json=dict(validation_id=candidate['validation']['id'])).status_code==200
        assert client.get('/health').json()['model_version']=='baseline-1'
        assert client.post('/api/v1/workspace/models/deployments',json=payload).status_code==202
        snapshot,job=wait_job(client,payload['request_id'])
        assert job['status']=='succeeded',job
        assert snapshot['target']['revision']==1
        assert snapshot['target']['active_model_id']==candidate['id']
        assert snapshot['target']['observed_model_id']==candidate['id']
        assert client.get('/metadata').json()['model_version']=='candidate-1'
        assert client.get('/health').json()['model_version']=='candidate-1'
        dev_config=client.get('/dev-tests/config').json()
        assert dev_config['model_version']=='candidate-1'
        assert dev_config['artifact_sha256']==candidate['artifact_sha256']
        with client.websocket_connect('/ws/inference') as socket:
            socket.send_json({'sequence':1})
            assert socket.receive_json()['model_version']=='candidate-1'
        assert client.post('/api/v1/workspace/models/deployments',json=payload).status_code==202
        assert client.get('/api/v1/workspace/models').json()['target']['revision']==1
        assert client.post('/api/v1/workspace/models/rollback',json=dict(request_id=str(uuid4()),expected_revision=0)).status_code==409
        rollback_id=str(uuid4())
        assert client.post('/api/v1/workspace/models/rollback',json=dict(request_id=rollback_id,expected_revision=1)).status_code==202
        snapshot,job=wait_job(client,rollback_id)
        assert job['status']=='succeeded',job
        assert snapshot['target']['revision']==2
        assert client.get('/metadata').json()['model_version']=='baseline-1'
        events=client.get('/api/v1/workspace/audit/events?group=deployment').json()['events']
        assert any(e['event_type']=='deployment.succeeded' and e['metadata']['source']=='server' for e in events)
        assert all(e['actor_id']==actor_id for e in events)


def test_failed_load_preserves_active_pointer_and_served_model(tmp_path):
    settings=managed_settings(tmp_path)
    def broken_factory(settings):
        if settings.model_version == 'baseline-1':
            return FakeBackend(settings)
        raise RuntimeError('do not leak /local/secret/path')
    with TestClient(create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=broken_factory)) as client:
        login(client)
        snapshot,candidate=register_and_validate(client,tmp_path)
        client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',json=dict(validation_id=candidate['validation']['id']))
        job_id=str(uuid4())
        assert client.post('/api/v1/workspace/models/deployments',json=dict(request_id=job_id,model_id=candidate['id'],expected_revision=0)).status_code==202
        snapshot,job=wait_job(client,job_id)
        assert job['status']=='failed'
        assert 'secret' not in job['error']
        assert snapshot['target']['revision']==0
        assert snapshot['target']['pending_job_id'] is None
        assert client.get('/metadata').json()['model_version']=='baseline-1'


def test_warmup_error_rejects_candidate_without_changing_pointer(tmp_path):
    settings=managed_settings(tmp_path)
    class BadBackend(FakeBackend):
        def predict(self,frames,sequence):
            return BackendPrediction(PredictionStatus.ERROR,None,None,[])
    def candidate_factory(settings):
        return FakeBackend(settings) if settings.model_version == 'baseline-1' else BadBackend(settings)
    with TestClient(create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=candidate_factory)) as client:
        login(client)
        snapshot,candidate=register_and_validate(client,tmp_path)
        client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',json=dict(validation_id=candidate['validation']['id']))
        job_id=str(uuid4())
        client.post('/api/v1/workspace/models/deployments',json=dict(request_id=job_id,model_id=candidate['id'],expected_revision=0))
        snapshot,job=wait_job(client,job_id)
        assert job['status']=='failed'
        assert snapshot['target']['revision']==0
        assert client.get('/health').json()['model_version']=='baseline-1'


def test_restart_restores_committed_pointer_and_tamper_fails_closed(tmp_path):
    settings=managed_settings(tmp_path)
    with TestClient(create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=FakeBackend)) as client:
        login(client)
        snapshot,candidate=register_and_validate(client,tmp_path)
        client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',json=dict(validation_id=candidate['validation']['id']))
        job_id=str(uuid4())
        client.post('/api/v1/workspace/models/deployments',json=dict(request_id=job_id,model_id=candidate['id'],expected_revision=0))
        assert wait_job(client,job_id)[1]['status']=='succeeded'
    restored=create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=FakeBackend)
    with TestClient(restored) as client:
        assert client.get('/metadata').json()['model_version']=='candidate-1'
        login(client)
        assert client.get('/api/v1/workspace/models').json()['target']['revision']==1
    (tmp_path/'candidate-1/model.onnx').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='SHA256'):
        with TestClient(create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=FakeBackend)):
            pytest.fail('managed runtime must not start with corrupt active artifact')


def test_loading_job_rechecks_revoked_permission_and_serializes_requests(tmp_path):
    settings=managed_settings(tmp_path)
    loading,release=Event(),Event()
    def slow_factory(settings):
        if settings.model_version != 'baseline-1':
            loading.set()
            assert release.wait(5)
        return FakeBackend(settings)
    app=create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=slow_factory)
    with TestClient(app) as client:
        login(client)
        snapshot,candidate=register_and_validate(client,tmp_path)
        client.post(f'/api/v1/workspace/models/{candidate["id"]}/approve',json=dict(validation_id=candidate['validation']['id']))
        job_id=str(uuid4())
        payload=dict(request_id=job_id,model_id=candidate['id'],expected_revision=0)
        client.post('/api/v1/workspace/models/deployments',json=payload)
        assert loading.wait(3)
        assert client.get('/health').json()['model_version']=='baseline-1'
        assert client.post('/api/v1/workspace/models/deployments',json={**payload,'request_id':str(uuid4())}).status_code==409
        assert client.post('/api/v1/workspace/models/deployments',json={**payload,'expected_revision':1}).status_code==409
        with app.state.platform_database.session() as session:
            membership=session.scalar(select(Membership))
            membership.role='reviewer'
            session.commit()
        release.set()
        snapshot,job=wait_job(client,job_id)
        assert job['status']=='failed'
        assert snapshot['target']['revision']==0
        assert client.get('/health').json()['model_version']=='baseline-1'


def test_registry_rbac_and_workspace_isolation(tmp_path):
    app=create_app(configured(tmp_path))
    with TestClient(app) as client:
        login(client)
        response=client.post('/api/v1/workspace/models',json=model_files(tmp_path,'private-candidate'))
        model_id=response.json()['models'][0]['id']
        with app.state.platform_database.session() as session:
            session.add(Workspace(id='other',name='Other',environment='development'))
            session.flush()
            model=session.get(RegisteredModel,model_id)
            model.workspace_id='other'
            membership=session.scalar(select(Membership))
            membership.role='viewer'
            session.commit()
        snapshot=client.get('/api/v1/workspace/models').json()
        assert snapshot['models']==[]
        assert not any(snapshot['permissions'].values())
        assert client.post('/api/v1/workspace/models',json=model_files(tmp_path,'viewer-candidate')).status_code==403
        assert client.post(f'/api/v1/workspace/models/{model_id}/approve',json=dict(validation_id=str(uuid4()))).status_code==403
        with app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role='model_admin'
            session.commit()
        assert client.post(f'/api/v1/workspace/models/{model_id}/approve',json=dict(validation_id=str(uuid4()))).status_code==404


def test_offline_runtime_cannot_accept_deployment(tmp_path):
    settings=managed_settings(tmp_path)
    app=create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=FakeBackend)
    with TestClient(app) as client:
        login(client)
        snapshot,candidate=register_and_validate(client,tmp_path)
        with app.state.platform_database.session() as session:
            target=session.get(DeploymentTarget,('local','production-local'))
            target.heartbeat_at=utc_now()-timedelta(seconds=60)
            session.commit()
        response=client.post('/api/v1/workspace/models/deployments',json=dict(request_id=str(uuid4()),model_id=candidate['id'],expected_revision=0))
        assert response.status_code==503
        assert client.get('/api/v1/workspace/models').json()['deployments']==[]


@pytest.mark.parametrize('change',[
    {'held_out':False}, {'independent_negatives':False}, {'negative_count':0}, {'dataset_snapshot_sha256':''},
    {'candidate_artifact_sha256':'f'*64}, {'baseline_artifact_sha256':'f'*64}, {'confidence_threshold':.2},
    {'candidate':{'macro_f1':float('nan')}}, {'candidate':{'macro_f1':.4}},
])
def test_gate_rejects_missing_mismatched_or_nonfinite_evidence(tmp_path,change):
    settings=managed_settings(tmp_path)
    with TestClient(create_app(settings,backend=FakeBackend(settings),runtime_backend_factory=FakeBackend)) as client:
        login(client)
        snapshot=client.post('/api/v1/workspace/models',json=model_files(tmp_path,'candidate-1')).json()
        candidate=next(m for m in snapshot['models'] if m['origin']=='candidate')
        report=evaluation_report(tmp_path,snapshot,candidate)
        data=json.loads(Path(report).read_text())
        data.update(change)
        Path(report).write_text(json.dumps(data))
        response=client.post(f'/api/v1/workspace/models/{candidate["id"]}/validate',json=dict(report_path=report))
        assert response.status_code==200,response.text
        model=next(m for m in response.json()['models'] if m['id']==candidate['id'])
        assert model['validation']['passed'] is False
        assert model['approved_validation_id'] is None
