from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

from app.platform_auth import SESSION_COOKIE_NAME
from app.team import WorkspaceTeam
from contracts.v1.team import AcceptInvitationRequest, CreateInvitationRequest, InspectInvitationRequest, TeamRequest, UpdateMemberRequest


class PrivateTeamRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default validation response includes raw password/token inputs.
                return JSONResponse(status_code=422, content={'detail':'Dữ liệu yêu cầu không hợp lệ.'})
        return private_handler


def create_team_router(settings, get_database, require_permission, validate_origin, hasher):
    router = APIRouter(tags=['team'], route_class=PrivateTeamRoute)
    base = '/workspace/team'

    def manager(request: Request):
        if request.method != 'GET':
            validate_origin(request)
        return require_permission(request, 'members:manage')

    def store(request):
        return WorkspaceTeam(get_database(request), settings, hasher, request.cookies.get(SESSION_COOKIE_NAME))

    def mutate(operation):
        try:
            return operation()
        except SQLAlchemyError:
            raise HTTPException(503, 'Chưa xác nhận thao tác. Làm mới và thử lại cùng mã yêu cầu') from None

    @router.get(base)
    def overview(request: Request, search: str = Query('',max_length=120), cursor: Optional[UUID] = None, actor=Depends(manager)):
        return store(request).overview(actor,search,cursor)

    @router.get(base+'/roles')
    def roles(request: Request, actor=Depends(manager)):
        return store(request).roles(actor)

    @router.get(base+'/invitations')
    def invitations(request: Request, cursor: Optional[UUID] = None, actor=Depends(manager)):
        return store(request).invitations(actor,cursor)

    @router.get(base+'/audit')
    def audit(request: Request, cursor: Optional[str] = Query(None,max_length=256), member_id: Optional[UUID] = None,
              action: Optional[str] = Query(None,max_length=120), from_at: Optional[datetime] = None,
              to_at: Optional[datetime] = None, actor=Depends(manager)):
        return store(request).history(actor,cursor,member_id,action,from_at,to_at)

    @router.post(base+'/members/{identity}/update')
    def update(request: Request, identity: UUID, payload: UpdateMemberRequest, actor=Depends(manager)):
        def operation():
            service = store(request)
            service.update(actor,identity,payload)
            return service.overview(actor)
        return mutate(operation)

    @router.post(base+'/invitations',status_code=201)
    def invite(request: Request, payload: CreateInvitationRequest, actor=Depends(manager)):
        def operation():
            service = store(request)
            result = service.create_invitation(actor,payload)
            return {**service.invitations(actor),**result}
        return mutate(operation)

    @router.post(base+'/invitations/{identity}/revoke')
    def revoke(request: Request, identity: UUID, payload: TeamRequest, actor=Depends(manager)):
        def operation():
            service = store(request)
            service.revoke_invitation(actor,identity,payload)
            return service.invitations(actor)
        return mutate(operation)

    @router.post('/invitations/inspect')
    def inspect(request: Request, payload: InspectInvitationRequest):
        validate_origin(request)
        return mutate(lambda:store(request).inspect(payload,request.client.host if request.client else 'unknown'))

    @router.post('/invitations/accept')
    def accept(request: Request, payload: AcceptInvitationRequest):
        validate_origin(request)
        return mutate(lambda:store(request).accept(payload,request.client.host if request.client else 'unknown'))

    return router
