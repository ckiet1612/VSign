"""Separate webhook dispatcher; network and DNS bounded by a child deadline."""
from __future__ import annotations

import hashlib
import hmac
import json
import multiprocessing
import signal
import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.config import Settings
from app.platform_db import create_database, utc_now
from app.integrations import Integrations, aware, cipher, consume, safe_log
from app.integration_db import IntegrationDelivery, IntegrationWebhook, IntegrationWorkerState

BACKOFF=(15,60,300,900)


def scope(settings):
    return SimpleNamespace(workspace=SimpleNamespace(id=settings.workspace_id))


def fail_attempt(row,error):
    row.error=error
    row.claim_token,row.lease_until=None,None
    row.status='failed' if row.attempts>=5 else 'pending'
    if row.status=='pending':
        row.available_at=utc_now()+timedelta(seconds=BACKOFF[max(0,row.attempts-1)])


def claim_delivery(database,settings):
    with Integrations(database,settings).write(scope(settings)) as session:
        now=utc_now()
        state=session.get(IntegrationWorkerState,settings.workspace_id)
        if not state:
            session.add(IntegrationWorkerState(workspace_id=settings.workspace_id,heartbeat_at=now))
        else:
            state.heartbeat_at=now
        expired=session.scalars(select(IntegrationDelivery).where(IntegrationDelivery.workspace_id==settings.workspace_id,
            IntegrationDelivery.status=='sending',IntegrationDelivery.lease_until<=now)).all()
        for row in expired:
            fail_attempt(row,'worker_interrupted')
            safe_log(session,settings.workspace_id,'webhook',row.id,row.event_type,0,attempt=row.attempts,error='worker_interrupted')
        session.flush()
        pending=session.scalars(select(IntegrationDelivery).where(IntegrationDelivery.workspace_id==settings.workspace_id,
            IntegrationDelivery.status=='pending',IntegrationDelivery.available_at<=now)
            .order_by(IntegrationDelivery.available_at,IntegrationDelivery.created_at,IntegrationDelivery.id).limit(100)).all()
        for row in pending:
            hook=session.get(IntegrationWebhook,row.webhook_id)
            if not hook or hook.workspace_id!=settings.workspace_id or not hook.enabled:
                row.status='cancelled'
                continue
            retry=consume(session,settings.workspace_id,[('webhook:workspace',60),('webhook:'+hook.id,30)])
            if retry:
                row.available_at=now+timedelta(seconds=retry)
                continue
            row.status,row.claim_token,row.lease_until='sending',str(uuid4()),now+timedelta(seconds=60)
            row.attempts += 1
            return row.id,row.claim_token
        return None


def deliver(database,settings,identity,token,transport=None):
    started=time.monotonic()
    from app.webhook_transport import post_webhook, UnsafeTarget
    transport=transport or post_webhook
    with database.session() as session:
        row=session.get(IntegrationDelivery,identity)
        if (not row or row.workspace_id!=settings.workspace_id or row.status!='sending' or row.claim_token!=token
                or not row.lease_until or aware(row.lease_until)<=utc_now()):
            return {'status_code':0,'error':'claim_inactive','duration_ms':0}
        hook=session.get(IntegrationWebhook,row.webhook_id)
        if not hook or hook.workspace_id!=settings.workspace_id or not hook.enabled:
            return {'status_code':0,'error':'webhook_disabled','duration_ms':0}
        url=hook.url
        try:
            secret=cipher(settings).decrypt(hook.secret_ciphertext.encode())
        except Exception:
            return {'status_code':0,'error':'signing_key_unavailable','duration_ms':0}
        body=json.dumps(row.payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
        timestamp=str(int(time.time()))
        headers={'X-VSign-Delivery':row.id,'X-VSign-Event':row.event_type,'X-VSign-Timestamp':timestamp,
            'X-VSign-Signature':'sha256='+hmac.new(secret,timestamp.encode()+b'.'+body,hashlib.sha256).hexdigest()}
    code,error=0,None
    try:
        code=transport(url,body,headers)
        error=None if 200<=code<300 else 'http_error'
    except UnsafeTarget:
        error='unsafe_target'
    except Exception:
        error='network_error'
    return {'status_code':code,'error':error,'duration_ms':int((time.monotonic()-started)*1000)}


def finish_delivery(database,settings,identity,token,result):
    with Integrations(database,settings).write(scope(settings)) as session:
        row=session.get(IntegrationDelivery,identity)
        if (not row or row.workspace_id!=settings.workspace_id or row.status!='sending' or row.claim_token!=token
                or not row.lease_until or aware(row.lease_until)<=utc_now()):
            return False
        code=int(result['status_code'])
        row.status_code=code or None
        if 200<=code<300 and not result['error']:
            row.status,row.claim_token,row.lease_until,row.error='delivered',None,None,None
        else:
            fail_attempt(row,result['error'] or 'http_error')
        safe_log(session,settings.workspace_id,'webhook',row.id,row.event_type,code,
            duration=result['duration_ms'],attempt=row.attempts,error=row.error)
        return True


def child(settings,identity,token,connection):
    database=create_database(settings.database_url)
    try:
        connection.send(deliver(database,settings,identity,token))
    finally:
        database.dispose()
        connection.close()


def dispatch(database,settings,identity,token):
    ctx=multiprocessing.get_context('spawn')
    parent,child_pipe=ctx.Pipe(duplex=False)
    process=ctx.Process(target=child,args=(settings,identity,token,child_pipe))
    result={'status_code':0,'error':'delivery_timeout','duration_ms':20000}
    try:
        process.start()
        child_pipe.close()
        process.join(timeout=20)
        if not process.is_alive() and parent.poll():
            try:
                result=parent.recv()
            except EOFError:
                result={'status_code':0,'error':'worker_interrupted','duration_ms':0}
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
            if process.is_alive():
                process.kill()
                process.join()
        parent.close()
        child_pipe.close()
    return finish_delivery(database,settings,identity,token,result)


def main():
    settings=Settings.from_env()
    cipher(settings)
    if settings.database_url=='sqlite:///:memory:':
        raise RuntimeError('Webhook worker requires persistent storage')
    database=create_database(settings.database_url)
    database.ensure_schema(False)
    stopped=False
    def stop(*_args):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        while not stopped:
            claim=claim_delivery(database,settings)
            if claim:
                dispatch(database,settings,*claim)
            else:
                time.sleep(2)
    finally:
        database.dispose()


if __name__=='__main__':
    main()
