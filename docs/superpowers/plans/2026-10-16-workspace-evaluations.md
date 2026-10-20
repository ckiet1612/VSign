# Workspace Evaluations Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task by task. User approved inline implementation; no commits or unrelated edits.

**Goal:** Connect enterprise evaluation workflows to durable real inference and fail-closed deployment gates.
**Architecture:** Scoped SQLAlchemy queue, separate subprocess worker and frozen evidence. Server-computed reports feed registry validations; React consumes a strictly checked API.
**Tech Stack:** Existing FastAPI, SQLAlchemy/Alembic, PyAV, NumPy, React/Vitest/Playwright.
**Spec:** `docs/superpowers/specs/2026-10-16-workspace-evaluations.md`.

## Global Constraints

Passwordless local enterprise admin remains. No production pointer/model/sample changes. No enterprise training, approval or deployment. No invented metrics. Missing trusted provenance fails gate. Preserve dirty checkout.

### Task 1: Scoped Queue And API

Files: `contracts/v1/evaluations.py`, `app/evaluation_db.py`, migration 0007,
`app/evaluations.py`, `app/evaluation_router.py`, auth/main/router integration.
Interface: `Evaluations.create(actor,payload)`, `cancel(actor,id)`, `overview(actor)`.

- [x] Write API/role/idempotency/snapshot tests in `tests/test_workspace_evaluations.py`; run them and confirm missing-route failures.
- [x] Add migration, contracts and transactional queue; freeze registry manifests and snapshot identities, reject incompatible labels/backend and foreign IDs.
- [x] Run focused API tests and schema regression.

### Task 2: Computation And Worker

Files: `app/evaluation_engine.py`, `app/evaluation_worker.py`, `app/evaluation_evidence.py`.
Interface: `execute_run(database,settings,run_id,worker_id,factory)`; worker CLI `python -m app.evaluation_worker --backend onnx`.

- [x] Write exact metrics, tamper, provenance, cancellation and lease tests; verify red.
- [x] Implement bounded video sampling, isolated model loading, warmup and predict-only timing, progress and fenced completion.
- [x] Implement worker heartbeat/claim, expired-run recovery, subprocess cancellation/timeout; test lifecycle without touching production.

### Task 3: Deployment Gate

Files: `app/model_gate.py`, `app/model_registry.py`, registry test fixtures.
Interface: `require_evaluation_evidence(registry,session,validation)` invoked on approval and the shared deploy gate.

- [x] Add tests that imported numeric reports cannot approve/deploy and that stale/tampered computed evidence is rejected.
- [x] Generate versioned validations only from completed runs, recheck evidence at approval/deploy and worker activation.
- [x] Adapt deployment mechanics fixtures to explicitly seed trusted computed evidence; run registry/recovery regressions.

### Task 4: Enterprise UI

Files: `contracts/v1/evaluations.ts`, `useWorkspaceEvaluations.ts`, `WorkspaceEvaluations.tsx`, scoped CSS, `App.tsx`.

- [x] Add frontend contract/race/readonly/comparison tests and confirm failures.
- [x] Implement validated polling, request timeout, scope invalidation and same-ID retry; compact accessible selectors, run details and metric/gate tables.
- [x] Run frontend tests, lint/build and isolated responsive browser checks.

### Task 5: Local Operation And Evidence

Files: `docs/WORKSPACE_EVALUATIONS_LOCAL.md`, `docs/reports/2026-10-16-workspace-evaluations.md`, disposable browser fixture/script.

- [x] Test native inference on a disposable immutable video snapshot; record integration limits separately from model quality.
- [x] Back up local DB, migrate/restart only required managed services preserving existing environment, launch available workers.
- [x] Verify live empty states/permissions, runtime metadata/pointer/legacy hashes, full focused regression and diff checks.
- [x] Report endpoints, auth mode, visible changes, exact verification and remaining limitations.
