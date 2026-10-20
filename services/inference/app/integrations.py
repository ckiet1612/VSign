"""Enterprise management and explicitly scoped, read-only machine access."""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import secrets
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from uuid import uuid4, UUID

from fastapi import HTTPException
from sqlalchemy import select, func, delete, or_, and_

from app.platform_db import AuditEvent, utc_now, hash_session_token
from app.workspace_data import WorkspaceData
from app.integration_db import (IntegrationKey, IntegrationWebhook, IntegrationDelivery,
    IntegrationLog, IntegrationRateBucket, IntegrationMutation, IntegrationWorkerState)
from contracts.v1.integrations import EVENT_NAMES, SCOPE_NAMES


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def timestamp(value):
    return aware(value).isoformat() if value else None


def public_address(value):
    address=ipaddress.ip_address(value)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and (address.version==4 or (address in ipaddress.ip_network('2000::/3')
                 and address.sixtofour is None and address.teredo is None)))


def cipher(settings):
    try:
        from cryptography.fernet import Fernet
        return Fernet(settings.integration_encryption_key.encode('ascii'))
    except (AttributeError, ValueError, UnicodeError, ImportError):
        raise HTTPException(503, 'Khóa mã hóa webhook của máy chủ chưa sẵn sàng') from None


def validate_url(value):
    try:
        url=urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.port not in (None,443) or url.username
            or url.password or url.query or url.fragment or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
            or '\\' in value or len(url.hostname) > 253 or url.hostname.endswith('.')):
            raise ValueError
        host=url.hostname.lower()
        if host in ('localhost',) or host.endswith(('.localhost','.local','.internal')) or '.' not in host:
            raise ValueError
        try:
            address=ipaddress.ip_address(host)
        except ValueError:
            if any(not part or len(part)>63 or not all(c.isalnum() or c=='-' for c in part)
                   or part[0]=='-' or part[-1]=='-' for part in host.split('.')):
                raise ValueError
        else:
            if not public_address(str(address)):
                raise ValueError
        return value
    except (ValueError, TypeError):
        raise HTTPException(422,'Webhook cần địa chỉ HTTPS công khai, cổng443, không có query hoặc thông tin đăng nhập') from None


def consume(session, workspace_id, limits, now=None):
    now=time.time() if now is None else now
    window=int(now)//60
    session.execute(delete(IntegrationRateBucket).where(IntegrationRateBucket.workspace_id==workspace_id,
                                                      IntegrationRateBucket.window < window-1))
    rows=[]
    for bucket,limit in limits:
        row=session.get(IntegrationRateBucket,(workspace_id,bucket,window))
        if row and row.count >= limit:
            return max(1,60-int(now)%60)
        rows.append((bucket,row))
    for bucket,row in rows:
        if row:
            row.count += 1
        else:
            session.add(IntegrationRateBucket(workspace_id=workspace_id,bucket=bucket,window=window,count=1))
    return 0


def safe_log(session,workspace,kind,resource,action,status,duration=0,attempt=0,error=None):
    session.add(IntegrationLog(id=str(uuid4()),workspace_id=workspace,kind=kind,resource_id=resource,
        action=action,status_code=status,duration_ms=max(0,int(duration)),attempt=attempt,error=error))


def audit(session,actor,action,resource):
    session.add(AuditEvent(id=str(uuid4()),workspace_id=actor.workspace.id,event_type='integration.'+action,
        actor_type='user',actor_id=actor.user.id,outcome='success',resource_type='integration',
        resource_id=resource,metadata_json={'source':'server'}))


