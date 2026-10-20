# Workspace Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the five approved Settings groups to persistent workspace APIs.

**Architecture:** Follow the existing platform router, SQLAlchemy and Alembic
patterns. Separate configuration from personal preferences, use workspace-locked
writes and revision/request receipts, and keep retention read-only.

**Tech Stack:** FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, React, TypeScript,
Vitest, pytest and the repository browser verification workflow.

**Spec:** `docs/superpowers/specs/2026-10-16-workspace-settings.md`

## Global Constraints

- No commit, push, model promotion, training, real collection or deletion.
- Automatic deletion is always false.
- Preserve all snapshots, model artifacts, evaluation evidence and legacy data.
- Never change an active session, server model, thresholds or queue parameters.
- Store choices; notification delivery remains explicitly unavailable.

### Task 1: Versioned Settings API

**Files:** create `contracts/v1/settings.py`, `contracts/v1/settings.ts`,
`services/inference/app/workspace_settings{,_db,_router}.py`, migration
`0010_workspace_settings.py`, `tests/test_workspace_settings.py`; modify
`migrate.py`, `platform_router.py`, `platform_auth.py`, `main.py`, `teamLabels.ts`.

**Interfaces:** `WorkspaceSettings(database, settings, session_token=None)`;
`overview(actor)`, `update(actor, payload)`, `notifications(actor, payload)`,
`preview(actor)`, `effective(actor)`; factory
`create_workspace_settings_router(settings, get_database, require_permission, validate_origin)`.

- [x] Write API tests, including `assert client.get(BASE).status_code == 200`,
  role isolation, revision 409, request-ID reuse, persistence and preview counts.
- [x] Run `PYTHONPATH=services/inference:. .venv/bin/pytest tests/test_workspace_settings.py -q`;
  confirm new routes fail with 404 before implementation.
- [x] Implement contracts, schema and locked service, then include router and
  enable role-based settings capability. Add settings request body size limit.
- [x] Run settings/auth/schema/team tests and inspect before/after audit rows.

### Task 2: Effective Collection Policy

**Files:** modify `contracts/v1/data.py`, `workspace_data.py`,
`workspace_data_db.py`, `apps/web/src/components/WorkspaceData.tsx`,
`apps/web/src/App.tsx`; test `tests/test_workspace_settings.py`.

**Interfaces:** `collection_policy(session, settings)` returns effective enabled,
require_consent, default quota and revision. Start request adds `consent: bool`;
session stores consent timestamp and policy revision. Existing collection
responses stay compatible; data overview may add optional policy information.

- [x] Write failing tests for disabled collection, required consent at start,
  resume/save and omitted quota inheriting the workspace default.
- [x] Verify failure, implement checks inside the existing writer lock and
  persist consent; add conditional checkbox to collection UI.
- [x] Run data/collection/enterprise regressions, including explicit quota
  preservation, sealed versions and consent after policy changes.

### Task 3: Settings UI And Session Defaults

**Files:** create `useWorkspaceSettings.ts`, `WorkspaceSettings.tsx`,
`workspace-settings.css`, `workspaceSettings.ts` parser and adjacent tests;
modify `App.tsx`, extend `App.data.test.tsx`, and add session-default hook tests.

**Interfaces:** hook returns validated snapshot, busy/error/stale/access,
`refresh()`, `mutate(path, body)`, `retry()` and preview; component receives
platformUrl/workspaceId/user and onWorkspaceChanged; runtime default is loaded
once per workspace/user session and ignored after camera use/manual override.

- [x] Add failing parser, hook and component tests for all five tabs, denied
  state, independent preference revision, malformed responses and uncertain retry.
- [x] Run targeted Vitest tests and confirm missing module/behavior failure.
- [x] Implement semantic tabs/forms, numeric limits, disabled unavailable
  delivery, refresh/conflict handling and scoped mutation cancellation.
- [x] Verify defaults do not change active sessions or transcript insertion.
- [x] Run frontend tests, `npm run lint`, `npm run build`.

### Task 4: Browser, Activation And Handoff

**Files:** add `tests/e2e/workspace_settings.mjs`,
`docs/WORKSPACE_SETTINGS_LOCAL.md`, report in `docs/reports/`.

- [x] Run isolated fixture browser workflow at desktop and 390/320px: save each
  group, reload, conflict, personal-only access, consent and preview.
- [x] Inspect screenshots, horizontal overflow, nonblank pixels, page errors;
  assert inference metadata unchanged and fixtures cleaned up.
- [x] Capture live listeners/environment safely without printing secrets;
  back up shared DB and fingerprint model/data; migrate/restart affected local
  services preserving environment and check health/CORS/capabilities/settings.
- [ ] Run focused backend regressions and complete frontend verification;
  document commands/results, screenshot paths and unverified environments.
