from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from test_local_admin import local_settings

BASE = '/api/v1/workspace/integrations'
MACHINE = '/api/v1/integrations'


@pytest.fixture
def settings(monkeypatch, tmp_path):
    return local_settings(monkeypatch, tmp_path)


def key_payload(**kwargs):
    return {'request_id':str(uuid4()), 'name':'CRM', 'scopes':['models:read'],
            'expires_at':(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(),
            'requests_per_minute':2, **kwargs}


def test_overview_and_hashed_one_time_key(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get(BASE)
        assert response.status_code == 200, response.text
        assert response.json()['keys'] == []
        assert client.get('/api/v1/workspace/capabilities').json()['capabilities']['integrations']
        payload = key_payload()
        response = client.post(BASE+'/keys', json=payload)
        assert response.status_code == 201, response.text
        secret = response.json()['secret']
        assert secret.startswith('vsign_') and len(secret) > 40
        assert secret not in client.get(BASE).text
        assert client.post(BASE+'/keys', json=payload).json()['secret'] is None
        assert client.post(BASE+'/keys', json={**payload,'name':'Changed'}).status_code == 409
        assert secret not in client.get('/api/v1/workspace/audit/events').text
        from pathlib import Path
        assert secret.encode() not in Path(settings.database_url.removeprefix('sqlite:///')).read_bytes()
        from app.integration_db import IntegrationKey
        from app.platform_db import hash_session_token
        with client.app.state.platform_database.session() as session:
            row = session.get(IntegrationKey,payload['request_id'])
            assert row.token_hash == hash_session_token(secret)


def test_machine_keys_are_scoped_and_never_local_admin(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get(MACHINE+'/models').status_code == 401
        secret=client.post(BASE+'/keys',json=key_payload()).json()['secret']
        headers={'Authorization':'Bearer '+secret}
        assert client.get(MACHINE+'/models',headers=headers).status_code == 200
        assert client.get(MACHINE+'/snapshots',headers=headers).status_code == 403
        assert client.get('/api/v1/workspace/members',headers=headers).status_code == 403
        assert client.post('/api/v1/workspace/models',json={},headers=headers).status_code == 403
        assert client.get(MACHINE+'/models',headers={'Authorization':'Bearer invalid'}).status_code == 401


def test_shared_rate_limit_revoke_and_retry_after(settings):
    app=create_app(settings)
    with TestClient(app) as client:
        payload=key_payload()
        secret=client.post(BASE+'/keys',json=payload).json()['secret']
        headers={'Authorization':'Bearer '+secret}
        assert client.get(MACHINE+'/models',headers=headers).status_code == 200
        with TestClient(create_app(settings)) as other:
            assert other.get(MACHINE+'/models',headers=headers).status_code == 200
            response=other.get(MACHINE+'/models',headers=headers)
            assert response.status_code == 429 and int(response.headers['Retry-After']) > 0
        assert client.post(BASE+f'/keys/{payload["request_id"]}/revoke',json={}).status_code == 200
        assert client.get(MACHINE+'/models',headers=headers).status_code == 401


def test_auth_origin_limits_and_no_encryption_key(settings):
    with TestClient(create_app(replace(settings,local_admin_enabled=False))) as client:
        assert client.get(BASE).status_code == 401
    with TestClient(create_app(settings)) as client:
        assert client.post(BASE+'/keys',json=key_payload(),headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.post(BASE+'/keys',content='x'*9000).status_code == 413
        assert client.post(BASE+'/keys',json=key_payload(scopes=['models:deploy'])).status_code == 422
        assert client.post(BASE+'/keys',json=key_payload(requests_per_minute=61)).status_code == 422
        response=client.post(BASE+'/webhooks',json={'request_id':str(uuid4()),'name':'CRM',
            'url':'https://example.com/hook','events':['evaluation.completed']})
        assert response.status_code == 503


@pytest.mark.parametrize('role', ['operator','reviewer','viewer','model_admin'])
def test_only_enterprise_administrators_manage_integrations(settings,role):
    from sqlalchemy import select
    from app.platform_db import Membership
    settings=replace(settings,local_admin_enabled=False,bootstrap_admin_email='admin@example.com',
                     bootstrap_admin_password='password-1234567')
    app=create_app(settings)
    with TestClient(app) as client:
        with app.state.platform_database.session() as session:
            session.scalar(select(Membership)).role=role
            session.commit()
        client.post('/api/v1/auth/login',json={'email':settings.bootstrap_admin_email,'password':settings.bootstrap_admin_password})
        assert client.get(BASE).status_code == 403
        assert client.post(BASE+'/keys',json={}).status_code == 403


def test_tenant_key_and_management_isolation(settings):
    with TestClient(create_app(settings)) as first:
        payload=key_payload()
        secret=first.post(BASE+'/keys',json=payload).json()['secret']
        with TestClient(create_app(replace(settings,workspace_id='other'))) as other:
            assert other.get(BASE).json()['keys'] == []
            assert other.post(BASE+f'/keys/{payload["request_id"]}/revoke',json={}).status_code == 404
            assert other.get(MACHINE+'/models',headers={'Authorization':'Bearer '+secret}).status_code == 401


@pytest.fixture
def encrypted_settings(settings):
    from cryptography.fernet import Fernet
    return replace(settings,integration_encryption_key=Fernet.generate_key().decode())


def hook_payload(**kwargs):
    return {'request_id':str(uuid4()),'name':'ERP','url':'https://example.com/events',
            'events':['evaluation.completed'], **kwargs}


def test_encrypted_webhook_idempotency_configure_rotate_test(encrypted_settings):
    from app.integration_db import IntegrationWebhook, IntegrationDelivery
    from sqlalchemy import select
    with TestClient(create_app(encrypted_settings)) as client:
        payload=hook_payload()
        response=client.post(BASE+'/webhooks',json=payload)
        assert response.status_code == 201, response.text
        secret=response.json()['secret']
        identity=payload['request_id']
        assert secret not in client.get(BASE).text
        assert client.post(BASE+'/webhooks',json=payload).json()['secret'] is None
        with client.app.state.platform_database.session() as session:
            row=session.get(IntegrationWebhook,identity)
            assert secret not in row.secret_ciphertext
        rotation={'request_id':str(uuid4())}
        new=client.post(BASE+f'/webhooks/{identity}/rotate',json=rotation).json()['secret']
        assert new and new!=secret
        assert client.post(BASE+f'/webhooks/{identity}/rotate',json=rotation).json()['secret'] is None
        test={'request_id':str(uuid4())}
        for _ in range(2):
            assert client.post(BASE+f'/webhooks/{identity}/test',json=test).status_code == 201
        with client.app.state.platform_database.session() as session:
            assert len(session.scalars(select(IntegrationDelivery)).all()) == 1
        response=client.post(BASE+f'/webhooks/{identity}/configure',json={'request_id':str(uuid4()),
            'enabled':False,'events':['collection.started']})
        assert response.status_code == 200
        assert response.json()['deliveries'][0]['status']=='cancelled'
        assert client.post(BASE+f'/webhooks/{identity}/test',json={'request_id':str(uuid4())}).status_code == 409


def test_transactional_fanout_never_browser_or_arbitrary_metadata(encrypted_settings):
    from app.platform_db import AuditEvent
    from app.integration_db import IntegrationDelivery
    from sqlalchemy import select
    with TestClient(create_app(encrypted_settings)) as client:
        assert client.post(BASE+'/webhooks',json=hook_payload()).status_code == 201
        database=client.app.state.platform_database
        def event(source='server'):
            return AuditEvent(id=str(uuid4()),workspace_id=encrypted_settings.workspace_id,event_type='evaluation.completed',
                actor_type='system',outcome='success',resource_type='evaluation',resource_id=str(uuid4()),
                metadata_json={'source':source,'secret':'do-not-export','path':'/private/data'})
        with database.session() as session:
            session.add(event())
            session.flush()
            session.rollback()
        assert client.get(BASE).json()['deliveries']==[]
        with database.session() as session:
            session.add(event('browser_report'))
            session.commit()
        assert client.get(BASE).json()['deliveries']==[]
        with database.session() as session:
            row=event()
            session.add(row)
            session.commit()
            delivery=session.scalar(select(IntegrationDelivery))
            assert delivery.event_id==row.id and delivery.status=='pending'
            assert 'do-not-export' not in str(delivery.payload) and '/private/data' not in str(delivery.payload)
        assert len(client.get(BASE).json()['deliveries'])==1


@pytest.mark.parametrize('url',['http://example.com','https://localhost/a','https://127.0.0.1/a',
    'https://169.254.169.254/metadata','https://user:pass@example.com/a','https://example.com:8443',
    'https://example.com/a?secret=x','https://example.com/#x','https://example.com\\@127.0.0.1',
    'https://foo.internal/a','https://[::1]/'])
def test_webhook_rejects_unsafe_urls(encrypted_settings,url):
    with TestClient(create_app(encrypted_settings)) as client:
        assert client.post(BASE+'/webhooks',json=hook_payload(url=url)).status_code==422


def test_worker_claim_sign_retry_fence_and_disable(encrypted_settings,monkeypatch):
    from app.integration_worker import claim_delivery, finish_delivery, deliver
    from app.integration_db import IntegrationDelivery
    from app.integrations import utc_now
    from datetime import timedelta
    import hashlib, hmac, json
    captured=[]
    def transport(url,body,headers):
        captured.append((url,body,headers))
        return 202
    with TestClient(create_app(encrypted_settings)) as client:
        payload=hook_payload()
        secret=client.post(BASE+'/webhooks',json=payload).json()['secret']
        identity=payload['request_id']
        client.post(BASE+f'/webhooks/{identity}/test',json={'request_id':str(uuid4())})
        db=client.app.state.platform_database
        delivery_id,token=claim_delivery(db,encrypted_settings)
        assert claim_delivery(db,encrypted_settings) is None
        result=deliver(db,encrypted_settings,delivery_id,token,transport)
        assert result['status_code']==202
        _,body,headers=captured[0]
        ts=headers['X-VSign-Timestamp']
        assert headers['X-VSign-Signature']=='sha256='+hmac.new(secret.encode(),ts.encode()+b'.'+body,hashlib.sha256).hexdigest()
        assert json.loads(body)['event_type']=='integration.test'
        assert finish_delivery(db,encrypted_settings,delivery_id,'wrong-token',result) is False
        assert finish_delivery(db,encrypted_settings,delivery_id,token,{'status_code':500,'error':'http_error','duration_ms':3})
        assert claim_delivery(db,encrypted_settings) is None
        with db.session() as session:
            row=session.get(IntegrationDelivery,delivery_id)
            row.available_at=utc_now()-timedelta(seconds=1)
            session.commit()
        second_id,second_token=claim_delivery(db,encrypted_settings)
        assert second_id==delivery_id and second_token!=token
        with db.session() as session:
            session.get(IntegrationDelivery,delivery_id).lease_until=utc_now()-timedelta(seconds=1)
            session.commit()
        assert finish_delivery(db,encrypted_settings,delivery_id,second_token,result) is False
        assert claim_delivery(db,encrypted_settings) is None  # expired claim recovers into delayed retry
        client.post(BASE+f'/webhooks/{identity}/configure',json={'request_id':str(uuid4()),'enabled':False,'events':payload['events']})
        assert client.get(BASE).json()['deliveries'][0]['status']=='cancelled'


def test_dns_public_only_and_pinned_transport(monkeypatch):
    from app.webhook_transport import resolve_public, post_webhook, UnsafeTarget
    import socket
    from unittest.mock import Mock
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))])
    with pytest.raises(UnsafeTarget):
        resolve_public('example.com')
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443)),
        (socket.AF_INET6,socket.SOCK_STREAM,6,'',('::1',443,0,0))])
    with pytest.raises(UnsafeTarget):
        resolve_public('example.com')
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))])
    assert resolve_public('example.com')=='93.184.216.34'
    from app import webhook_transport
    connection=Mock()
    connection.getresponse.return_value.status=302
    factory=Mock(return_value=connection)
    monkeypatch.setattr(webhook_transport,'PinnedHTTPSConnection',factory)
    assert post_webhook('https://example.com/events',b'{}',{'X-Test':'ok'})==302
    assert factory.call_args.args==('example.com','93.184.216.34')
    assert connection.request.call_count==1  # never follow redirects
    assert connection.close.called


