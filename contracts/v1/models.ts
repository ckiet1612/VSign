export interface ModelGateCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ModelValidationSummary {
  id: string;
  passed: boolean;
  baseline_model_id: string;
  report_sha256: string;
  created_at: string;
  checks: ModelGateCheck[];
}

export interface RegisteredModelSummary {
  id: string;
  model_version: string;
  backend: string;
  artifact_sha256: string;
  labels_sha256: string;
  labels_count: number;
  source_run_id: string;
  created_at: string;
  origin: "candidate" | "baseline";
  status: "candidate" | "validated" | "approved" | "active" | "baseline";
  validation: ModelValidationSummary | null;
  approved_validation_id: string | null;
  approved_by: string | null;
  approved_at: string | null;
}

export interface ModelDeploymentTarget {
  target_id: string;
  runtime_url: string;
  backend: string;
  active_model_id: string | null;
  previous_model_id: string | null;
  revision: number;
  pending_job_id: string | null;
  worker_online: boolean;
  observed_model_id: string | null;
}

export interface ModelDeploymentJob {
  id: string;
  operation: "deploy" | "rollback";
  from_model_id: string;
  to_model_id: string;
  expected_revision: number;
  status: "queued" | "loading" | "succeeded" | "failed";
  requested_by: string;
  created_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface WorkspaceModelsResponse {
  api_version: "1";
  workspace_id: string;
  target: ModelDeploymentTarget | null;
  models: RegisteredModelSummary[];
  deployments: ModelDeploymentJob[];
  permissions: { register: boolean; validate: boolean; approve: boolean; deploy: boolean };
}
