# VSign Workspace Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent workspace foundation with bootstrap login, sessions, RBAC, audit events, and frontend capability/session fetching without changing camera or inference contracts.

**Architecture:** Keep the existing FastAPI inference service as the local deployment boundary, but isolate the new platform routes under `/api/v1`. SQLAlchemy supports SQLite for local tests and PostgreSQL through `DATABASE_URL`; database-backed cookie sessions protect platform routes when `AUTH_REQUIRED=true`, while existing inference routes remain backward-compatible by default. The React app fetches platform context/capabilities and only shows a login gate when the backend requires authentication.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Argon2 password hashing, HttpOnly database sessions, React, TypeScript, Vitest, pytest.

**Spec:** Approved workspace foundation design in the conversation on 2026-10-13.

## Global Constraints

- Do not change frame count, inference WebSocket payloads, model selection, collection storage, transcript behavior, or training/evaluation data.
- Keep `AUTH_REQUIRED=false` as the local default so the current local workflow remains usable.
- Never store plaintext passwords or session tokens.
- Bootstrap only from explicit environment variables; no public signup endpoint.
- Every platform response keeps `X-Request-ID` and `X-VSign-API-Version`.
- Use additive API changes under `/api/v1`; preserve `/health`, `/metadata`, `/ws/inference`, and `/collection/*` response bodies.

### Task 1: Database and configuration foundation

**Files:**
- Create: `services/inference/app/platform_db.py`
- Create: `services/inference/migrations/env.py`
- Create: `services/inference/migrations/versions/0001_workspace_foundation.py`
- Create: `services/inference/alembic.ini`
- Modify: `services/inference/app/config.py`
- Modify: `services/inference/requirements.txt`
- Modify: `services/inference/pyproject.toml`
- Test: `tests/test_platform_db.py`

- [x] Add SQLAlchemy models for workspaces, users, memberships, sessions, and audit events.
- [x] Add `DATABASE_URL`, `AUTH_REQUIRED`, session TTL, and bootstrap owner settings with validation.
- [x] Add SQLite parent-directory handling and PostgreSQL-compatible engine creation.
- [x] Add the initial Alembic migration with indexes and uniqueness constraints.
- [x] Write tests for schema creation, workspace bootstrap, email normalization, and session token hashing.
- [x] Run the focused database tests and confirm they fail before implementation, then pass after implementation.

### Task 2: Authentication, RBAC, and audit store

**Files:**
- Create: `services/inference/app/platform_auth.py`
- Create: `services/inference/app/platform_router.py`
- Create: `tests/test_platform_auth.py`
- Modify: `services/inference/app/models.py`

- [x] Add Argon2 password hashing and constant-time session-token hashing.
- [x] Add bootstrap owner creation without public signup.
- [x] Add login, logout, and current-user endpoints using an HttpOnly cookie.
- [x] Add role permissions for `owner`, `admin`, `operator`, `reviewer`, and `viewer`.
- [x] Require workspace membership for protected platform routes when `AUTH_REQUIRED=true`.
- [x] Persist login/logout and future platform actions as audit events.
- [x] Replace the empty audit response with paginated database-backed events.
- [x] Test invalid credentials, expiry, logout revocation, workspace isolation, and role permissions.

### Task 3: FastAPI integration and backward compatibility

**Files:**
- Modify: `services/inference/app/main.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `services/inference/Dockerfile`
- Test: `tests/test_inference_api.py`

- [x] Initialize the platform database during app startup only when configured for local auto-create.
- [x] Include the platform router under `/api/v1`.
- [x] Enable credentialed CORS for configured origins without allowing wildcard credentials.
- [x] Keep old inference endpoints usable with default local settings.
- [x] Add a PostgreSQL service and environment wiring to Docker Compose.
- [x] Add bootstrap environment documentation and a migration command.
- [x] Run inference regression tests and a TestClient smoke test for the platform endpoints.

### Task 4: Frontend platform client and authentication gate

**Files:**
- Create: `apps/web/src/lib/workspaceApi.ts`
- Create: `apps/web/src/hooks/useWorkspacePlatform.ts`
- Create: `apps/web/src/components/LoginGate.tsx`
- Create: `apps/web/src/hooks/useWorkspacePlatform.test.ts`
- Create: `apps/web/src/components/LoginGate.test.tsx`
- Modify: `apps/web/src/config.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/components/AppSidebar.tsx`
- Modify: `apps/web/src/components/AppSidebar.test.tsx`
- Modify: `apps/web/src/styles.css`
- Modify: `apps/web/tsconfig.app.json`
- Modify: `apps/web/vite.config.ts`

- [x] Add a platform URL configuration with a fallback to the inference HTTP URL.
- [x] Fetch workspace context, capabilities, and current session with `credentials: include`.
- [x] Keep a local fallback for unauthenticated development mode.
- [x] Show a restrained login gate only after a backend 401 when auth is required.
- [x] Send login/logout requests and refresh platform state after success.
- [x] Use backend capability flags for sidebar enabled state without changing navigation taxonomy.
- [x] Test loading, successful fetch, 401, login success, login failure, and capability disabling.

### Task 5: Documentation and contract parity

**Files:**
- Modify: `contracts/v1/workspace.ts`
- Modify: `contracts/v1/workspace.py`
- Modify: `contracts/README.md`
- Modify: `README.md`

- [x] Add auth/session response types and role/permission types to the shared contract.
- [x] Document local SQLite setup, PostgreSQL Docker setup, bootstrap owner variables, and migration commands.
- [x] Document that inference remains backward-compatible and platform auth is opt-in locally.

### Task 6: Full verification

- [x] Run `.venv/bin/pytest -q`.
- [x] Run `npm test -- --maxWorkers=1` from `apps/web`.
- [x] Run `npm run lint` and `npm run build` from `apps/web`.
- [x] Run `git diff --check`.
- [x] Smoke-test login, logout, `/api/v1/workspace`, `/api/v1/workspace/capabilities`, and audit pagination with an isolated SQLite database.
- [ ] Verify the existing camera/inference workflow remains the default when `AUTH_REQUIRED=false`.

## Checkpoint 2026-10-13

- Full backend suite passed; the final frontend suite passed with 48 files and 386 tests after the logout-state hardening.
- Legacy SQLite adoption was rerun against an unversioned `0001` schema and upgraded to `0003_platform_constraints` successfully.
- Local services are available at Vite `5175` and inference/platform `8000`; the backend reports ONNX `sales30-mvitv2s-seated-v3-epoch5` and `auth_required=false`.
- The remaining unchecked item requires a real camera interaction; automated tests and health checks do not prove webcam quality or recognition accuracy.