def test_expired_key_and_concurrent_shared_budget(settings,monkeypatch):
    from app.integration_db import IntegrationKey
    from app.platform_db import utc_now
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr('app.integrations.time.time',lambda:1800000001)
    with TestClient(create_app(settings)) as client:
        payload=key_payload()
        secret=client.post(BASE+'/keys',json=payload).json()['secret']
        headers={'Authorization':'Bearer '+secret}
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses=list(pool.map(lambda _:client.get(MACHINE+'/models',headers=headers).status_code,range(4)))
        assert sorted(statuses)==[200,200,429,429]
        with client.app.state.platform_database.session() as session:
            session.get(IntegrationKey,payload['request_id']).expires_at=utc_now()-timedelta(seconds=1)
            session.commit()
        assert client.get(MACHINE+'/models',headers=headers).status_code==401


def test_workspace_budget_counts_different_keys_and_logs_paginate(settings,monkeypatch):
    from app.integration_db import IntegrationRateBucket, IntegrationLog
    from app.integrations import utc_now
    monkeypatch.setattr('app.integrations.time.time',lambda:1800000001)
    with TestClient(create_app(settings)) as client:
        keys=[client.post(BASE+'/keys',json=key_payload()).json()['secret'] for _ in range(2)]
        with client.app.state.platform_database.session() as session:
            session.add(IntegrationRateBucket(workspace_id=settings.workspace_id,bucket='api:workspace',window=1800000001//60,count=299))
            for _ in range(52):
                session.add(IntegrationLog(id=str(uuid4()),workspace_id=settings.workspace_id,kind='webhook',resource_id=str(uuid4()),
                    action='integration.test',status_code=202,duration_ms=2,attempt=1,error=None,created_at=utc_now()))
            session.commit()
        assert client.get(MACHINE+'/models',headers={'Authorization':'Bearer '+keys[0]}).status_code==200
        assert client.get(MACHINE+'/models',headers={'Authorization':'Bearer '+keys[1]}).status_code==429
        first=client.get(BASE+'/logs?kind=webhook').json()
        assert len(first['logs'])==50 and first['next_cursor']
        second=client.get(BASE+'/logs',params={'kind':'webhook','cursor':first['next_cursor']}).json()
        assert len(second['logs'])==2 and second['next_cursor'] is None
        assert not {r['id'] for r in first['logs']} & {r['id'] for r in second['logs']}
        assert client.get(BASE+'/logs?cursor=not-json').status_code==422


def test_machine_returns_actual_safe_registry_snapshot_evaluation(settings,tmp_path):
    from test_workspace_evaluations import prepare_evaluation
    settings=replace(settings,collection_enabled=True,collection_dir=tmp_path/'media',model_registry_roots=(tmp_path,),model_evaluation_roots=(tmp_path/'evidence',))
    with TestClient(create_app(settings)) as client:
        run=prepare_evaluation(client,settings,tmp_path)
        assert client.post('/api/v1/workspace/evaluations',json=run).status_code==201
        secret=client.post(BASE+'/keys',json=key_payload(scopes=['models:read','snapshots:read','evaluations:read'],requests_per_minute=60)).json()['secret']
        headers={'Authorization':'Bearer '+secret}
        models=client.get(MACHINE+'/models',headers=headers)
        assert models.status_code==200 and len(models.json()['items'])==2
        assert '/media' not in models.text and 'artifact_path' not in models.text and 'manifest' not in models.text
        snapshots=client.get(MACHINE+'/snapshots',headers=headers).json()['items']
        assert len(snapshots)==1 and snapshots[0]['id']==run['snapshot_id']
        evaluations=client.get(MACHINE+'/evaluations',headers=headers).json()['items']
        assert evaluations[0]['id']==run['request_id'] and evaluations[0]['status']=='queued'


def test_five_attempt_cap_manual_retry_and_transport_error_redaction(encrypted_settings):
    from app.integration_worker import claim_delivery, finish_delivery, deliver
    from app.integration_db import IntegrationDelivery
    from app.platform_db import utc_now
    with TestClient(create_app(encrypted_settings)) as client:
        payload=hook_payload()
        client.post(BASE+'/webhooks',json=payload)
        identity=str(uuid4())
        client.post(BASE+f'/webhooks/{payload["request_id"]}/test',json={'request_id':identity})
        db=client.app.state.platform_database
        def failing_transport(*_args):
            raise RuntimeError('password=must-never-be-logged')
        for _ in range(5):
            with db.session() as session:
                session.get(IntegrationDelivery,identity).available_at=utc_now()-timedelta(seconds=1)
                session.commit()
            claimed=claim_delivery(db,encrypted_settings)
            assert claimed[0]==identity
            result=deliver(db,encrypted_settings,*claimed,failing_transport)
            assert result['error']=='network_error'
            finish_delivery(db,encrypted_settings,*claimed,result)
        assert claim_delivery(db,encrypted_settings) is None
        assert client.get(BASE).json()['deliveries'][0]['status']=='failed'
        assert 'must-never-be-logged' not in client.get(BASE+'/logs').text
        body={'request_id':str(uuid4())}
        assert client.post(BASE+f'/deliveries/{identity}/retry',json=body).status_code==200
        assert client.post(BASE+f'/deliveries/{identity}/retry',json=body).status_code==200
        assert client.get(BASE).json()['deliveries'][0]['attempts']==0


@pytest.mark.parametrize('address',['224.0.0.1','ff02::1','::ffff:127.0.0.1','64:ff9b::7f00:1'])
def test_dns_rejects_multicast_and_translation_targets(monkeypatch,address):
    from app.webhook_transport import resolve_public, UnsafeTarget
    import socket
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET6,socket.SOCK_STREAM,6,'',(address,443,0,0))])
    with pytest.raises(UnsafeTarget):
        resolve_public('example.com')


