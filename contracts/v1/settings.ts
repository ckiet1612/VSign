export interface WorkspaceOptions { name: string; timezone: string }
export interface RetentionPolicy {
  draft_samples_days: number | null;
  audit_events_days: number | null;
  automatic_deletion: false;
}
export interface CollectionPolicy { enabled: boolean; require_consent: boolean; default_quota_per_label: number }
export interface RuntimeDefaults { capture_mode: 'manual' | 'automatic' }
export interface NotificationPreferences { collection_completed: boolean; evaluation_finished: boolean; integration_failed: boolean }
export interface WorkspaceSettingsSnapshot {
  api_version: '1'; workspace_id: string; user_id: string;
  revision: number; updated_at: string | null; permissions: { manage: boolean };
  workspace: WorkspaceOptions | null; retention: RetentionPolicy | null;
  collection_policy: CollectionPolicy | null; runtime_defaults: RuntimeDefaults;
  process_collection_enabled: boolean;
  notifications: { revision: number; updated_at: string | null; preferences: NotificationPreferences; delivery: 'not_configured' };
  request_id: string | null; applied_revision: number | null;
}
export interface RetentionPreview {
  api_version: '1'; workspace_id: string; revision: number; generated_at: string;
  automatic_deletion: false; candidates: { draft_samples: number; audit_events: number };
  protected: { samples: number; snapshots: number };
  cutoffs: { draft_samples: string | null; audit_events: string | null };
}
export interface EffectiveWorkspaceSettings {
  api_version: '1'; workspace_id: string;
  collection: CollectionPolicy & { revision: number; process_enabled: boolean };
  runtime_defaults: RuntimeDefaults;
}
export type SettingsTab = 'workspace' | 'retention' | 'collection' | 'runtime' | 'notifications';
