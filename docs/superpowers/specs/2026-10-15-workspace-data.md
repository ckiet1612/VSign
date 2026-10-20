# Workspace Data Phase 4

Approved in chat on 2026-10-15. Enterprise admin, no new login or model rights.

## Data Ownership

Persist label versions, dataset versions, collection sessions, committed samples
and immutable snapshots in the platform DB. Every lookup and write is scoped to
the authenticated workspace, never a client-supplied tenant. New media resides
under `COLLECTION_DIR/workspaces/<workspace>/datasets/<version>`; legacy samples
remain untouched and are never implicitly imported.

## Contracts And Flow

Use `/api/v1/workspace/data` for reads and mutations, independently of the
selected inference endpoint. Owner/admin manage labels, drafts, quotas and seal
snapshots. Operator collects; reviewer/viewer read. Local admin stays passwordless.
Dataset labels have stable UUID identities and immutable versions; a draft binds
one label version. Editing labels creates a new version, not a change to existing
datasets or production vocabulary. Default quota is 100 per label across hands
and sessions. No deletion/export/automatic training/deployment is added.

Sessions transition running -> paused -> running -> stopped/completed. Writes
serialize with session transitions and snapshot creation. A committed capture
UUID retries idempotently even after session closure; an uncommitted request after
closure is rejected. Client stops capture immediately and waits for its in-flight
save before requesting closure. Page reload shows server sessions for recovery.

## Snapshots

Seal only a nonempty draft with all sessions closed. Copy exactly committed
MP4/JSON pairs into a separate snapshot directory and record SHA256 and a canonical
manifest binding workspace, dataset version and ordered label version. Atomic
publication and DB commit precede success. Recovery never accepts uncommitted
media as samples. Mutations after sealing are forbidden. Verify all bytes before
returning a snapshot manifest for a future training consumer. Existing standalone
training scripts are not newly launched or reconfigured by phase 4.

## UI And Verification

Data has Thu mẫu, Phiên thu, Bộ dữ liệu, Danh mục ký hiệu views using existing
tokens/icons and real backend state. No fabricated counts, empty-state history or
technical path entry. Disable changes on stale data and clear scope-specific state
on logout/workspace changes. Test role/tenant boundaries, retries, concurrent quota,
close/save races, snapshots, failed writes, label history and the existing camera
workflow. Use disposable media for E2E, never capture from a real camera for QA.