def test_native_tls_hostname_and_signed_payload(encrypted_settings,tmp_path,monkeypatch):
    import ssl, socket, threading, json, hmac, hashlib
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from app.integration_worker import claim_delivery,deliver,finish_delivery

    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'hook.example')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('hook.example')]),critical=False).sign(key,hashes.SHA256()))
    certfile,keyfile=tmp_path/'test-cert.pem',tmp_path/'test-key.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    received=[]
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.rfile.read(int(self.headers['Content-Length'])),dict(self.headers)))
            self.send_response(202)
            self.end_headers()
        def log_message(self,*_args):
            pass
    server=HTTPServer(('127.0.0.1',0),Receiver)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile,keyfile)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    real_connect,real_context,original_dns=socket.create_connection,ssl.create_default_context,socket.getaddrinfo
    def pinned_connect(address,timeout):
        assert address==('93.184.216.34',443)
        return real_connect(('127.0.0.1',server.server_port),timeout)
    monkeypatch.setattr(socket,'create_connection',pinned_connect)
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
                        if a[0] in ('hook.example','wrong.example') else original_dns(*a,**k))
    # The only test remapping is at the socket boundary; TLS still verifies the URL hostname.
    monkeypatch.setattr(ssl,'create_default_context',lambda:real_context(cafile=str(certfile)))
    try:
        with TestClient(create_app(encrypted_settings)) as client:
            payload=hook_payload(url='https://hook.example/events')
            secret=client.post(BASE+'/webhooks',json=payload).json()['secret']
            client.post(BASE+f'/webhooks/{payload["request_id"]}/test',json={'request_id':str(uuid4())})
            db=client.app.state.platform_database
            claim=claim_delivery(db,encrypted_settings)
            result=deliver(db,encrypted_settings,*claim)
            assert result['status_code']==202 and result['error'] is None
            assert finish_delivery(db,encrypted_settings,*claim,result)
            body,headers=received[0]
            assert headers['Host']=='hook.example'
            assert json.loads(body)['workspace_id']==encrypted_settings.workspace_id
            signed=headers['X-VSign-Timestamp'].encode()+b'.'+body
            assert headers['X-VSign-Signature']=='sha256='+hmac.new(secret.encode(),signed,hashlib.sha256).hexdigest()
            from app.webhook_transport import post_webhook
            with pytest.raises(ssl.SSLCertVerificationError):
                post_webhook('https://wrong.example/events',b'{}',{})
            assert len(received)==1
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def test_operator_key_file_missing_fails_closed(settings,monkeypatch,tmp_path):
    from app.config import Settings
    from cryptography.fernet import Fernet
    monkeypatch.delenv('INTEGRATION_ENCRYPTION_KEY',raising=False)
    target=tmp_path/'operator.key'
    monkeypatch.setenv('INTEGRATION_ENCRYPTION_KEY_FILE',str(target))
    assert Settings.from_env().integration_encryption_key is None
    value=Fernet.generate_key().decode()
    target.write_text(value+'\n')
    assert Settings.from_env().integration_encryption_key==value
    monkeypatch.setenv('INTEGRATION_ENCRYPTION_KEY','explicit-override')
    assert Settings.from_env().integration_encryption_key=='explicit-override'
    assert value not in repr(Settings.from_env())


