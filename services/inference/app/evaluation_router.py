from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.evaluations import Evaluations
from contracts.v1.evaluations import CreateEvaluationRequest, WorkspaceEvaluationsResponse

logger = logging.getLogger('vsign.evaluations')


def create_evaluation_router(settings, get_database, require_permission, validate_origin):
    router = APIRouter(prefix='/workspace/evaluations', tags=['evaluations'])

    def guard(permission):
        def check(request: Request):
            if request.method != 'GET':
                validate_origin(request)
            return require_permission(request, permission)
        return check

    reader, creator, canceller = (guard('evaluation:' + suffix) for suffix in ('read','create','cancel'))

    def run(request, actor, operation=None):
        store = Evaluations(get_database(request), settings)
        try:
            if operation:
                operation(store)
            return store.overview(actor)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, 'Model hoặc snapshot không hợp lệ') from exc
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            logger.error('Evaluation request failed (%s)', type(exc).__name__)
            raise HTTPException(503, 'Chưa xác nhận yêu cầu; hãy thử lại cùng mã yêu cầu') from exc

    @router.get('', response_model=WorkspaceEvaluationsResponse)
    def overview(request: Request, actor=Depends(reader)):
        return run(request, actor)

    @router.post('', response_model=WorkspaceEvaluationsResponse, status_code=201)
    def create(request: Request, payload: CreateEvaluationRequest, actor=Depends(creator)):
        return run(request, actor, lambda store: store.create(actor, payload))

    @router.post('/{identity}/cancel', response_model=WorkspaceEvaluationsResponse)
    def cancel(request: Request, identity: UUID, actor=Depends(canceller)):
        return run(request, actor, lambda store: store.cancel(actor, identity))

    return router
