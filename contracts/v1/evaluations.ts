export interface EvaluationMetrics {
  accuracy: number | null;
  macro_f1: number | null;
  false_accept_rate: number | null;
  latency_p95_ms: number;
  negative_count: number;
  false_accepts: number;
  uncertain_count: number;
  per_class: { label: string; support: number; recall: number | null; precision: number | null; f1: number | null; errors: number }[];
}
export interface EvaluationGate { passed: boolean; checks: { name: string; passed: boolean; detail: string }[] }
export interface EvaluationReport {
  schema_version: '1'; candidate_artifact_sha256: string; baseline_artifact_sha256: string; labels_sha256: string;
  source_run_id: string; preprocessing_version: string; protocol_version: string;
  confidence_threshold: number; margin_threshold: number; baseline_confidence_threshold: number; baseline_margin_threshold: number;
  dataset_snapshot_sha256: string; held_out: boolean; independent_negatives: boolean; positive_count: number; negative_count: number;
  candidate: EvaluationMetrics; baseline: EvaluationMetrics; runtime: Record<string,string>;
}
export interface EvaluationRun {
  id: string; model_id: string; baseline_model_id: string; model_version: string; baseline_model_version: string;
  snapshot_id: string; dataset_version: string; snapshot_sha256: string; backend: string; sample_count: number;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'; progress: number; requested_by: string;
  created_at: string; started_at: string | null; finished_at: string | null; error: string | null;
  report: EvaluationReport | null; gate: EvaluationGate | null; baseline_current: boolean;
}
export interface WorkspaceEvaluationsResponse {
  api_version: '1'; workspace_id: string; permissions: { create: boolean; cancel: boolean }; active_model_id: string | null;
  workers: Record<string,boolean>;
  models: { id: string; model_version: string; backend: string; active: boolean }[];
  snapshots: { id: string; dataset_version: string; dataset_name: string; sample_count: number; sha256: string }[];
  runs: EvaluationRun[];
}
