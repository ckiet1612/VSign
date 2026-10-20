from datetime import datetime, date
from typing import Literal

from pydantic import BaseModel


class DashboardTotals(BaseModel):
    samples: int
    datasets_draft: int
    datasets_sealed: int
    models: int
    evaluations: int


class DashboardPeriod(BaseModel):
    samples: int
    evaluations: int
    events: int


class DailySamples(BaseModel):
    date: date
    count: int


class LabelProgress(BaseModel):
    label: str
    count: int
    target: int


class DashboardActivity(BaseModel):
    id: str
    event_type: str
    outcome: str
    occurred_at: datetime


class DashboardEvaluation(BaseModel):
    id: str
    model_version: str
    status: str
    progress: int
    created_at: datetime


WorkerStatus = Literal["online", "offline", "not_configured"]


class DashboardWorkers(BaseModel):
    deployment: WorkerStatus
    evaluation: WorkerStatus
    integration: WorkerStatus


class DashboardResponse(BaseModel):
    api_version: Literal["1"] = "1"
    workspace_id: str
    generated_at: datetime
    timezone: Literal["UTC"] = "UTC"
    days: Literal[7, 30, 90]
    start_date: date
    totals: DashboardTotals
    period: DashboardPeriod
    daily_samples: list[DailySamples]
    label_progress: list[LabelProgress]
    workers: DashboardWorkers
    recent_activity: list[DashboardActivity]
    recent_evaluations: list[DashboardEvaluation]
