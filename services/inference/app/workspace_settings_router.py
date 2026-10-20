from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.platform_auth import SESSION_COOKIE_NAME
from app.workspace_settings import WorkspaceSettings
from contracts.v1.settings import UpdateNotifications, UpdateWorkspaceSettings, WorkspaceSettingsResponse


def create_workspace_settings_router(settings, get_database, require_permission, validate_origin):
    router = APIRouter(prefix='/workspace/settings', tags=['settings'])

    def guard(permission):
        def check(request: Request):
            if request.method != 'GET':
                validate_origin(request)
            return require_permission(request, permission)
        return check

    reader, manager = guard('settings:preferences'), guard('settings:manage')

    def run(request, actor, operation):
        store = WorkspaceSettings(get_database(request), settings, request.cookies.get(SESSION_COOKIE_NAME))
        try:
            return operation(store)
        except SQLAlchemyError:
            raise HTTPException(503, 'Chưa xác nhận cài đặt. Làm mới hoặc thử lại cùng mã yêu cầu') from None

    @router.get('', response_model=WorkspaceSettingsResponse)
    def overview(request: Request, actor=Depends(reader)):
        return run(request, actor, lambda store: store.overview(actor))

    @router.get('/effective')
    def effective(request: Request, actor=Depends(reader)):
        return run(request, actor, lambda store: store.effective(actor))

    @router.get('/retention/preview')
    def preview(request: Request, actor=Depends(manager)):
        return run(request, actor, lambda store: store.preview(actor))

    @router.post('/update', response_model=WorkspaceSettingsResponse)
    def update(request: Request, payload: UpdateWorkspaceSettings, actor=Depends(manager)):
        return run(request, actor, lambda store: store.update(actor, payload))

    @router.post('/notifications', response_model=WorkspaceSettingsResponse)
    def notifications(request: Request, payload: UpdateNotifications, actor=Depends(reader)):
        return run(request, actor, lambda store: store.notifications(actor, payload))

    return router
