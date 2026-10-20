from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ModelMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterModelRequest(ModelMutation):
    manifest_path: str = Field(min_length=1, max_length=2048)
    artifact_path: str = Field(min_length=1, max_length=2048)
    labels_path: str = Field(min_length=1, max_length=2048)


class ValidateModelRequest(ModelMutation):
    report_path: str = Field(min_length=1, max_length=2048)


class ApproveModelRequest(ModelMutation):
    validation_id: UUID


class RollbackModelRequest(ModelMutation):
    request_id: UUID
    expected_revision: int = Field(strict=True, ge=0)


class DeployModelRequest(RollbackModelRequest):
    model_id: UUID


class ModelGateCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class ModelValidationSummary(BaseModel):
    id: str
    passed: bool
    baseline_model_id: str
    report_sha256: str
    created_at: str
    checks: list[ModelGateCheck]


class RegisteredModelSummary(BaseModel):
    id: str
    model_version: str
    backend: str
    artifact_sha256: str
    labels_sha256: str
    labels_count: int
    source_run_id: str
    created_at: str
    origin: Literal["candidate", "baseline"]
    status: Literal["candidate", "validated", "approved", "active", "baseline"]
    validation: Optional[ModelValidationSummary]
    approved_validation_id: Optional[str]
    approved_by: Optional[str]
    approved_at: Optional[str]


class ModelDeploymentTarget(BaseModel):
    target_id: str
    runtime_url: str
    backend: str
    active_model_id: Optional[str]
    previous_model_id: Optional[str]
    revision: int
    pending_job_id: Optional[str]
    worker_online: bool
    observed_model_id: Optional[str]


class ModelDeploymentJob(BaseModel):
    id: str
    operation: Literal["deploy", "rollback"]
    from_model_id: str
    to_model_id: str
    expected_revision: int
    status: Literal["queued", "loading", "succeeded", "failed"]
    requested_by: str
    created_at: str
    finished_at: Optional[str]
    error: Optional[str]


class ModelPermissions(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    can_register: bool = Field(alias="register")
    can_validate: bool = Field(alias="validate")
    approve: bool
    deploy: bool


class WorkspaceModelsResponse(BaseModel):
    api_version: Literal["1"] = "1"
    workspace_id: str
    target: Optional[ModelDeploymentTarget]
    models: list[RegisteredModelSummary]
    deployments: list[ModelDeploymentJob]
    permissions: ModelPermissions
