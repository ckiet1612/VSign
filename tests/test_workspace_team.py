from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.platform_db import Membership, User, utc_now
from test_local_admin import local_settings

BASE = '/api/v1/workspace/team'
PUBLIC = '/api/v1/invitations'
PASSWORD = 'correct-password-123'


@pytest.fixture
def settings(monkeypatch, tmp_path):
    return local_settings(monkeypatch, tmp_path)


def add_member(client, settings, role='operator', email=None, workspace=None):
    identity = str(uuid4())
    with client.app.state.platform_database.session() as session:
        session.add(User(id=identity, email=email or identity+'@example.com', display_name='Thành viên',
                         password_hash=client.app.state.password_hasher.hash(PASSWORD)))
        session.flush()
        session.add(Membership(workspace_id=workspace or settings.workspace_id, user_id=identity, role=role))
        session.commit()
    return identity


def invitation(**extra):
    return {'request_id':str(uuid4()), 'email':'new@example.com', 'role':'operator', **extra}


def test_team_overview_roles_and_protected_local_admin(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get(BASE)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['workspace_id'] == settings.workspace_id and body['permissions']['manage']
        assert body['members'][0]['protected'] and body['members'][0]['revision'] == 0
        roles = client.get(BASE+'/roles').json()['roles']
        assert {r['id'] for r in roles} == {'owner', 'admin', 'operator', 'reviewer', 'viewer'}
        assert all(not any(p.startswith('models:') and p != 'models:read' for p in r['permissions']) for r in roles)
        identity = body['members'][0]['id']
        assert client.post(BASE+f'/members/{identity}/update', json={
            'request_id':str(uuid4()), 'expected_revision':0, 'status':'removed'}).status_code == 403


def test_member_update_scoped_status_revision_and_idempotency(settings):
    with TestClient(create_app(settings)) as client:
        identity = add_member(client, settings)
        payload = {'request_id':str(uuid4()), 'expected_revision':0, 'role':'viewer'}
        response = client.post(BASE+f'/members/{identity}/update', json=payload)
        assert response.status_code == 200, response.text
        assert client.post(BASE+f'/members/{identity}/update', json=payload).status_code == 200
        assert client.post(BASE+f'/members/{identity}/update', json={**payload,'role':'reviewer'}).status_code == 409
        assert client.post(BASE+f'/members/{identity}/update', json={**payload,'request_id':str(uuid4())}).status_code == 409
        response = client.post(BASE+f'/members/{identity}/update', json={
            'request_id':str(uuid4()), 'expected_revision':1, 'status':'suspended'})
        assert response.status_code == 200
        with client.app.state.platform_database.session() as session:
            member = session.scalar(select(Membership).where(Membership.user_id == identity))
            assert member.status == 'suspended' and member.revision == 2
            assert session.get(User, identity).is_active
        assert client.post(BASE+f'/members/{identity}/update', json={
            'request_id':str(uuid4()), 'expected_revision':2, 'role':'model_admin'}).status_code == 422


@pytest.mark.parametrize('role', ['operator','reviewer','viewer','model_admin'])
def test_non_managers_cannot_read_or_manage_team(settings, role):
    settings = replace(settings, local_admin_enabled=False, bootstrap_admin_email='owner@example.com',
                       bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        with client.app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role = role
            session.commit()
        assert client.post('/api/v1/auth/login',json={'email':'owner@example.com','password':PASSWORD}).status_code == 200
        for path in ('','/roles','/invitations','/audit'):
            assert client.get(BASE+path).status_code == 403
        assert client.post(BASE+'/invitations',json=invitation()).status_code == 403


def test_invite_once_only_hashed_and_no_implicit_account_login(settings):
    with TestClient(create_app(settings)) as client:
        payload = invitation()
        response = client.post(BASE+'/invitations', json=payload)
        assert response.status_code == 201, response.text
        token = response.json()['secret']
        assert len(token) >= 43
        assert token not in client.get(BASE+'/invitations').text
        assert client.post(BASE+'/invitations',json=payload).json()['secret'] is None
        assert client.post(PUBLIC+'/inspect',json={'token':token}).json()['email'] == payload['email']
        accept = {'request_id':str(uuid4()), 'token':token, 'password':PASSWORD,'display_name':'Người mới'}
        response = client.post(PUBLIC+'/accept',json=accept)
        assert response.status_code == 200, response.text
        assert 'set-cookie' not in response.headers
        assert client.post(PUBLIC+'/accept',json=accept).status_code == 200
        assert client.post(PUBLIC+'/accept',json={**accept,'request_id':str(uuid4())}).status_code == 409
        assert token not in client.get(BASE+'/audit').text
        from pathlib import Path
        assert token.encode() not in Path(settings.database_url.removeprefix('sqlite:///')).read_bytes()
        assert client.get('/api/v1/auth/me').json()['auth_mode'] == 'local_admin'


def test_existing_account_invitation_cannot_reset_password(settings):
    with TestClient(create_app(settings)) as client:
        identity = add_member(client, settings)
        with client.app.state.platform_database.session() as session:
            member = session.scalar(select(Membership).where(Membership.user_id == identity))
            member.status = 'removed'
            session.commit()
            email = session.get(User,identity).email
        token = client.post(BASE+'/invitations',json=invitation(email=email)).json()['secret']
        payload = {'request_id':str(uuid4()),'token':token,'password':'attacker-password-123','display_name':'Attacker'}
        assert client.post(PUBLIC+'/accept',json=payload).status_code == 403
        assert client.post(PUBLIC+'/accept',json={**payload,'password':PASSWORD}).status_code == 200
        with client.app.state.platform_database.session() as session:
            assert session.get(User,identity).display_name == 'Thành viên'


def test_invitation_revoke_expiry_and_grant_ceiling(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post(BASE+'/invitations',json=invitation(role='admin')).status_code == 403
        assert client.post(BASE+'/invitations',json=invitation(role='owner')).status_code == 422
        assert client.post(BASE+'/invitations',json=invitation(role='model_admin')).status_code == 422
        response = client.post(BASE+'/invitations',json=invitation())
        assert response.status_code == 201
        row = response.json()
        assert client.post(BASE+f'/invitations/{row["id"]}/revoke',json={'request_id':str(uuid4())}).status_code == 200
        assert client.post(PUBLIC+'/inspect',json={'token':row['secret']}).status_code == 410


def test_member_suspension_revokes_only_workspace_session(settings):
    from app.platform_auth import create_session, resolve_principal
    with TestClient(create_app(settings)) as client:
        identity = add_member(client,settings)
        database = client.app.state.platform_database
        with database.session() as session:
            user = session.get(User,identity)
        token = create_session(database,user,settings.workspace_id,3600)
        assert resolve_principal(database,token,settings.workspace_id)
        response = client.post(BASE+f'/members/{identity}/update',json={
            'request_id':str(uuid4()),'expected_revision':0,'status':'suspended'})
        assert response.status_code == 200
        assert resolve_principal(database,token,settings.workspace_id) is None


def test_owner_grants_admin_but_admin_cannot_manage_peers_or_owners(settings):
    settings = replace(settings,local_admin_enabled=False,bootstrap_admin_email='owner@example.com',bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        client.post('/api/v1/auth/login',json={'email':'owner@example.com','password':PASSWORD})
        owner = client.get('/api/v1/auth/me').json()['user']['id']
        admin = add_member(client,settings,role='admin',email='admin@example.com')
        other = add_member(client,settings)
        internal = add_member(client,settings,role='model_admin')
        assert internal not in {r['id'] for r in client.get(BASE).json()['members']}
        assert client.post(BASE+'/invitations',json=invitation(role='admin')).status_code == 201
        client.post('/api/v1/auth/login',json={'email':'admin@example.com','password':PASSWORD})
        for identity in (owner,admin,internal):
            response = client.post(BASE+f'/members/{identity}/update',json={
                'request_id':str(uuid4()),'expected_revision':0,'status':'removed'})
            assert response.status_code in (403,404)
        assert client.post(BASE+f'/members/{other}/update',json={
            'request_id':str(uuid4()),'expected_revision':0,'role':'admin'}).status_code == 403


def test_tenant_isolation_and_api_keys_never_get_management(settings):
    with TestClient(create_app(settings)) as first:
        identity = add_member(first,settings)
        invite = first.post(BASE+'/invitations',json=invitation()).json()
        from test_workspace_integrations import key_payload
        key = first.post('/api/v1/workspace/integrations/keys',json=key_payload()).json()['secret']
        assert first.get(BASE,headers={'Authorization':'Bearer '+key}).status_code == 403
        with TestClient(create_app(replace(settings,workspace_id='other'))) as other:
            assert identity not in {r['id'] for r in other.get(BASE).json()['members']}
            assert other.post(BASE+f'/members/{identity}/update',json={
                'request_id':str(uuid4()),'expected_revision':0,'status':'removed'}).status_code == 404
            assert other.post(BASE+f'/invitations/{invite["id"]}/revoke',json={'request_id':str(uuid4())}).status_code == 404
            assert other.post(PUBLIC+'/inspect',json={'token':invite['secret']}).status_code == 404


def test_suspend_is_workspace_local_and_old_session_never_returns(settings):
    from app.platform_db import Workspace
    from app.platform_auth import create_session, resolve_principal
    with TestClient(create_app(settings)) as client:
        identity = add_member(client,settings)
        database = client.app.state.platform_database
        with database.session() as session:
            session.add(Workspace(id='other',name='Other',environment='development'))
            session.flush()
            session.add(Membership(user_id=identity,workspace_id='other',role='viewer'))
            session.commit()
            user = session.get(User,identity)
        token = create_session(database,user,settings.workspace_id,3600)
        other_token = create_session(database,user,'other',3600)
        for revision,status in ((0,'suspended'),(1,'active')):
            assert client.post(BASE+f'/members/{identity}/update',json={
                'request_id':str(uuid4()),'expected_revision':revision,'status':status}).status_code == 200
        assert resolve_principal(database,token,settings.workspace_id) is None
        assert resolve_principal(database,other_token,'other')


def test_expired_invite_and_issuer_loss_fail_closed(settings):
    from app.team_db import TeamInvitation
    with TestClient(create_app(settings)) as client:
        payload = invitation()
        row = client.post(BASE+'/invitations',json=payload).json()
        database = client.app.state.platform_database
        with database.session() as session:
            session.get(TeamInvitation,row['id']).expires_at = utc_now()-timedelta(seconds=1)
            session.commit()
        assert client.post(PUBLIC+'/inspect',json={'token':row['secret']}).status_code == 410
        row = client.post(BASE+'/invitations',json=invitation()).json()
        with database.session() as session:
            session.scalar(select(Membership)).role = 'viewer'
            session.commit()
        assert client.post(PUBLIC+'/accept',json={'request_id':str(uuid4()),'token':row['secret'],
            'password':PASSWORD,'display_name':'New'}).status_code == 409


def test_invalid_tokens_consume_persisted_budget(settings,monkeypatch):
    monkeypatch.setattr('app.team.time.time',lambda:1800000001)
    with TestClient(create_app(settings)) as client:
        for _ in range(20):
            assert client.post(PUBLIC+'/inspect',json={'token':'x'*43}).status_code == 404
    with TestClient(create_app(settings)) as other:
        response = other.post(PUBLIC+'/inspect',json={'token':'x'*43})
        assert response.status_code == 429 and int(response.headers['Retry-After']) > 0


def test_sensitive_audit_hidden_in_both_team_and_activity(settings):
    settings = replace(settings,local_admin_enabled=False,bootstrap_admin_email='owner@example.com',bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        client.post('/api/v1/auth/login',json={'email':'owner@example.com','password':PASSWORD})
        identity = add_member(client,settings,email='viewer@example.com',role='viewer')
        assert client.post(BASE+'/invitations',json=invitation()).status_code == 201
        assert client.post(BASE+f'/members/{identity}/update',json={
            'request_id':str(uuid4()),'expected_revision':0,'role':'reviewer'}).status_code == 200
        rows = client.get(BASE+'/audit',params={'member_id':identity}).json()['events']
        assert len(rows) == 1 and rows[0]['before']['role'] == 'viewer' and rows[0]['after']['role'] == 'reviewer'
        client.post('/api/v1/auth/login',json={'email':'viewer@example.com','password':PASSWORD})
        assert client.get(BASE+'/audit').status_code == 403
        events = client.get('/api/v1/workspace/audit/events?group=permission').json()['events']
        assert not any(r['event_type'] in ('permission.member_updated','permission.invitation_created') for r in events)


def test_audit_time_filter_normalizes_timezones(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get(BASE+'/audit',params={'from_at':'2020-01-01T00:00:00','to_at':'2030-01-01T00:00:00Z'})
        assert response.status_code == 200, response.text
        assert client.get(BASE+'/audit?cursor=null').status_code == 422


def test_concurrent_accept_never_replays_membership(settings):
    from concurrent.futures import ThreadPoolExecutor
    with TestClient(create_app(settings)) as client:
        invite = client.post(BASE+'/invitations',json=invitation()).json()
        def accept(_):
            return client.post(PUBLIC+'/accept',json={'request_id':str(uuid4()),'token':invite['secret'],
                'password':PASSWORD,'display_name':'New'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(accept,range(2)))
        assert statuses.count(200) == 1 and all(s in (200,409) for s in statuses)
        users = [r for r in client.get(BASE).json()['members'] if r['email'] == 'new@example.com']
        assert len(users) == 1


def test_concurrent_accept_versus_revoke_is_serialized(settings):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.team_db import TeamInvitation
    with TestClient(create_app(settings)) as client:
        invite = client.post(BASE+'/invitations',json=invitation()).json()
        barrier = Barrier(2)
        def accept():
            barrier.wait()
            return client.post(PUBLIC+'/accept',json={'request_id':str(uuid4()),'token':invite['secret'],
                'password':PASSWORD,'display_name':'New'}).status_code
        def revoke():
            barrier.wait()
            return client.post(BASE+f'/invitations/{invite["id"]}/revoke',json={'request_id':str(uuid4())}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            a,b = pool.submit(accept),pool.submit(revoke)
            accepted,revoked = a.result(),b.result()
        assert (accepted,revoked) in ((200,409),(410,200))
        with client.app.state.platform_database.session() as session:
            row = session.get(TeamInvitation,invite['id'])
            assert bool(row.accepted_at) != bool(row.revoked_at)


def test_members_invitations_and_history_paginate_without_duplicates(settings):
    from app.platform_db import AuditEvent
    from app.team_db import TeamInvitation
    with TestClient(create_app(settings)) as client:
        database = client.app.state.platform_database
        actor = client.get(BASE).json()['members'][0]['id']
        with database.session() as session:
            for i in range(55):
                identity = str(uuid4())
                session.add(User(id=identity,email=f'page-{i}@example.com',display_name=f'Page {i}',password_hash='unused'))
                session.flush()
                session.add(Membership(workspace_id=settings.workspace_id,user_id=identity,role='viewer'))
                session.add(TeamInvitation(id=str(uuid4()),workspace_id=settings.workspace_id,email=f'invite-{i}@example.com',
                    role='viewer',token_hash=str(uuid4())+str(i),created_by=actor,expires_at=utc_now()+timedelta(days=1)))
                session.add(AuditEvent(id=str(uuid4()),workspace_id=settings.workspace_id,event_type='permission.invitation_created',
                    actor_type='user',actor_id=actor,outcome='success',metadata_json={}))
            session.commit()
        for suffix,key,total in (('','members',56),('/invitations','invitations',55),('/audit','events',55)):
            first = client.get(BASE+suffix).json()
            assert len(first[key]) == 50 and first['next_cursor']
            second = client.get(BASE+suffix,params={'cursor':first['next_cursor']}).json()
            assert len(second[key]) == total-50 and second['next_cursor'] is None
            assert len({r['id'] for r in first[key]+second[key]}) == total
        assert len(client.get(BASE,params={'search':'page-1@'}).json()['members']) == 1


def test_management_revalidates_actor_after_waiting_for_lock(settings):
    from app.platform_auth import resolve_local_admin
    from app.team import WorkspaceTeam
    from contracts.v1.team import CreateInvitationRequest
    with TestClient(create_app(settings)) as client:
        database = client.app.state.platform_database
        actor = resolve_local_admin(database,settings.workspace_id)
        with database.session() as session:
            session.scalar(select(Membership)).status = 'suspended'
            session.commit()
        with pytest.raises(Exception) as caught:
            WorkspaceTeam(database,settings,client.app.state.password_hasher).create_invitation(actor,CreateInvitationRequest(**invitation()))
        assert getattr(caught.value,'status_code',None) == 403


def test_login_rechecks_membership_after_password_verification(settings, monkeypatch):
    from app.platform_db import AuthSession
    from app.platform_auth import verify_password
    settings = replace(settings, local_admin_enabled=False, bootstrap_admin_email='owner@example.com',
                       bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        identity = add_member(client, settings, email='racing@example.com')
        database = client.app.state.platform_database
        def suspend_during_verify(hasher, encoded, password):
            valid = verify_password(hasher, encoded, password)
            with database.session() as session:
                session.scalar(select(Membership).where(Membership.user_id == identity)).status = 'suspended'
                session.commit()
            return valid
        monkeypatch.setattr('app.platform_router.verify_password', suspend_during_verify)
        response = client.post('/api/v1/auth/login', json={'email':'racing@example.com','password':PASSWORD})
        assert response.status_code == 401
        with database.session() as session:
            assert not session.scalar(select(AuthSession).where(AuthSession.user_id == identity))


def test_team_denials_not_disclosed_by_legacy_activity(settings):
    settings = replace(settings, local_admin_enabled=False, bootstrap_admin_email='owner@example.com',
                       bootstrap_admin_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        first = add_member(client, settings, role='viewer', email='first@example.com')
        add_member(client, settings, role='viewer', email='second@example.com')
        client.post('/api/v1/auth/login', json={'email':'first@example.com','password':PASSWORD})
        assert client.post(BASE+f'/members/{first}/update', json={
            'request_id':str(uuid4()),'expected_revision':0,'status':'removed'}).status_code == 403
        client.post('/api/v1/auth/login', json={'email':'second@example.com','password':PASSWORD})
        events = client.get('/api/v1/workspace/audit/events?group=permission').json()['events']
        assert not any(r['metadata'].get('permission') == 'members:manage' for r in events)
        client.post('/api/v1/auth/login', json={'email':'owner@example.com','password':PASSWORD})
        assert any(r['action'] == 'permission.denied' for r in client.get(BASE+'/audit').json()['events'])


def test_invitation_validation_never_echoes_secret_inputs(settings):
    with TestClient(create_app(settings)) as client:
        token = 'private-token-'*11
        response = client.post(PUBLIC+'/inspect',json={'token':token})
        assert response.status_code == 422 and token not in response.text
        password = 'private-password-'*20
        response = client.post(PUBLIC+'/accept',json={'token':'x'*43,'request_id':str(uuid4()),'password':password})
        assert response.status_code == 422 and password not in response.text and 'x'*43 not in response.text
