# Workspace Settings, Phase 8

Approved in chat on 2026-10-16. Implement in the existing dirty checkout; no
commit, push, model promotion, training, real collection or deletion.

## Persistence And Authority

Add migration `0010_workspace_settings`. Store workspace configuration and its
revision separately from each user's workspace-local notification preferences.
Workspace name stays in `workspaces`, never overwrite it from bootstrap on
restart. Owner/admin manage workspace settings; all authenticated active members
can manage only their own preferences. API keys never inherit browser authority.
Mutation request IDs are idempotent and bind actor, workspace, operation and
payload. Expected revisions reject stale updates. Revalidate membership and
session under the same SQLite writer/PostgreSQL workspace lock as every write.
Settings changes and their before/after audit are one transaction.

## Five Groups

- Workspace: name and validated IANA timezone. Environment, workspace ID, URLs,
  secrets, model pointers and deployment controls are not editable.
- Retention: optional 1..3650 day draft-sample and audit-event horizons. Automatic
  deletion is always false. Preview uses database counts, not file deletion;
  exclude sealed/snapshotted datasets and datasets with active/paused sessions.
  Preserve all snapshots, model artifacts, evaluation evidence and legacy data.
- Collection: workspace enable switch AND process `COLLECTION_ENABLED` hard cap,
  explicit consent requirement (off for existing behavior by default), default
  quota 100 per label (1..10000). Quota applies only to new datasets when omitted.
  Check policy inside collection start/resume/save transactions; never count an
  unacknowledged sample. Persist consent on collection sessions, not in audit
  payloads or browser localStorage. Existing sessions without consent must be
  stopped and replaced when consent becomes required.
- Runtime: recognition capture mode manual/automatic, default manual. Apply once
  to a fresh browser workspace session before camera use or a manual mode change.
  Never change an active session, server model, thresholds or queue parameters.
  Collection's existing automatic default and manual transcript insertion remain.
- Notifications: collection completion, evaluation completion, integration
  failure booleans, independently versioned per user/workspace. Store choices;
  delivery remains explicitly unavailable. No email, push or invented alerts.

## API And UI

GET `/api/v1/workspace/settings`: versioned, workspace/user-bound snapshot,
management permissions, personal preferences, runtime defaults; private groups
are null for non-managers. POST `/settings/update`: manager-only partial update
of full sections with request_id and expected_revision. POST
`/settings/notifications`: current user's complete preferences and own revision.
GET `/settings/retention/preview`: manager-only counts with revision and timestamp.
GET `/settings/effective`: non-secret collection/runtime policy for workspace use.

Settings navigation is enabled for active authenticated members. Reuse current
workspace styles and icon module, five tabs for managers, notifications only for
other members. Loading/error/denied/stale states lock writes. Validate envelopes
and nested values at runtime, discard late responses after identity/workspace
changes, retain exact uncertain mutation for explicit retry. Refresh must not
silently overwrite dirty form inputs. Mask personal preference audit from other
non-manager users; no new webhook event types. Update collection UI with consent
only when required. Do not change recognition layout.

## Verification And Activation

Tests first: restart persistence, scope/role/session boundaries, invalid inputs,
revision/idempotency races, audit atomicity/privacy, retention read-only counts,
collection hard cap/consent and new-only defaults, malformed/stale/late frontend
responses, desktop/mobile settings forms. Use isolated SQLite/mock fixtures for
writes. Before local activation back up DB, capture runtime metadata and model/
data fingerprints, migrate and restart only processes sharing the affected DB
while preserving their exact environment. Report fixture and live evidence
separately; no real-camera, PostgreSQL/load or production acceptance claim.