def test_active_keys_remain_visible_after_many_expired_keys(settings):
    from app.integration_db import IntegrationKey
    from app.platform_db import utc_now
    with TestClient(create_app(settings)) as client:
        payload=key_payload()
        client.post(BASE+'/keys',json=payload)
        with client.app.state.platform_database.session() as session:
            for _ in range(55):
                session.add(IntegrationKey(id=str(uuid4()),workspace_id=settings.workspace_id,name='Old',prefix='vsign_old',
                    token_hash=uuid4().hex+uuid4().hex,scopes=['models:read'],requests_per_minute=60,expires_at=utc_now()-timedelta(days=1)))
            session.commit()
        rows=client.get(BASE).json()['keys']
        assert len(rows)==50 and rows[0]['id']==payload['request_id']


def sleeping_delivery_child(*_args):
    import time
    time.sleep(60)


def test_dispatch_terminates_a_stuck_subprocess(encrypted_settings,monkeypatch):
    from app import integration_worker as worker
    monkeypatch.setattr(worker,'child',sleeping_delivery_child)
    with TestClient(create_app(encrypted_settings)) as client:
        payload=hook_payload()
        client.post(BASE+'/webhooks',json=payload)
        client.post(BASE+f'/webhooks/{payload["request_id"]}/test',json={'request_id':str(uuid4())})
        database=client.app.state.platform_database
        claim=worker.claim_delivery(database,encrypted_settings)
        assert worker.dispatch(database,encrypted_settings,*claim)
        delivery=client.get(BASE).json()['deliveries'][0]
        assert delivery['status']=='pending' and delivery['attempts']==1
        assert delivery['error']=='delivery_timeout'
        assert client.get(BASE+'/logs').json()['logs'][0]['duration_ms']==20000


