import type { CollectionPolicy, EffectiveWorkspaceSettings, NotificationPreferences, RetentionPolicy,
  RetentionPreview, RuntimeDefaults, WorkspaceOptions, WorkspaceSettingsSnapshot } from '../../../../contracts/v1/settings';

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const integer = (value: unknown, max = 2147483647): value is number => Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= max;
const date = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
const optionalDate = (value: unknown) => value === null || date(value);
const uuid = (value: unknown) => typeof value === 'string' && /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(value);
function invalid(): never { throw new Error('invalid_settings'); }
function envelope(value: unknown, workspace: string): asserts value is Record<string, unknown> {
  if (!record(value) || value.api_version !== '1' || value.workspace_id !== workspace) invalid();
}
function runtime(value: unknown): RuntimeDefaults {
  if (!record(value) || !['manual', 'automatic'].includes(String(value.capture_mode))) return invalid();
  return { capture_mode: value.capture_mode as RuntimeDefaults['capture_mode'] };
}
function collection(value: unknown): CollectionPolicy {
  if (!record(value) || typeof value.enabled !== 'boolean' || typeof value.require_consent !== 'boolean' ||
    !integer(value.default_quota_per_label, 10000) || value.default_quota_per_label < 1) return invalid();
  return { enabled: value.enabled, require_consent: value.require_consent, default_quota_per_label: value.default_quota_per_label };
}
function retention(value: unknown): RetentionPolicy {
  const days = (v: unknown) => v === null || integer(v, 3650) && v >= 1;
  if (!record(value) || value.automatic_deletion !== false || !days(value.draft_samples_days) || !days(value.audit_events_days)) return invalid();
  return { draft_samples_days: value.draft_samples_days as number | null, audit_events_days: value.audit_events_days as number | null, automatic_deletion: false };
}
function workspaceOptions(value: unknown): WorkspaceOptions {
  if (!record(value) || typeof value.name !== 'string' || !value.name.trim() || value.name.length > 120 ||
    /[\p{Cc}\p{Cf}]/u.test(value.name) || typeof value.timezone !== 'string' || value.timezone.length > 64) return invalid();
  try { new Intl.DateTimeFormat('vi-VN', { timeZone: value.timezone }); } catch { return invalid(); }
  return { name: value.name, timezone: value.timezone };
}
function preferences(value: unknown): NotificationPreferences {
  if (!record(value) || typeof value.collection_completed !== 'boolean' || typeof value.evaluation_finished !== 'boolean' ||
    typeof value.integration_failed !== 'boolean') return invalid();
  return { collection_completed: value.collection_completed, evaluation_finished: value.evaluation_finished, integration_failed: value.integration_failed };
}
export function parseWorkspaceSettings(value: unknown, workspace: string, userId: string): WorkspaceSettingsSnapshot {
  envelope(value, workspace);
  if (value.user_id !== userId || !integer(value.revision) || !optionalDate(value.updated_at) ||
    !record(value.permissions) || typeof value.permissions.manage !== 'boolean' || typeof value.process_collection_enabled !== 'boolean' ||
    !record(value.notifications) || !integer(value.notifications.revision) || !optionalDate(value.notifications.updated_at) ||
    value.notifications.delivery !== 'not_configured' || !(value.request_id === null || uuid(value.request_id)) ||
    !(value.applied_revision === null || integer(value.applied_revision)) ||
    (value.request_id === null) !== (value.applied_revision === null)) return invalid();
  const manage = value.permissions.manage;
  if (!manage && (value.workspace !== null || value.retention !== null || value.collection_policy !== null)) return invalid();
  return { api_version: '1', workspace_id: workspace, user_id: userId, revision: value.revision, updated_at: value.updated_at as string | null,
    permissions: { manage }, workspace: manage ? workspaceOptions(value.workspace) : null,
    retention: manage ? retention(value.retention) : null, collection_policy: manage ? collection(value.collection_policy) : null,
    runtime_defaults: runtime(value.runtime_defaults), process_collection_enabled: value.process_collection_enabled,
    notifications: { revision: value.notifications.revision, updated_at: value.notifications.updated_at as string | null,
      preferences: preferences(value.notifications.preferences), delivery: 'not_configured' },
    request_id: value.request_id as string | null, applied_revision: value.applied_revision as number | null };
}
export function parseEffectiveSettings(value: unknown, workspace: string): EffectiveWorkspaceSettings {
  envelope(value, workspace);
  const policy = collection(value.collection);
  if (!record(value.collection) || !integer(value.collection.revision) || typeof value.collection.process_enabled !== 'boolean' ||
    policy.enabled && !value.collection.process_enabled) return invalid();
  return { api_version: '1', workspace_id: workspace, runtime_defaults: runtime(value.runtime_defaults),
    collection: { ...policy, revision: value.collection.revision, process_enabled: value.collection.process_enabled } };
}
export function parseRetentionPreview(value: unknown, workspace: string): RetentionPreview {
  envelope(value, workspace);
  if (!integer(value.revision) || !date(value.generated_at) || value.automatic_deletion !== false ||
    !record(value.candidates) || !integer(value.candidates.draft_samples) || !integer(value.candidates.audit_events) ||
    !record(value.protected) || !integer(value.protected.samples) || !integer(value.protected.snapshots) ||
    !record(value.cutoffs) || !optionalDate(value.cutoffs.draft_samples) || !optionalDate(value.cutoffs.audit_events)) return invalid();
  return { api_version: '1', workspace_id: workspace, revision: value.revision, generated_at: value.generated_at,
    automatic_deletion: false, candidates: { draft_samples: value.candidates.draft_samples, audit_events: value.candidates.audit_events },
    protected: { samples: value.protected.samples, snapshots: value.protected.snapshots },
    cutoffs: { draft_samples: value.cutoffs.draft_samples as string | null, audit_events: value.cutoffs.audit_events as string | null } };
}
