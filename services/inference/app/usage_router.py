from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.usage import store_conversation, usage_report
from contracts.v1.usage import ConversationSummaryRequest, ConversationSummaryResponse, UsageReportResponse


def create_usage_router(settings, get_database, require_permission, validate_origin):
    router = APIRouter(prefix='/workspace/usage', tags=['usage'])

    @router.post('/conversations', response_model=ConversationSummaryResponse, status_code=201)
    def record_conversation(request: Request, payload: ConversationSummaryRequest, response: Response):
        validate_origin(request)
        current = require_permission(request, 'recognize:use')
        try:
            created = store_conversation(get_database(request), current.workspace.id, current, payload)
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail='Chưa ghi được thống kê. Hãy thử lại với cùng ID.') from exc
        response.status_code = 201 if created else 200
        return ConversationSummaryResponse(id=payload.id, status='recorded' if created else 'duplicate')

    @router.get('/report', response_model=UsageReportResponse)
    def report(request: Request, response: Response, days: int = Query(default=30)):
        current = require_permission(request, 'reports:read')
        if days not in (7, 30, 90):
            raise HTTPException(status_code=422, detail='Khoảng thống kê phải là 7, 30 hoặc 90 ngày')
        response.headers['Cache-Control'] = 'no-store'
        return usage_report(get_database(request), current.workspace.id, days)

    return router
