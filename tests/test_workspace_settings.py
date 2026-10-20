from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.platform_db import AuditEvent, Membership, utc_now
from test_local_admin import local_settings
from test_workspace_data import prepare, save
from test_workspace_team import add_member, PASSWORD

BASE = '/api/v1/workspace/settings'
DATA = '/api/v1/workspace/data'


@pytest.fixture
def settings(monkeypatch, tmp_path):
    return replace(local_settings(monkeypatch, tmp_path), collection_enabled=True,
                   collection_dir=tmp_path / 'media')


def update(client, revision=0, **fields):
    return client.post(BASE + '/update', json={
        'request_id': str(uuid4()), 'expected_revision': revision, **fields})


def test_settings_defaults_and_persisted_name_survive_bootstrap(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get(BASE)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['revision'] == 0 and body['permissions']['manage']
        assert body['workspace']['name'] == settings.workspace_name
        assert body['retention']['automatic_deletion'] is False
        assert body['runtime_defaults']['capture_mode'] == 'manual'
        response = update(client, workspace={'name': '  Workspace Việt  ', 'timezone': 'Asia/Ho_Chi_Minh'},
                          runtime_defaults={'capture_mode': 'automatic'})
        assert response.status_code == 200, response.text
        assert response.json()['revision'] == 1
        assert client.get('/api/v1/workspace').json()['name'] == 'Workspace Việt'
        assert client.get('/api/v1/workspace/capabilities').json()['capabilities']['settings']
    with TestClient(create_app(settings)) as client:
        body = client.get(BASE).json()
        assert body['workspace'] == {'name': 'Workspace Việt', 'timezone': 'Asia/Ho_Chi_Minh'}
        assert body['revision'] == 1
        assert body['runtime_defaults']['capture_mode'] == 'automatic'


def test_revision_receipts_audit_and_concurrent_writers(settings):
    with TestClient(create_app(settings)) as client:
        payload = {'request_id': str(uuid4()), 'expected_revision': 0,
                   'runtime_defaults': {'capture_mode': 'automatic'}}
        assert client.post(BASE + '/update', json=payload).status_code == 200
        assert client.post(BASE + '/update', json=payload).status_code == 200
        assert client.post(BASE + '/update', json={**payload, 'runtime_defaults': {'capture_mode': 'manual'}}).status_code == 409
        assert update(client, runtime_defaults={'capture_mode': 'manual'}).status_code == 409
        with client.app.state.platform_database.session() as session:
            events = session.scalars(select(AuditEvent).where(AuditEvent.event_type == 'settings.updated')).all()
            assert len(events) == 1
            assert events[0].metadata_json['before']['runtime_defaults']['capture_mode'] == 'manual'
            assert events[0].metadata_json['after']['runtime_defaults']['capture_mode'] == 'automatic'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: update(client, 1, runtime_defaults={'capture_mode': 'manual'}).status_code, range(2)))
        assert sorted(results) == [200, 409]


@pytest.mark.parametrize('fields', [
    {}, {'workspace_id': 'other'}, {'environment': 'production'},
    {'workspace': {'name': ' ', 'timezone': 'UTC'}},
    {'workspace': {'name': 'Bad\nname', 'timezone': 'UTC'}},
    {'workspace': {'name': 'Valid', 'timezone': 'not/a-zone'}},
    {'retention': {'draft_samples_days': 0}}, {'retention': {'audit_events_days': 3651}},
    {'retention': {'automatic_deletion': True}},
    {'collection_policy': {'enabled': 'yes', 'require_consent': False, 'default_quota_per_label': 100}},
    {'collection_policy': {'enabled': True, 'require_consent': False, 'default_quota_per_label': True}},
    {'runtime_defaults': {'capture_mode': 'automatic', 'model_version': 'other'}},
    {'runtime_defaults': {'capture_mode': 'unknown'}},
])
def test_settings_reject_invalid_or_unapproved_fields(settings, fields):
    with TestClient(create_app(settings)) as client:
        assert update(client, **fields).status_code == 422
        assert client.get(BASE).json()['revision'] == 0


@pytest.mark.parametrize('fields', [
    {'collection_policy': {'default_quota_per_label': 19}},
    {'retention': {'draft_samples_days': 7, 'audit_events_days': 90}},
    {'runtime_defaults': {}},
])
def test_incomplete_sections_cannot_reset_existing_policy(settings, fields):
    with TestClient(create_app(settings)) as client:
        assert update(client,
            collection_policy={'enabled': False, 'require_consent': True, 'default_quota_per_label': 17},
            retention={'draft_samples_days': 30, 'audit_events_days': 90, 'automatic_deletion': False},
            runtime_defaults={'capture_mode': 'automatic'}).status_code == 200
        before = client.get(BASE).json()
        assert update(client, 1, **fields).status_code == 422
        assert client.get(BASE).json() == before


