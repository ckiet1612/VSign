from __future__ import annotations

from typing import Literal, Optional
from datetime import datetime
from uuid import UUID

from pydantic import Field
from contracts.v1.data import DataRequest


class CreateEvaluationRequest(DataRequest):
    request_id: UUID
    model_id: UUID
    snapshot_id: UUID


class GateCheck(DataRequest):
    name: str
    passed: bool
    detail: str


class EvaluationGate(DataRequest):
    passed: bool
    checks: list[GateCheck]


class ClassMetrics(DataRequest):
    label: str
    support: int
    recall: Optional[float]
    precision: Optional[float]
    f1: Optional[float]
    errors: int


class EvaluationMetrics(DataRequest):
    accuracy: Optional[float]
    macro_f1: Optional[float]
    false_accept_rate: Optional[float]
    latency_p95_ms: float
    per_class: list[ClassMetrics]
    negative_count: int
    false_accepts: int
    uncertain_count: int


class EvaluationReport(DataRequest):
    schema_version: Literal['1']
    candidate_artifact_sha256: str
    baseline_artifact_sha256: str
    labels_sha256: str
    source_run_id: str
    preprocessing_version: str
    protocol_version: str
    confidence_threshold: float
    margin_threshold: float
    baseline_confidence_threshold: float
    baseline_margin_threshold: float
    dataset_snapshot_sha256: str
    held_out: bool
    independent_negatives: bool
    positive_count: int
    negative_count: int
    candidate: EvaluationMetrics
    baseline: EvaluationMetrics
    runtime: dict[str, str]


class EvaluationRunResponse(DataRequest):
    id: str
    model_id: str
    baseline_model_id: str
    model_version: str
    baseline_model_version: str
    snapshot_id: str
    dataset_version: str
    snapshot_sha256: str
    backend: str
    sample_count: int
    status: Literal['queued', 'running', 'completed', 'failed', 'cancelled']
    progress: int
    requested_by: str
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    error: Optional[str]
    report: Optional[EvaluationReport]
    gate: Optional[EvaluationGate]
    baseline_current: bool


class EvaluationModelChoice(DataRequest):
    id: str
    model_version: str
    backend: str
    active: bool


class EvaluationSnapshotChoice(DataRequest):
    id: str
    dataset_version: str
    dataset_name: str
    sample_count: int
    sha256: str


class EvaluationPermissions(DataRequest):
    create: bool
    cancel: bool


class WorkspaceEvaluationsResponse(DataRequest):
    api_version: Literal['1'] = '1'
    workspace_id: str
    permissions: EvaluationPermissions
    active_model_id: Optional[str]
    workers: dict[str, bool]
    models: list[EvaluationModelChoice]
    snapshots: list[EvaluationSnapshotChoice]
    runs: list[EvaluationRunResponse] = Field(max_length=50)
