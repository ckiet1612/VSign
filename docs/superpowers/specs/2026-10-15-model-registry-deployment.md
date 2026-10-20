# Phase 3: Local Model Lifecycle

Approved scope: platform 8000 manages the registry; recognition runtime 8002
executes explicit deployment jobs. Runtime 8003 is excluded. No existing
candidate is promoted by this implementation.

## Invariants

- Fine-tuning writes a separate candidate and never changes production.
- Registry mutations require a signed-in workspace member and server RBAC.
- Candidate registration verifies local allowlisted paths, actual artifact
  bytes, ordered labels and the inference contract. Artifacts are immutable.
- A validation report is imported from a trusted server-local evaluation root.
  This does not run an evaluation or turn training-fit results into evidence.
- The gate binds exact candidate, baseline, labels, preprocessing, thresholds,
  protocol, dataset snapshot and source run. Held-out positives and independent
  negatives are mandatory. Missing evidence blocks approval and deployment.
- Owner/admin register, validate, approve and deploy. Reviewer reads, validates
  and approves. Operator may read and register. Viewer reads only.
- Deploy and rollback are explicit confirmed requests with an idempotency UUID
  and expected pointer revision. Only one pending job is allowed per target.
- A single opted-in runtime worker uses the shared database. It loads and
  warms the model while the old model serves; switches only after the current
  inference finishes; and commits the pointer and audit in the same transaction.
- Startup restores the committed active artifact. Failure to restore is fatal
  for a managed runtime. Offline workers cannot accept new deployments.
- Rollback resolves the previous successful model on the server and reloads it.
- Browser endpoint selection remains Dev/Test and is not a deployment.

## Gate Policy v1

Require finite held-out macro F1, false-accept rate, p95 latency and per-label
recall/support for both models. Candidate macro F1 may drop at most 0.02,
false-accept rate must be <=0.05 and <=baseline+0.01, p95 latency <=120% of
baseline and <=2000 ms, per-label recall drop <=0.10. All labels need positive
support; independent negative count must be positive. These configurable-code
local policy bounds are not a claim of real-camera quality or release approval.

## Persistence And Runtime

Migration 0004 adds registered_models, model_validations, deployment_targets and
deployment_jobs without changing prior workspace data. Target key is scoped to
workspace. Registry rows keep absolute artifact/label paths (never exposed in
read responses), SHA256 and immutable manifest JSON. Worker identity and
heartbeat prevent a second active worker taking the same target. Jobs retain
requesting user and are checked again against current membership before switch.

Runtime bootstrap records the already-serving artifact as an observed baseline,
not as a validated candidate or a successful deployment. Initial revision is 0.
Health, metadata and each WebSocket prediction use the actually active backend.

## API

GET /api/v1/workspace/models returns the snapshot in contracts/v1/models.ts.
All POST responses return the refreshed same snapshot:

- /workspace/models: manifest_path, artifact_path, labels_path
- /workspace/models/{id}/validate: report_path
- /workspace/models/{id}/approve: validation_id
- /workspace/models/deployments: request_id, model_id, expected_revision
- /workspace/models/rollback: request_id, expected_revision

Errors use the existing platform error format. Model/report paths must be
server-local, beneath configured roots, without symlinks or traversal. Reports
are limited in size. Read responses contain no local paths or secrets.

## UI

Retain the current SnowUI design. Models page shows observed runtime separately
from the authoritative target pointer, registry table, gate details, approval,
confirmed deployment/rollback, and recent jobs. Anonymous users see runtime
summary plus embedded login. Loading, denied, stale, offline, empty and failure
states are explicit. Account changes invalidate old reads and write callbacks.

## Verification

Use isolated temporary artifacts/database for real HTTP/WebSocket lifecycle
checks. Exercise tenant/RBAC, path/hash tampering, incomplete evaluation,
explicit deployment, rollback, load failure, CAS/idempotency, restart restore,
permission revocation, and candidate-only fine-tune output. Preserve actual
production artifacts and all existing datasets.
