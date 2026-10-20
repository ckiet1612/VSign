# Workspace Data Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the approved existing workspace. Steps use checkbox syntax for tracking.

**Goal:** Connect enterprise Data to durable scoped collection and immutable datasets.

**Architecture:** Platform-owned data API reuses authentication and media encoding.
DB transactions serialize quota/session/snapshot changes across processes. Scoped
files and canonical hash manifests preserve committed bytes and legacy data.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PyAV, React, TypeScript, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-15-workspace-data.md`

## Global Constraints

- Work in the existing dirty checkout; preserve unrelated changes; no commit/push.
- No model mutation, training, legacy data import, new authentication or new dependencies.
- Default quota 100 per label across hands; authoritative DB workspace and counts.
- Capture frames, timing, tracking and transcript behavior stay unchanged.

### Task 1: Durable Data API And Media

Files: `contracts/v1/data.py`, `services/inference/app/workspace_data_db.py`,
`workspace_data.py`, `workspace_data_router.py`, migration `0006_workspace_data.py`,
existing `platform_router.py`, `platform_auth.py`, `main.py`, `migrate.py`.

Interfaces: `WorkspaceData(database, settings)` exposes `overview(actor)`,
`labels(actor, payload)`, `dataset(actor, payload)`, `quota(actor, id, payload)`,
`start(actor, payload)`, `transition(actor, id, payload)`, `save(actor, id, payload)`
and `seal(actor, id, payload)`. Mutations return a fresh scoped overview; save returns
the existing collection ACK shape. Snapshot manifest reads verify SHA256 first.

- [x] Write API tests in `tests/test_workspace_data.py` using temporary SQLite and media.
  Assert e.g. `assert client.get('/api/v1/workspace/data').status_code == 200`.
- [x] Run `PYTHONPATH=services/inference:. .venv/bin/python -m pytest -o addopts='' -q tests/test_workspace_data.py` and observe missing routes.
- [x] Add typed requests, versioned tables, lock transactions and scoped file paths.
- [x] Implement permission-guarded routes, durable audit and atomic media/snapshots.
- [x] Run the tests including role/tenant, race, crash residue and tampering cases.

### Task 2: Enterprise Data UI And Capture Connection

Files: `contracts/v1/data.ts`, `apps/web/src/hooks/useWorkspaceData.ts`,
`components/WorkspaceData.tsx`, `styles/workspace-data.css`, `App.tsx`, collection panel.

Interfaces: hook supplies validated overview, refresh, typed mutation and session
state. WorkspaceData renders four tabs and dataset/label configuration. App routes
workspace captures to platform API while retaining trusted legacy standalone flow.

- [x] Add failing UI/hook tests for no technical controls, empty/loading/error,
  scope changes and sealed-state permissions.
- [x] Run focused Vitest tests and observe missing data UI.
- [x] Implement four views, mutation recovery, and acknowledged session transitions.
- [x] Connect existing camera capture to selected draft and persisted session;
  pending save completes before session close, no stale-scope ACK is accepted.
- [x] Run full frontend suite, lint and production build.

### Task 3: Local Delivery And Evidence

Files: `tests/e2e/workspace_data.mjs`, `docs/WORKSPACE_DATA_LOCAL.md`, scoped report.

- [x] Run isolated browser/API workflow: labels -> draft -> session -> sample ->
  close -> snapshot; verify bytes, quota, responsive geometry and no model writes.
- [x] Back up actual DB and snapshot runtime identity; migrate explicitly.
- [x] Restart only services requiring updated schema/code with preserved settings.
- [x] Read actual API/UI without creating datasets/samples or touching legacy media.
- [x] Record tests, endpoint/auth modes, current limitations and unchanged models.

Evidence: `docs/reports/2026-10-16-workspace-data.md`. The approved plan/spec
date remains October 15; final verification and migration occurred October 16.
