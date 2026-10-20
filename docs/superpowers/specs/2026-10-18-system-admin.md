# VSign System Administration

Approved in chat on 2026-10-18. Scope is the existing configured VSign instance,
not a new cross-workspace or multi-enterprise control plane.

## Authorization

Introduce `system_admin` as a distinct persisted membership role. It combines
the existing administration and model lifecycle permissions. Business roles
remain unchanged. Server guards and deployment-worker permission rechecks stay
authoritative. UI visibility must never grant authority.

Local development opts in with `LOCAL_ADMIN_ROLE=system_admin`; the existing
default remains `admin`. A separate deterministic identity avoids promoting or
rewriting existing users. This mode remains passwordless, loopback-only,
development-only and incompatible with required authentication. Revoked or
altered identities are never repaired automatically. Neither invitations nor
ordinary account editing may grant `system_admin` or `model_admin`.

## Interface And Workflows

System navigation exposes overview, recognition, data and collection, model
evaluation, service monitoring, model registry and deployment, audit activity,
integrations/API, accounts/roles, and configuration. Existing business accounts
retain their customer-facing views. System accounts mount the existing internal
registry instead of the read-only customer model screen. Internal runtime tools
and Dev/Test remain explicitly distinguished from the managed deployment target.

All existing data, evaluation, integration, team and configuration workflows
must accept the new role. System account management lists internal memberships
as protected and documents their permissions; existing business-role invitation,
suspension, revision, session revocation and last-admin rules remain enforced.
System monitoring may expose real endpoint/backend/protocol identity, not fake
telemetry. Administrative headers identify the system scope.

## Safety And Verification

No automatic training, sample changes, model registration, evaluation, approval,
deployment, rollback, retention deletion or secret rotation. Exercise writes in
isolated databases/artifacts only. Before local activation, back up the database,
record metadata/model pointers, migrate with integrity checks, and preserve the
running model and its thresholds. Verify RBAC, enterprise denial, local opt-in,
revocation, migration, frontend routing, API-backed controls, desktop/mobile
layout, and unchanged inference identity. Production acceptance and camera
quality are not implied by these checks. Do not commit or push.
