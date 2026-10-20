export interface DataLabel { id: string; name: string; kind: "sign" | "negative" }
export interface DataLabels { id: string; name: string; parent_id: string | null; entries: DataLabel[]; created_at: string }
export interface DataVersion {
  id: string; name: string; label_version_id: string; quota_per_label: number; status: "draft" | "sealed";
  sample_count: number; counts: Record<string, { right: number; left: number }>; created_at: string;
}
export interface DataSession {
  id: string; dataset_version_id: string; created_by: string; state: "running" | "paused" | "stopped" | "completed";
  sample_count: number; created_at: string; updated_at: string;
}
export interface DataSnapshot {
  id: string; dataset_version_id: string; label_version_id: string; sample_count: number; sha256: string; created_at: string;
}
export interface WorkspaceDataResponse {
  api_version: "1"; workspace_id: string; collection_enabled: boolean; default_labels: string[];
  collection_policy?: { enabled: boolean; require_consent: boolean; default_quota_per_label: number; revision: number; process_enabled: boolean };
  permissions: { manage: boolean; collect: boolean };
  labels: DataLabels[]; datasets: DataVersion[]; sessions: DataSession[]; snapshots: DataSnapshot[];
}