@pytest.mark.parametrize('role', ['owner', 'admin', 'operator', 'reviewer', 'viewer', 'model_admin'])
def test_management_and_own_preferences_are_separate(settings, role):
    settings = replace(settings, local_admin_enabled=False, bootstrap_admin_email='owner@example.com',
                       bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        with client.app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = role
            session.commit()
        assert client.post('/api/v1/auth/login', json={'email': 'owner@example.com', 'password': PASSWORD}).status_code == 200
        body = client.get(BASE).json()
        manage = role in ('owner', 'admin')
        assert body['permissions']['manage'] == manage
        assert (body['workspace'] is not None) == manage
        assert (body['retention'] is not None) == manage
        assert client.post(BASE + '/update', json={}).status_code == (422 if manage else 403)
        assert client.get(BASE + '/retention/preview').status_code == (200 if manage else 403)
        response = client.post(BASE + '/notifications', json={'request_id': str(uuid4()), 'expected_revision': 0,
            'preferences': {'collection_completed': False, 'evaluation_finished': True, 'integration_failed': False}})
        assert response.status_code == 200, response.text
        assert response.json()['notifications']['revision'] == 1
        assert response.json()['revision'] == 0
        assert response.json()['notifications']['delivery'] == 'not_configured'


def test_scope_personal_preference_privacy_and_service_credentials(settings):
    with TestClient(create_app(settings)) as client:
        assert update(client, workspace={'name': 'Private workspace', 'timezone': 'UTC'}).status_code == 200
        assert client.post(BASE + '/notifications', json={'request_id': str(uuid4()), 'expected_revision': 0,
            'preferences': {'collection_completed': False, 'evaluation_finished': False, 'integration_failed': False}}).status_code == 200
        assert client.get(BASE, headers={'Authorization': 'Bearer bad'}).status_code == 403
        assert client.post(BASE + '/update', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
        assert client.post(BASE + '/notifications', json={'user_id': 'other'}).status_code == 422
    with TestClient(create_app(replace(settings, workspace_id='other'))) as other:
        body = other.get(BASE).json()
        assert body['revision'] == 0 and body['workspace']['name'] == settings.workspace_name
        assert body['notifications']['revision'] == 0 and body['notifications']['preferences']['collection_completed']
    anonymous = replace(settings, local_admin_enabled=False)
    with TestClient(create_app(anonymous)) as client:
        assert client.get(BASE).status_code == 401


def test_other_users_cannot_read_personal_preferences_or_audit(settings):
    settings = replace(settings, local_admin_enabled=False, bootstrap_admin_email='owner@example.com', bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        add_member(client, settings, email='one@example.com')
        add_member(client, settings, email='two@example.com')
        client.post('/api/v1/auth/login', json={'email': 'one@example.com', 'password': PASSWORD})
        payload = {'request_id': str(uuid4()), 'expected_revision': 0,
                   'preferences': {'collection_completed': False, 'evaluation_finished': False, 'integration_failed': False}}
        assert client.post(BASE + '/notifications', json=payload).status_code == 200
        assert client.post(BASE + '/notifications', json=payload).status_code == 200
        client.post('/api/v1/auth/login', json={'email': 'two@example.com', 'password': PASSWORD})
        assert client.get(BASE).json()['notifications']['revision'] == 0
        events = client.get('/api/v1/workspace/audit/events').json()['events']
        assert not any(e['event_type'] == 'settings.notifications_updated' for e in events)
        assert client.post(BASE + '/notifications', json=payload).status_code == 409
        assert client.get(BASE).json()['notifications']['revision'] == 0


def test_effective_policy_consent_quota_and_hard_process_cap(settings):
    with TestClient(create_app(settings)) as client:
        labels, _, dataset, existing = prepare(client, quota=5)
        policy = {'enabled': True, 'require_consent': True, 'default_quota_per_label': 17}
        assert update(client, collection_policy=policy).status_code == 200
        created = client.post(DATA + '/datasets', json={'request_id': str(uuid4()), 'name': 'New defaults', 'label_version_id': labels})
        assert created.status_code == 201, created.text
        assert {row['name']: row['quota_per_label'] for row in created.json()['datasets']} == {'Đợt thu 1': 5, 'New defaults': 17}
        start = {'request_id': str(uuid4()), 'dataset_version_id': dataset}
        assert client.post(DATA + '/sessions', json=start).status_code == 403
        assert save(client, existing).status_code == 403
        assert client.post(DATA + f'/sessions/{existing}/state', json={'state': 'running'}).status_code == 403
        assert client.post(DATA + f'/sessions/{existing}/state', json={'state': 'stopped'}).status_code == 200
        start['consent'] = True
        assert client.post(DATA + '/sessions', json=start).status_code == 201
        assert save(client, start['request_id']).status_code == 200
        assert update(client, 1, collection_policy={**policy, 'enabled': False}).status_code == 200
        assert not client.get(DATA).json()['collection_enabled']
        assert save(client, start['request_id'], sample_key=str(uuid4())).status_code == 403
        assert client.post(DATA + '/sessions', json={**start, 'request_id': str(uuid4())}).status_code == 403
    with TestClient(create_app(replace(settings, collection_enabled=False))) as client:
        assert update(client, 2, collection_policy={**policy, 'enabled': True}).status_code == 200
        assert client.get(BASE + '/effective').json()['collection']['enabled'] is False
        assert client.post(DATA + '/sessions', json={**start, 'request_id': str(uuid4())}).status_code == 403


def test_retention_preview_is_read_only_and_protects_sealed_and_active(settings):
    from app.workspace_data_db import DataSample, DatasetSnapshot
    with TestClient(create_app(settings)) as client:
        _, _, old, ended = prepare(client)
        assert save(client, ended).status_code == 200
        client.post(DATA + f'/sessions/{ended}/state', json={'state': 'stopped'})
        _, _, sealed, session_id = prepare(client)
        assert save(client, session_id, sample_key=str(uuid4())).status_code == 200
        client.post(DATA + f'/sessions/{session_id}/state', json={'state': 'stopped'})
        assert client.post(DATA + f'/datasets/{sealed}/snapshot', json={'request_id': str(uuid4())}).status_code == 201
        _, _, active, session_id = prepare(client)
        assert save(client, session_id, sample_key=str(uuid4())).status_code == 200
        with client.app.state.platform_database.session() as session:
            for row in session.scalars(select(DataSample)).all():
                row.created_at = utc_now() - timedelta(days=45)
            session.add(AuditEvent(id=str(uuid4()), workspace_id=settings.workspace_id,
                event_type='test.old', actor_type='system', outcome='success', occurred_at=utc_now()-timedelta(days=45)))
            session.commit()
        assert update(client, retention={'draft_samples_days': 30, 'audit_events_days': 30, 'automatic_deletion': False}).status_code == 200
        before = {str(p): p.read_bytes() for p in settings.collection_dir.rglob('*') if p.is_file()}
        result = client.get(BASE + '/retention/preview')
        assert result.status_code == 200, result.text
        assert result.json()['candidates'] == {'draft_samples': 1, 'audit_events': 1}
        assert result.json()['protected']['snapshots'] == 1
        assert result.json()['automatic_deletion'] is False
        assert before == {str(p): p.read_bytes() for p in settings.collection_dir.rglob('*') if p.is_file()}
        with client.app.state.platform_database.session() as session:
            assert session.scalar(select(func.count()).select_from(DataSample)) == 3
            assert session.scalar(select(func.count()).select_from(DatasetSnapshot)) == 1
        assert client.post(BASE + '/retention/delete', json={}).status_code == 404


def test_settings_body_limit_and_metadata_are_unchanged(settings):
    with TestClient(create_app(settings)) as client:
        metadata = client.get('/metadata').json()
        assert client.post(BASE + '/update', content='x'*8193).status_code == 413
        assert update(client, runtime_defaults={'capture_mode': 'automatic'}).status_code == 200
        assert client.get('/metadata').json() == metadata


def test_settings_recheck_role_and_revoked_session_inside_writer_lock(settings):
    from app.platform_auth import SESSION_COOKIE_NAME, resolve_local_admin, resolve_principal
    from app.workspace_settings import WorkspaceSettings
    from contracts.v1.settings import UpdateWorkspaceSettings

    payload = UpdateWorkspaceSettings(request_id=uuid4(), expected_revision=0, runtime_defaults={'capture_mode': 'automatic'})
    with TestClient(create_app(settings)) as client:
        database = client.app.state.platform_database
        actor = resolve_local_admin(database, settings.workspace_id)
        with database.session() as session:
            session.scalar(select(Membership)).role = 'viewer'
            session.commit()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as denied:
            WorkspaceSettings(database, settings).update(actor, payload)
        assert denied.value.status_code == 403
    configured = replace(settings, local_admin_enabled=False, bootstrap_admin_email='owner@example.com', bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(configured)) as client:
        client.post('/api/v1/auth/login', json={'email': 'owner@example.com', 'password': PASSWORD})
        database = client.app.state.platform_database
        token = client.cookies.get(SESSION_COOKIE_NAME)
        actor = resolve_principal(database, token, settings.workspace_id)
        client.post('/api/v1/auth/logout')
        with pytest.raises(HTTPException) as denied:
            WorkspaceSettings(database, configured, token).update(actor, payload)
        assert denied.value.status_code == 401
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == 'settings.updated')) == 0


def test_failed_audit_rolls_back_settings_and_receipt(settings, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.workspace_settings import WorkspaceSettings

    original = WorkspaceSettings.record_change
    with TestClient(create_app(settings)) as client:
        payload = {'request_id': str(uuid4()), 'expected_revision': 0, 'workspace': {'name': 'Never saved', 'timezone': 'UTC'}}
        def fail(*args, **kwargs):
            raise OperationalError('audit', {}, RuntimeError('fixture failure'))
        monkeypatch.setattr(WorkspaceSettings, 'record_change', fail)
        assert client.post(BASE + '/update', json=payload).status_code == 503
        assert client.get(BASE).json()['revision'] == 0
        assert client.get('/api/v1/workspace').json()['name'] == settings.workspace_name
        monkeypatch.setattr(WorkspaceSettings, 'record_change', original)
        assert client.post(BASE + '/update', json=payload).status_code == 200


def test_default_quota_retry_is_stable_and_explicit_quota_is_not_reinterpreted(settings):
    with TestClient(create_app(settings)) as client:
        labels, _, _, _ = prepare(client)
        body = {'request_id': str(uuid4()), 'name': 'Inherited', 'label_version_id': labels}
        assert client.post(DATA + '/datasets', json=body).status_code == 201
        assert update(client, collection_policy={'enabled': True, 'require_consent': False, 'default_quota_per_label': 19}).status_code == 200
        retried = client.post(DATA + '/datasets', json=body)
        assert retried.status_code == 201
        row = next(row for row in retried.json()['datasets'] if row['id'] == body['request_id'])
        assert row['quota_per_label'] == 100
        assert client.post(DATA + '/datasets', json={**body, 'quota_per_label': 100}).status_code == 409
        explicit = {**body, 'request_id': str(uuid4()), 'quota_per_label': 100}
        assert client.post(DATA + '/datasets', json=explicit).status_code == 201
        assert client.post(DATA + '/datasets', json={key: value for key, value in explicit.items() if key != 'quota_per_label'}).status_code == 409
        assert client.post(DATA + '/datasets', json=explicit).status_code == 201


def test_pre_settings_dataset_receipt_accepts_identical_retry_after_upgrade(settings):
    from app.workspace_data import fingerprint
    from app.workspace_data_db import DatasetVersion
    from contracts.v1.data import CreateDatasetRequest
    with TestClient(create_app(settings)) as client:
        labels, _, _, _ = prepare(client)
        body = {'request_id': str(uuid4()), 'name': 'Legacy inherited', 'label_version_id': labels}
        assert client.post(DATA + '/datasets', json=body).status_code == 201
        with client.app.state.platform_database.session() as session:
            row = session.get(DatasetVersion, body['request_id'])
            row.request_hash = fingerprint(CreateDatasetRequest.model_validate(body))
            session.commit()
        assert update(client, collection_policy={'enabled': True, 'require_consent': False, 'default_quota_per_label': 19}).status_code == 200
        retried = client.post(DATA + '/datasets', json=body)
        assert retried.status_code == 201
        row = next(row for row in retried.json()['datasets'] if row['id'] == body['request_id'])
        assert row['quota_per_label'] == 100
        assert client.post(DATA + '/datasets', json={**body, 'name': 'Different request'}).status_code == 409


def test_settings_upgrade_keeps_existing_collection_rows_and_rejects_lossy_downgrade(settings):
    from alembic import command
    from app.migrate import migration_config
    from app.platform_db import create_database
    from app.workspace_data_db import DataSession
    with TestClient(create_app(settings)) as client:
        _, _, _, identity = prepare(client)
        assert save(client, identity).status_code == 200
    database = create_database(settings.database_url)
    config = migration_config()
    with database.engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.commit()
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        config.attributes['connection'] = connection
        command.downgrade(config, '0009_workspace_team')
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        connection.commit()
        connection.exec_driver_sql('PRAGMA foreign_keys=ON')
        connection.commit()
    from app.migrate import upgrade_database
    upgrade_database(database)
    with database.session() as session:
        row = session.get(DataSession, identity)
        assert row.state == 'running' and row.consented_at is None
    with TestClient(create_app(settings)) as client:
        assert client.get(DATA).json()['datasets'][0]['sample_count'] == 1
        assert update(client, runtime_defaults={'capture_mode': 'automatic'}).status_code == 200
    with database.engine.begin() as connection:
        config.attributes['connection'] = connection
        with pytest.raises(RuntimeError, match='Export settings'):
            command.downgrade(config, '0009_workspace_team')
    database.dispose()
