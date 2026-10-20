from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from app.model_registry import ModelRegistry
from contracts.v1.models import (ApproveModelRequest, DeployModelRequest, RegisterModelRequest,
    RollbackModelRequest, ValidateModelRequest, WorkspaceModelsResponse)
from contracts.model_lifecycle_lock import LifecycleBusy

logger = logging.getLogger("vsign.registry")


def create_model_registry_router(settings, get_database, require_permission, validate_origin):
    def guard(request: Request):
        if request.method != "GET":
            validate_origin(request)
        return require_permission(request, "models:read")

    router = APIRouter(prefix="/workspace/models", tags=["models"], dependencies=[Depends(guard)])

    def mutation_guard(permission):
        def check(request: Request):
            return require_permission(request, f"models:{permission}")
        return Depends(check)

    def run(request, permission, action=None):
        actor = require_permission(request, f"models:{permission}")
        registry = ModelRegistry(get_database(request), settings)
        try:
            if action:
                action(registry, actor)
            return registry.snapshot(actor)
        except HTTPException:
            raise
        except LifecycleBusy as exc:
            raise HTTPException(409, "Đang fine-tune hoặc đăng ký mô hình. Chờ hoàn tất rồi thử lại.") from exc
        except (ValueError, OSError, RuntimeError, ValidationError) as exc:
            logger.warning("Registry verification rejected (%s)",type(exc).__name__)
            raise HTTPException(422, "Artifact hoặc báo cáo không hợp lệ. Kiểm tra thư mục cho phép, manifest và SHA256.") from exc

    @router.get("", response_model=WorkspaceModelsResponse)
    def models(request: Request):
        return run(request,"read")

    @router.post("", status_code=201, response_model=WorkspaceModelsResponse, dependencies=[mutation_guard("register")])
    def register(request: Request, payload: RegisterModelRequest):
        return run(request,"register",lambda registry,actor:registry.register(actor,payload))

    @router.post("/{model_id}/validate", response_model=WorkspaceModelsResponse, dependencies=[mutation_guard("validate")])
    def validate(request: Request, model_id: str, payload: ValidateModelRequest):
        return run(request,"validate",lambda registry,actor:registry.validate(actor,model_id,payload.report_path))

    @router.post("/{model_id}/approve", response_model=WorkspaceModelsResponse, dependencies=[mutation_guard("approve")])
    def approve(request: Request, model_id: str, payload: ApproveModelRequest):
        return run(request,"approve",lambda registry,actor:registry.approve(actor,model_id,str(payload.validation_id)))

    @router.post("/deployments", status_code=202, response_model=WorkspaceModelsResponse, dependencies=[mutation_guard("deploy")])
    def deploy(request: Request, payload: DeployModelRequest):
        return run(request,"deploy",lambda registry,actor:registry.enqueue(actor,str(payload.request_id),payload.expected_revision,str(payload.model_id)))

    @router.post("/rollback", status_code=202, response_model=WorkspaceModelsResponse, dependencies=[mutation_guard("deploy")])
    def rollback(request: Request, payload: RollbackModelRequest):
        return run(request,"deploy",lambda registry,actor:registry.enqueue(actor,str(payload.request_id),payload.expected_revision,None))

    return router