class Integrations(WorkspaceData):
    def receipt(self,session,actor,payload,operation):
        request_hash=hashlib.sha256(json.dumps({'op':operation,'actor':actor.user.id,
            'body':payload.model_dump(mode='json')},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        identity=str(payload.request_id)
        if self.existing(session,IntegrationMutation,actor,identity,request_hash):
            return False
        session.add(IntegrationMutation(id=identity,workspace_id=actor.workspace.id,request_hash=request_hash))
        return True

    def create_key(self,actor,payload):
        secret=None
        with self.write(actor) as session:
            if self.receipt(session,actor,payload,'key.create'):
                count=session.scalar(select(func.count()).select_from(IntegrationKey).where(
                    IntegrationKey.workspace_id==actor.workspace.id,IntegrationKey.revoked_at.is_(None),
                    IntegrationKey.expires_at>utc_now()))
                if count >= 20:
                    raise HTTPException(409,'Workspace đã có 20 khóa đang hoạt động')
                secret='vsign_'+secrets.token_urlsafe(32)
                session.add(IntegrationKey(id=str(payload.request_id),workspace_id=actor.workspace.id,name=payload.name,
                    prefix=secret[:16],token_hash=hash_session_token(secret),scopes=payload.scopes,
                    requests_per_minute=payload.requests_per_minute,expires_at=payload.expires_at))
                audit(session,actor,'key_created',str(payload.request_id))
        return {'secret':secret,'id':str(payload.request_id)}

    def revoke(self,actor,identity):
        with self.write(actor) as session:
            key=self.get(session,IntegrationKey,actor,identity)
            if not key.revoked_at:
                key.revoked_at=utc_now()
                audit(session,actor,'key_revoked',key.id)

    def create_webhook(self,actor,payload):
        validate_url(payload.url)
        encryption=cipher(self.settings)
        secret=None
        with self.write(actor) as session:
            if self.receipt(session,actor,payload,'webhook.create'):
                count=session.scalar(select(func.count()).select_from(IntegrationWebhook).where(
                    IntegrationWebhook.workspace_id==actor.workspace.id))
                if count >= 10:
                    raise HTTPException(409,'Workspace đã có 10 webhook')
                secret=secrets.token_urlsafe(32)
                session.add(IntegrationWebhook(id=str(payload.request_id),workspace_id=actor.workspace.id,
                    name=payload.name,url=payload.url,events=payload.events,enabled=True,
                    secret_ciphertext=encryption.encrypt(secret.encode()).decode(),secret_version=1))
                audit(session,actor,'webhook_created',str(payload.request_id))
        return {'secret':secret,'id':str(payload.request_id)}

    def configure(self,actor,identity,payload):
        with self.write(actor) as session:
            hook=self.get(session,IntegrationWebhook,actor,identity)
            if self.receipt(session,actor,payload,'webhook.configure:'+hook.id):
                if payload.enabled is not None:
                    hook.enabled=payload.enabled
                if payload.events is not None:
                    hook.events=payload.events
                if not hook.enabled:
                    for delivery in session.scalars(select(IntegrationDelivery).where(
                        IntegrationDelivery.workspace_id==actor.workspace.id,IntegrationDelivery.webhook_id==hook.id,
                        IntegrationDelivery.status.in_(['pending','sending']))):
                        delivery.status,delivery.claim_token,delivery.lease_until='cancelled',None,None
                audit(session,actor,'webhook_updated',hook.id)

    def rotate(self,actor,identity,payload):
        encryption=cipher(self.settings)
        secret=None
        with self.write(actor) as session:
            hook=self.get(session,IntegrationWebhook,actor,identity)
            if self.receipt(session,actor,payload,'webhook.rotate:'+hook.id):
                secret=secrets.token_urlsafe(32)
                hook.secret_ciphertext=encryption.encrypt(secret.encode()).decode()
                hook.secret_version += 1
                audit(session,actor,'webhook_rotated',hook.id)
        return {'secret':secret,'id':str(identity)}

    def test(self,actor,identity,payload):
        with self.write(actor) as session:
            hook=self.get(session,IntegrationWebhook,actor,identity)
            if not hook.enabled:
                raise HTTPException(409,'Webhook đang tắt')
            if self.receipt(session,actor,payload,'webhook.test:'+hook.id):
                event_id=str(payload.request_id)
                session.add(IntegrationDelivery(id=event_id,workspace_id=actor.workspace.id,webhook_id=hook.id,
                    event_id=event_id,event_type='integration.test',payload={'api_version':'1','event_id':event_id,
                    'workspace_id':actor.workspace.id,'event_type':'integration.test','occurred_at':timestamp(utc_now()),
                    'outcome':'success','resource_type':'webhook','resource_id':hook.id}))
                audit(session,actor,'webhook_test_requested',hook.id)

    def retry(self,actor,identity,payload):
        with self.write(actor) as session:
            delivery=self.get(session,IntegrationDelivery,actor,identity)
            hook=self.get(session,IntegrationWebhook,actor,delivery.webhook_id)
            if self.receipt(session,actor,payload,'delivery.retry:'+delivery.id):
                if delivery.status != 'failed' or not hook.enabled:
                    raise HTTPException(409,'Chỉ gửi lại lượt thất bại của webhook đang bật')
                delivery.status,delivery.attempts,delivery.available_at='pending',0,utc_now()
                delivery.error,delivery.status_code=None,None
                audit(session,actor,'delivery_retry_requested',delivery.id)

    def overview(self,actor):
        with self.database.session() as session:
            workspace=actor.workspace.id
            keys=session.scalars(select(IntegrationKey).where(IntegrationKey.workspace_id==workspace)
                .order_by(and_(IntegrationKey.revoked_at.is_(None),IntegrationKey.expires_at>utc_now()).desc(),
                          IntegrationKey.created_at.desc(),IntegrationKey.id.desc()).limit(50)).all()
            hooks=session.scalars(select(IntegrationWebhook).where(IntegrationWebhook.workspace_id==workspace)
                .order_by(IntegrationWebhook.created_at.desc(),IntegrationWebhook.id.desc()).limit(50)).all()
            deliveries=session.scalars(select(IntegrationDelivery).where(IntegrationDelivery.workspace_id==workspace)
                .order_by(IntegrationDelivery.created_at.desc(),IntegrationDelivery.id.desc()).limit(50)).all()
            worker=session.get(IntegrationWorkerState,workspace)
            ready=False
            try:
                encryption=cipher(self.settings)
                # Report mismatched operator keys honestly, without decrypting into a response.
                for hook in hooks:
                    encryption.decrypt(hook.secret_ciphertext.encode())
                ready=True
            except Exception:
                pass
            return {'api_version':'1','workspace_id':workspace,'permissions':{'manage':True},
                'webhook_ready':ready,'worker_online':bool(worker and aware(worker.heartbeat_at)>utc_now()-timedelta(seconds=45)),
                'available_scopes':list(SCOPE_NAMES),'available_events':list(EVENT_NAMES),
                'limits':{'key_per_minute':60,'workspace_per_minute':300,'webhook_per_minute':30,'webhook_workspace_per_minute':60},
                'keys':[{'id':k.id,'name':k.name,'prefix':k.prefix,'scopes':k.scopes,'requests_per_minute':k.requests_per_minute,
                    'created_at':timestamp(k.created_at),'expires_at':timestamp(k.expires_at),'revoked_at':timestamp(k.revoked_at),
                    'last_used_at':timestamp(k.last_used_at)} for k in keys],
                'webhooks':[{'id':h.id,'name':h.name,'url':h.url,'events':h.events,'enabled':h.enabled,
                    'secret_version':h.secret_version,'created_at':timestamp(h.created_at)} for h in hooks],
                'deliveries':[{'id':d.id,'webhook_id':d.webhook_id,'event_id':d.event_id,'event_type':d.event_type,
                    'status':d.status,'attempts':d.attempts,'status_code':d.status_code,'error':d.error,
                    'created_at':timestamp(d.created_at),'available_at':timestamp(d.available_at)} for d in deliveries]}

    def logs(self,actor,kind=None,cursor=None):
        query=select(IntegrationLog).where(IntegrationLog.workspace_id==actor.workspace.id)
        if kind:
            query=query.where(IntegrationLog.kind==kind)
        if cursor:
            try:
                data=json.loads(base64.urlsafe_b64decode(cursor.encode()))
                at=datetime.fromisoformat(data['at'])
                identity=str(UUID(data['id']))
                if at.tzinfo is None:
                    raise ValueError
            except (ValueError,KeyError,TypeError,UnicodeError):
                raise HTTPException(422,'Cursor không hợp lệ') from None
            query=query.where(or_(IntegrationLog.created_at<at,and_(IntegrationLog.created_at==at,IntegrationLog.id<identity)))
        with self.database.session() as session:
            rows=session.scalars(query.order_by(IntegrationLog.created_at.desc(),IntegrationLog.id.desc()).limit(51)).all()
            more=len(rows)>50
            rows=rows[:50]
            next_cursor=base64.urlsafe_b64encode(json.dumps({'at':timestamp(rows[-1].created_at),'id':rows[-1].id}).encode()).decode() if more else None
            return {'api_version':'1','workspace_id':actor.workspace.id,'logs':[{
                'id':r.id,'kind':r.kind,'resource_id':r.resource_id,'action':r.action,'status_code':r.status_code,
                'duration_ms':r.duration_ms,'attempt':r.attempt,'error':r.error,'created_at':timestamp(r.created_at)} for r in rows],
                'next_cursor':next_cursor}
