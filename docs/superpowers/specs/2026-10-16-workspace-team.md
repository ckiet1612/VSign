# Workspace Members And Permissions

Approved Phase 7: enterprise members, fixed roles, workspace invitations and
permission audit. Preserve passwordless local admin, inference/data/models and
all unrelated dirty files. No real invitation, email, commit or push.

## Access And Persistence

Keep owner/admin/operator/reviewer/viewer, never grant model_admin via enterprise
APIs. Owner manages admin and lower roles; admin manages only lower roles. No
self mutation, owner mutation, local-admin mutation or internal-role mutation.
Protect the last active owner/admin under a workspace writer lock. Membership
status active/suspended/removed and revision are workspace-scoped; never change
User.is_active or delete global accounts. Auth/login recheck membership status;
role changes apply on subsequent requests, suspension/removal revoke sessions
for this workspace. Team mutations revalidate actor, membership and auth session
under the same SQLite immediate/PostgreSQL workspace row lock as the mutation.
Expected revision prevents stale member updates; request IDs make writes
idempotent, conflict on changed actor/operation/body, never store one-time keys.

## API

GET /api/v1/workspace/team: paginated members, search, counts, capabilities.
GET /team/roles: fixed role matrix reflecting backend permissions.
GET /team/invitations: paginated invitation state.
GET /team/audit: permission events with member/action/time filters and pagination.
POST /team/members/{user_id}/update: request_id, expected_revision, role/status.
POST /team/invitations: request_id, email, role, expires_in_days (1..14, default7).
POST /team/invitations/{id}/revoke: request_id.
All paths above except the first share /api/v1/workspace prefix. Reads and
writes require owner/admin; stale UI locks writes. API keys never inherit admin.

POST /api/v1/invitations/inspect and /accept: token in bounded JSON only, never
URL/query/access log. Anonymous routes use explicit token/account credentials,
not implicit local-admin/cookie identity. 256-bit token, hash only, expires,
revocable, once accepted cannot grant membership again. Existing users must
provide their current password; new users set a >=12-character password and
display name. Acceptance never changes an existing password or signs in the
browser implicitly. Issuer's current authority is rechecked at acceptance.
Same successful accept request ID and password can acknowledge again but never
re-add removed membership. Limit 20/IP/min and120/workspace/min in DB before
password hashing. No public signup/password reset/mail delivery. Max100 pending
invitations/workspace; no duplicate pending invitation or active membership.
Suspended members must be restored by management, not through invitations.

## UI And Audit

Four views in the existing team screen: members, roles, invitations, permission
history. Use current workspace styling; do not restore outdated font/icon notes.
Manual invitation links use /invite#token=..., shown once without localStorage.
Acceptance page removes hash before requests, sets no-referrer, submits only
on explicit confirmation. Local mode remains local admin; session-mode fixtures
verify the actual invited-account/login flow without enabling login on local.

Audit is server-only, transactional, includes actor/target/before/after and no
password/token/invitation URL. Sensitive team events are owner/admin-only in
both team history and the legacy Activity API. No new webhook event types.

## Verification And Activation

Tests first: workspace/role isolation, owner/admin/self/local/internal guards,
stale writes and receipts, scoped suspension/session revocation, invite expiry,
revocation/replay/races and existing-account takeover, denied audit access,
malformed/stale/late frontend data and responsive browser fixture. Separate
real local read-only checks from fixture writes. Back up DB, capture runtime
metadata/model/data hashes, migrate and restart only necessary local platform
and shared-DB workers preserving environment. Document limits; no public,
PostgreSQL/load/email/real-camera acceptance claims.
