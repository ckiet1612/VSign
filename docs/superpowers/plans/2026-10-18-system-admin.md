# System Admin Implementation Plan

> Execute inline in the existing dirty checkout; preserve unrelated work. No
> delegation, commits, model mutations or real sample writes.

**Goal:** Restore existing administration workflows for a distinct system role.

**Architecture:** Keep configured-workspace API boundaries. Extend persisted
authorization, then route system users to existing internal components. Opt-in
local startup creates a separate identity; business roles remain unchanged.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, Pydantic, React, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-18-system-admin.md`

## Constraints

- No cross-workspace authority, automatic account promotion or internal-role grants.
- Keep lifecycle gates, worker authorization, revision checks and confirmation.
- No model/data writes outside isolated test fixtures; no Git operations.
- Keep current full-width responsive layout and existing components.

## Task 1: Persisted System Authorization

- [x] Add failing tests in `tests/test_system_admin.py` for permissions, explicit
  local role, distinct identity, revocation, migration, and read APIs.
- [x] Run `PYTHONPATH=services/inference:.:tests .venv/bin/python -m pytest
  -o addopts='' -q tests/test_system_admin.py`; confirm missing-role failures.
- [x] Extend workspace Python/TS contracts, membership constraint and migration
  `0011_system_admin`; update `CURRENT_SCHEMA_REVISION`.
- [x] Add `Settings.local_admin_role` default `admin`, validated against
  `admin/system_admin`; make local identity/bootstrap/resolution role-aware.
- [x] Define system permissions as union of existing admin and model-admin sets.
  Include system role in full audit access and existing team/settings rechecks.
- [x] Test customer denials, revocation and all administration APIs on fixtures.

## Task 2: System Interface And Existing Workflows

- [x] Add failing frontend tests for system navigation, internal registry routing,
  role parsing and team/evaluation/integration access.
- [x] Extend shared role labels and account parser. Route only `system_admin`
  and `model_admin` to the internal registry; keep enterprise models read-only.
- [x] Add system-specific navigation/breadcrumb labels and page headings using
  existing components. Pass system scope to overview/monitoring for real runtime
  identity, keeping missing telemetry unavailable.
- [x] Update frontend access checks for existing data/evaluation/integration/team/
  settings workflows. System team lists protected internal roles without grants.
- [x] Run focused tests, full serial frontend suite, lint and TypeScript checks.

## Task 3: Local Activation And Evidence

- [x] Add explicit loopback system-admin launcher and document startup/opt-out.
- [x] Back up current DB, record runtime identity/pointers, migrate, verify
  integrity, and restart only the current backend with the same inference setup.
- [x] Read-only browser checks on port 5174 across all ten tabs, desktop/mobile,
  and verify model mutation controls and real API access without submitting writes.
- [x] Record fresh test evidence, unchanged model identity and remaining limits
  in `docs/reports/2026-10-18-system-admin.md`.
