from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.collection import CollectionConflict
from app.validation import FrameValidationError
from app.workspace_data import WorkspaceData
from contracts.v1.data import (CreateDatasetRequest, CreateLabelsRequest, QuotaRequest,
    SessionStateRequest, SnapshotRequest, StartSessionRequest, WorkspaceDataResponse, WorkspaceSampleRequest)
from contracts.v1.inference import CollectionSampleResponse

logger = logging.getLogger("vsign.data")


def create_workspace_data_router(settings, get_database, require_permission, validate_origin):
    def guard(permission):
        def check(request: Request):
            if request.method != "GET":
                validate_origin(request)
            return require_permission(request, permission)
        return check

    router = APIRouter(prefix="/workspace/data", tags=["data"])
    reader, manager, collector = guard("data:read"), guard("data:manage"), guard("data:use")

    def run(request, actor, operation=None, sample=False):
        store = WorkspaceData(get_database(request), settings)
        try:
            result = operation(store) if operation else None
            return result if sample else store.overview(actor)
        except HTTPException:
            raise
        except (CollectionConflict, FrameValidationError, ValueError) as exc:
            raise HTTPException(409 if isinstance(exc, CollectionConflict) else 422, "Mẫu hoặc yêu cầu dữ liệu không hợp lệ") from exc
        except (SQLAlchemyError, OSError, RuntimeError) as exc:
            logger.error("Workspace data operation failed (%s)", type(exc).__name__)
            raise HTTPException(503, "Chưa xác nhận được dữ liệu; hãy làm mới và thử lại cùng mã yêu cầu") from exc

    @router.get("", response_model=WorkspaceDataResponse)
    def overview(request: Request, actor=Depends(reader)):
        return run(request, actor)

    @router.post("/labels", response_model=WorkspaceDataResponse, status_code=201)
    def labels(request: Request, payload: CreateLabelsRequest, actor=Depends(manager)):
        return run(request, actor, lambda store: store.labels(actor, payload))

    @router.post("/datasets", response_model=WorkspaceDataResponse, status_code=201)
    def dataset(request: Request, payload: CreateDatasetRequest, actor=Depends(manager)):
        return run(request, actor, lambda store: store.dataset(actor, payload))

    @router.post("/datasets/{identity}/quota", response_model=WorkspaceDataResponse)
    def quota(request: Request, identity: UUID, payload: QuotaRequest, actor=Depends(manager)):
        return run(request, actor, lambda store: store.quota(actor, identity, payload))

    @router.post("/sessions", response_model=WorkspaceDataResponse, status_code=201)
    def start(request: Request, payload: StartSessionRequest, actor=Depends(collector)):
        return run(request, actor, lambda store: store.start(actor, payload))

    @router.post("/sessions/{identity}/state", response_model=WorkspaceDataResponse)
    def transition(request: Request, identity: UUID, payload: SessionStateRequest, actor=Depends(collector)):
        return run(request, actor, lambda store: store.transition(actor, identity, payload))

    @router.post("/sessions/{identity}/samples", response_model=CollectionSampleResponse)
    def sample(request: Request, identity: UUID, payload: WorkspaceSampleRequest, actor=Depends(collector)):
        return run(request, actor, lambda store: store.save(actor, identity, payload), sample=True)

    @router.post("/datasets/{identity}/snapshot", response_model=WorkspaceDataResponse, status_code=201)
    def seal(request: Request, identity: UUID, payload: SnapshotRequest, actor=Depends(manager)):
        return run(request, actor, lambda store: store.seal(actor, identity, payload))

    @router.get("/snapshots/{identity}/manifest")
    def manifest(request: Request, identity: UUID, actor=Depends(reader)):
        return run(request, actor, lambda store: store.manifest(actor, identity), sample=True)

    return router