def test_integration_migration_matches_models_and_roundtrips_empty_database():
    from app.platform_db import create_database,Base
    from app.migrate import migration_config,upgrade_database
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    database=create_database('sqlite:///:memory:')
    try:
        upgrade_database(database)
        with database.engine.connect() as connection:
            differences=compare_metadata(MigrationContext.configure(connection),Base.metadata)
            assert not [d for d in differences if 'integration_' in str(d)]
            config=migration_config()
            config.attributes['connection']=connection
            command.downgrade(config,'0007_workspace_evaluations')
            connection.commit()
        upgrade_database(database)
        with database.engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision()=='0011_system_admin'
    finally:
        database.dispose()


def test_subscription_edits_never_reenable_disabled_webhooks(encrypted_settings):
    with TestClient(create_app(encrypted_settings)) as client:
        payload=hook_payload()
        client.post(BASE+'/webhooks',json=payload)
        path=BASE+f'/webhooks/{payload["request_id"]}/configure'
        # A separate operator disables the hook before an older subscription form saves.
        assert client.post(path,json={'request_id':str(uuid4()),'enabled':False}).status_code==200
        response=client.post(path,json={'request_id':str(uuid4()),'events':['collection.started']})
        assert response.status_code==200, response.text
        hook=response.json()['webhooks'][0]
        assert hook['enabled'] is False and hook['events']==['collection.started']
        response=client.post(path,json={'request_id':str(uuid4()),'enabled':True})
        assert response.status_code==200
        assert response.json()['webhooks'][0]['events']==['collection.started']
        assert client.post(path,json={'request_id':str(uuid4())}).status_code==422
