import { expect, it } from 'vitest';
import { parseWorkspaceSettings, parseEffectiveSettings, parseRetentionPreview } from './workspaceSettings';
import { settingsSnapshot, settingsUser } from '../test/settingsFixture';

it('validates the workspace, identity and every nested settings group', () => {
  const valid = settingsSnapshot();
  expect(parseWorkspaceSettings(valid, 'local', settingsUser.id)).toEqual(valid);
  for (const bad of [null, {}, { ...valid, workspace_id: 'other' }, { ...valid, user_id: 'other' },
    { ...valid, revision: -1 }, { ...valid, retention: { ...valid.retention, automatic_deletion: true } },
    { ...valid, collection_policy: { ...valid.collection_policy, default_quota_per_label: 0 } },
    { ...valid, runtime_defaults: { capture_mode: 'unknown' } },
    { ...valid, notifications: { ...valid.notifications, preferences: { collection_completed: true } } },
    { ...valid, workspace: { name: 'Workspace', timezone: 'not/a-zone' } }]) {
    expect(() => parseWorkspaceSettings(bad, 'local', settingsUser.id)).toThrow();
  }
  const restricted = { ...valid, permissions: { manage: false }, workspace: null, retention: null, collection_policy: null };
  expect(parseWorkspaceSettings(restricted, 'local', settingsUser.id).workspace).toBeNull();
  expect(() => parseWorkspaceSettings({ ...restricted, workspace: valid.workspace }, 'local', settingsUser.id)).toThrow();
});

it('refuses foreign previews, invalid counts and unsafe effective defaults', () => {
  const preview = { api_version: '1', workspace_id: 'local', revision: 0, generated_at: '2026-10-16T00:00:00Z',
    automatic_deletion: false, candidates: { draft_samples: 2, audit_events: 1 }, protected: { samples: 4, snapshots: 1 },
    cutoffs: { draft_samples: null, audit_events: null } };
  expect(parseRetentionPreview(preview, 'local').candidates.draft_samples).toBe(2);
  expect(() => parseRetentionPreview({ ...preview, automatic_deletion: true }, 'local')).toThrow();
  expect(() => parseRetentionPreview({ ...preview, candidates: { draft_samples: -1, audit_events: 1 } }, 'local')).toThrow();
  expect(() => parseRetentionPreview(preview, 'other')).toThrow();
  const effective = { api_version: '1', workspace_id: 'local', runtime_defaults: { capture_mode: 'automatic' },
    collection: { enabled: true, process_enabled: true, require_consent: true, default_quota_per_label: 100, revision: 1 } };
  expect(parseEffectiveSettings(effective, 'local').runtime_defaults.capture_mode).toBe('automatic');
  expect(() => parseEffectiveSettings({ ...effective, collection: { ...effective.collection, process_enabled: false } }, 'local')).toThrow();
});
