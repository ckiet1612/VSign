# Workspace Team Implementation Plan

> Use executing-plans inline, test-driven. No worktree/commit/push. Use the
> requesting-code-review read-only checkpoint before local activation.

**Goal:** deliver approved Phase7 without changing local auth mode or models/data.
**Architecture:** membership-local lifecycle + scoped transactional management,
one-time invitation acceptance independent of local-admin fallback; four team
views and a separate invitation page.
**Tech Stack:** existing FastAPI/Pydantic, SQLAlchemy/Alembic, Argon2, React/Vitest.
**Spec:** `docs/superpowers/specs/2026-10-16-workspace-team.md`.

## Global Constraints

Keep existing dirty checkout and current UI conventions. Isolated writes only
until backup/migration; do not create real accounts/invites or send mail.

### Task 1: Team Persistence, Roles And Membership Management
- [x] Add failing API tests in `tests/test_workspace_team.py`; run
  `PYTHONPATH=services/inference:. .venv/bin/python -m pytest -o addopts='' -q tests/test_workspace_team.py`.
- [x] Create `contracts/v1/team.py`, `app/team_db.py`, migration0009,
  `app/team.py` and `app/team_router.py`. Add membership status/revision,
  session/login checks, metadata registration and legacy schema compatibility.
- [x] Expose `WorkspaceTeam(database,settings,hasher,session_token)` with
  `overview(actor,search,cursor)`, `roles(actor)`, `update(actor,id,payload)`;
  router `create_team_router(settings,get_database,require_permission,validate_origin,hasher)`.
- [x] Verify read/write roles, tenant isolation, stale revisions, receipts,
  protected identities, workspace-only suspend/remove and session revocation.

### Task 2: Invitations And Permission History
- [x] Red tests for once-only acceptance, existing-user password protection,
  expiry/revocation, issuer authority, concurrent accept/revoke, persisted rate
  limits, pagination and sensitive-event filtering in Activity.
- [x] Add `create_invitation`, `revoke_invitation`, `inspect`, `accept`,
  `invitations`, `history` to team service and bounded routes; durable counters,
  receipts and transaction audit. Token never stored/echoed except first create.
- [x] Green backend tests; migrate empty schema roundtrip and legacy adoption.

### Task 3: Enterprise UI And Acceptance Page
- [x] Red tests for scoped team reads/mutations, invalid data, stale/timeout,
  late replies, one-time link clearing and explicit invitation acceptance.
- [x] Add TS contracts, `useWorkspaceTeam`, `WorkspaceTeam`, team forms,
  invitation acceptance page, scoped CSS, App team route and main invite route.
- [x] Reuse workspace HTTP helper, icons and styles. Add human-readable audit
  labels without exposing secrets or enabling internal model controls.
- [x] Focused tests, full frontend sequential suite, lint/build and isolated
  browser member/invite/login flow at desktop/mobile.

### Task 4: Review, Local Activation And Evidence
- [x] Run platform/data/model/evaluation/integration/inference regressions;
  read-only focused code review and resolve findings with regressions.
- [x] Back up DB and capture runtime/model/data snapshot. Migrate0009 and
  restart only required shared-DB processes with their existing environment;
  confirm all workers and preserved metadata/hash/pointer/auth.
- [x] Live read-only browser checks; document real state, limits, evidence and
  recovery in `docs/WORKSPACE_TEAM_LOCAL.md` and dated report.
