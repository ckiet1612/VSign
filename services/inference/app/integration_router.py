from time import perf_counter
from typing import Literal, Optional
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.integrations import Integrations, aware, consume, safe_log, timestamp
from app.integration_db import IntegrationKey
from app.platform_db import hash_session_token, utc_now
from contracts.v1.integrations import CreateKeyRequest, CreateWebhookRequest, ConfigureWebhookRequest, IntegrationRequest


def create_integration_router(settings, get_database, require_permission, validate_origin):
    router=APIRouter(tags=['integrations'])
    prefix='/workspace/integrations'

    def manager(request:Request):
        if request.method != 'GET':
            validate_origin(request)
        return require_permission(request,'integrations:manage')

    def call(request,actor,operation=None):
        try:
            store=Integrations(get_database(request),settings)
            result=operation(store) if operation else None
            return {**store.overview(actor),**(result or {})}
        except (SQLAlchemyError,OSError):
            raise HTTPException(503,'Chưa xác nhận thao tác tích hợp; làm mới rồi thử lại cùng mã yêu cầu') from None

    @router.get(prefix)
    def overview(request:Request,actor=Depends(manager)):
        return call(request,actor)

    @router.post(prefix+'/keys',status_code=201)
    def create_key(request:Request,payload:CreateKeyRequest,actor=Depends(manager)):
        return call(request,actor,lambda s:s.create_key(actor,payload))

    @router.post(prefix+'/keys/{identity}/revoke')
    def revoke(request:Request,identity:UUID,actor=Depends(manager)):
        return call(request,actor,lambda s:s.revoke(actor,identity))

    @router.post(prefix+'/webhooks',status_code=201)
    def create_webhook(request:Request,payload:CreateWebhookRequest,actor=Depends(manager)):
        return call(request,actor,lambda s:s.create_webhook(actor,payload))

    @router.post(prefix+'/webhooks/{identity}/configure')
    def configure(request:Request,identity:UUID,payload:ConfigureWebhookRequest,actor=Depends(manager)):
        return call(request,actor,lambda s:s.configure(actor,identity,payload))

    @router.post(prefix+'/webhooks/{identity}/rotate')
    def rotate(request:Request,identity:UUID,payload:IntegrationRequest,actor=Depends(manager)):
        return call(request,actor,lambda s:s.rotate(actor,identity,payload))

    @router.post(prefix+'/webhooks/{identity}/test',status_code=201)
    def test(request:Request,identity:UUID,payload:IntegrationRequest,actor=Depends(manager)):
        return call(request,actor,lambda s:s.test(actor,identity,payload))

    @router.post(prefix+'/deliveries/{identity}/retry')
    def retry(request:Request,identity:UUID,payload:IntegrationRequest,actor=Depends(manager)):
        return call(request,actor,lambda s:s.retry(actor,identity,payload))

    @router.get(prefix+'/logs')
    def logs(request:Request,kind:Optional[Literal['api','webhook']]=None,
             cursor:Optional[str]=Query(None,max_length=256),actor=Depends(manager)):
        return Integrations(get_database(request),settings).logs(actor,kind,cursor)

    @router.get('/integrations/{resource}')
    def machine_read(request:Request,resource:Literal['models','snapshots','evaluations'],
                     cursor:Optional[UUID]=None):
        started=perf_counter()
        database=get_database(request)
        store=Integrations(database,settings)
        workspace=SimpleNamespace(workspace=SimpleNamespace(id=settings.workspace_id))
        header=request.headers.get('authorization','')
        if len(header)>256 or not header.lower().startswith('bearer ') or len(header.split())!=2:
            raise HTTPException(401,'Cần khóa API hợp lệ',headers={'WWW-Authenticate':'Bearer'})
        token=header.split()[1]
        status,retry_after=200,0
        scope={'models':'models:read','snapshots':'snapshots:read','evaluations':'evaluations:read'}[resource]
        with store.write(workspace) as session:
            key=session.scalar(select(IntegrationKey).where(IntegrationKey.workspace_id==settings.workspace_id,
                IntegrationKey.token_hash==hash_session_token(token)))
            if not key:
                status=401
            elif key.revoked_at or aware(key.expires_at)<=utc_now():
                status=401
            else:
                retry_after=consume(session,settings.workspace_id,[('api:workspace',300),('api:key:'+key.id,key.requests_per_minute)])
                status=429 if retry_after else 403 if scope not in key.scopes else 200
                key.last_used_at=utc_now()
            if key and status!=200:
                safe_log(session,settings.workspace_id,'api',key.id,resource,status,(perf_counter()-started)*1000,
                         error={401:'key_inactive',403:'scope_denied',429:'rate_limited'}.get(status))
        if status!=200:
            raise HTTPException(status,{401:'Khóa không hợp lệ hoặc hết hạn',403:'Khóa không có quyền này',429:'Vượt giới hạn gọi API'}[status],
                headers={'Retry-After':str(retry_after)} if status==429 else {'WWW-Authenticate':'Bearer'} if status==401 else None)
        from app.model_registry_db import RegisteredModel, DeploymentTarget
        from app.workspace_data_db import DatasetSnapshot
        from app.evaluation_db import EvaluationRun
        table={'models':RegisteredModel,'snapshots':DatasetSnapshot,'evaluations':EvaluationRun}[resource]
        with database.session() as session:
            query=select(table).where(table.workspace_id==settings.workspace_id)
            if cursor:
                query=query.where(table.id>str(cursor))
            rows=session.scalars(query.order_by(table.id).limit(51)).all()
            more=len(rows)>50
            rows=rows[:50]
            if resource=='models':
                active=session.get(DeploymentTarget,(settings.workspace_id,settings.model_deployment_target))
                items=[{'id':r.id,'model_version':r.model_version,'backend':r.manifest_json.get('backend'),
                        'origin':r.origin,'active':bool(active and active.active_model_id==r.id)} for r in rows]
            elif resource=='snapshots':
                items=[{'id':r.id,'dataset_version':r.dataset_version_id,'label_version':r.label_version_id,
                        'sample_count':r.sample_count,'sha256':r.sha256,'created_at':timestamp(r.created_at)} for r in rows]
            else:
                items=[{'id':r.id,'model_version':r.frozen_json['candidate']['model_version'],
                    'dataset_version':r.frozen_json['dataset_version'],
                    'status':r.status,'created_at':timestamp(r.created_at),'gate_passed':(r.gate_json or {}).get('passed'),
                    'metrics':{key:(r.report_json or {}).get(key) for key in ('candidate','baseline')}} for r in rows]
            result={'api_version':'1','workspace_id':settings.workspace_id,'items':items,'next_cursor':rows[-1].id if more else None}
        with store.write(workspace) as session:
            safe_log(session,settings.workspace_id,'api',key.id,resource,200,(perf_counter()-started)*1000)
        return result

    return router
