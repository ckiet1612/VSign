# Workspace Integrations Implementation Plan

> Use executing-plans inline; no worktree/commit. Use the required read-only
> code-reviewer skill checkpoint before local activation, without delegating edits.

**Goal:** deliver approved Phase6 without changing production models or data.
**Architecture:** SQLAlchemy scoped management + read-only machine router;
transactional audit fanout and a separate bounded webhook process.
**Tech Stack:** FastAPI/Pydantic, SQLAlchemy/Alembic, cryptography Fernet,
stdlib pinned HTTPS, React and the current SnowUI/Inter/Mage styles inspected in
the checkout (newer than the earlier Nunito/Lucide design notes).
**Spec:** `docs/superpowers/specs/2026-10-16-workspace-integrations.md`.

## Global Constraints
Local admin unchanged. API keys read-only. No automatic outbound traffic on UI
load. No raw data/secret leaks. Preserve all unrelated dirty work. Tests isolated.

### Task1: Persistence, Management And Machine Reads
- [x] Add tests in `tests/test_workspace_integrations.py`; run red with
  `PYTHONPATH=services/inference:. .venv/bin/python -m pytest -o addopts='' -q tests/test_workspace_integrations.py`.
- [x] Add `contracts/v1/integrations.py`, `app/integration_db.py`, migration0008,
  `app/integrations.py`, `app/integration_router.py`; register metadata and
  routers; activate capability owner/admin. Add encryption dependency/config.
- [x] Verify endpoints: `POST /workspace/integrations/keys`, POST
  `/keys/{id}/revoke`, `/webhooks`, `/webhooks/{id}/configure|rotate|test`,
  `/deliveries/{id}/retry`, GET overview/logs and3 machine read endpoints.
- [x] Green: tenant/roles, key scopes/expiry/revoke, fail-closed config,
  idempotency and429 shared counters; update schema revision assertion.

### Task2: Transactional Events And Bounded Delivery
- [x] Add red tests for transaction rollback, browser-event rejection, unique
  fanout, SSRF, claim fencing, retries/timeout and signing.
- [x] Add `app/integration_events.py`, `app/webhook_transport.py`,
  `app/integration_worker.py`, launcher. Session hook signature
  `capture_events(session, flush_context, instances)`; worker
  `claim_delivery(database, settings)` returns `(id, claim_token)` orNone;
  `finish_delivery(database,settings,id,token,result)` fences stale results.
- [x] Green including two workers, expired claims and disable/rotation.

### Task3: Enterprise UI
- [x] Red hook/component tests for secrets, scope changes, invalid responses,
  stale/error controls and explicit test delivery.
- [x] Add TS contract, `useWorkspaceIntegrations`, `WorkspaceIntegrations`,
  scoped CSS, App route and readable activity event names. Reuse workspace API.
- [x] Run frontend focused tests, lint and production build.

### Task4: Regression And Local Handoff
- [x] Backend regression across platform/data/evaluations/models/inference:
  257 passed on resumed verification.
- [x] Full frontend tests and isolated browser workflow at desktop/mobile.
- [x] Backup DB, capture runtime identities/data hashes, migrate and restart
  only needed local listeners with preserved environment; provision operator
  encryption key outside DB/repo, start webhook worker, read-only live check.
- [x] Record evidence, limitations, runtime before/after and runbook in
  `docs/reports/2026-10-16-workspace-integrations.md` and
  `docs/WORKSPACE_INTEGRATIONS_LOCAL.md`; focused read-only follow-up review
  found no remaining actionable bugs in the two prior UI fixes.
