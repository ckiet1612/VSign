import type { WorkspaceSettingsSnapshot } from '../../../../contracts/v1/settings';
import type { AuthenticatedUser } from '../../../../contracts/v1/workspace';

export const settingsUser: AuthenticatedUser = { id: '123e4567-e89b-12d3-a456-426614174001',
  email: 'admin@example.com', display_name: 'Admin', role: 'admin' };
export const settingsSnapshot = (): WorkspaceSettingsSnapshot => ({
  api_version: '1', workspace_id: 'local', user_id: settingsUser.id, revision: 0, updated_at: null,
  permissions: { manage: true }, workspace: { name: 'Workspace Việt', timezone: 'UTC' },
  retention: { draft_samples_days: null, audit_events_days: null, automatic_deletion: false },
  collection_policy: { enabled: true, require_consent: false, default_quota_per_label: 100 },
  runtime_defaults: { capture_mode: 'manual' }, process_collection_enabled: true,
  notifications: { revision: 0, updated_at: null, preferences: {
    collection_completed: true, evaluation_finished: true, integration_failed: true }, delivery: 'not_configured' },
  request_id: null, applied_revision: null,
});
export function savedSettings(id: string, change: Partial<WorkspaceSettingsSnapshot> = {}): WorkspaceSettingsSnapshot {
  return { ...settingsSnapshot(), ...change, revision: 1, updated_at: '2026-10-16T00:00:00Z', request_id: id, applied_revision: 1 };
}
