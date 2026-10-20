# Model Registry And Deployment (Local Phase 3)

Platform: `http://localhost:8000`. Managed recognition target:
`production-local`, `http://127.0.0.1:8002`. Runtime 8003 is not managed.
The frontend models page is `http://127.0.0.1:5174/?view=models`.

## Lifecycle

Fine-tune -> candidate manifest -> explicit registration -> imported validation
report -> separate approval -> explicit deployment job -> actual runtime reload.
Fine-tuning never calls deployment APIs, registers a model automatically, writes
an active pointer, or overwrites any registered artifact directory.

The runtime first verifies and records its already-serving artifact as an
observed baseline. That record is not evidence of passing the candidate gate.
No existing fine-tuned candidate is automatically promoted.

The customer workspace page is read-only: active version, supported sign count,
service confirmation and update history. It uses the authoritative registry
target, not the selected Dev/Test endpoint. Candidate registration, artifact
paths, gate details and deployment controls are not mounted in this page.
`InternalModelRegistry` remains an unmounted component, not an internal console.
The standalone local Dev/Test tooling is separate and is not secured by this
workspace UI change; keep development services bound to loopback.

## Authentication And Permissions

Local development defaults to admin without a login form when
`APP_ENV=development` and `AUTH_REQUIRED=false`. The backend creates one
workspace-scoped `Admin local` identity with role `admin`, no usable password,
no session cookie and no fake login event. Registry and audit permissions use
this persisted identity, including the worker's final permission check.
The UI shows the admin identity as a business administrator without a logout
button. Local admin has no model mutation permissions.

`LOCAL_ADMIN_ENABLED=false` restores the session-based flow for later account
development. `APP_ENV=production` or `AUTH_REQUIRED=true` disables local admin
by default; forcing the flag on in either case fails startup. This is a trusted
local development mode, not a public deployment authentication mechanism.
Keep the local services bound to loopback, not a public address or proxy.

In session mode, registry reads and every mutation require a signed-in workspace
member. No default password is created. Bootstrap an owner explicitly through the existing
`BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` configuration (minimum
12-character password), then restart platform 8000 with
`LOCAL_ADMIN_ENABLED=false`. Keep secrets out of logs.

| Role | Read | Register | Validate | Approve | Deploy/Rollback |
| --- | --- | --- | --- | --- | --- |
| owner/admin | yes | no | no | no | no |
| operator | yes | no | no | no | no |
| reviewer | yes | no | no | no | no |
| viewer | yes | no | no | no | no |
| model_admin (internal only) | yes | yes | yes | yes | yes |

`model_admin` is an explicit workspace-scoped internal membership, provisioned
out of band by trusted maintenance. It is never assigned by local admin,
owner bootstrap or public/self-service routes, and is excluded from customer
member lists. There is no internal account-management UI in this change.
Mutation routes reject all five business roles before parsing request bodies.

Approval is an explicit separate action; this personal-scale policy does not
require approver and requester to be different people. Permissions are enforced
again by the worker immediately before switching. Capability flags are not RBAC.

## Configuration

Both processes use the same absolute `DATABASE_URL` and `WORKSPACE_ID`. Back up
the database before migration. Revision `0004_model_registry` adds four tables.
Current revision `0005_internal_model_role` extends the membership constraint
without promoting existing accounts or changing workspace, sessions, models
or audit rows. Downgrade refuses while internal memberships still exist.

Only the recognition process enables `MODEL_DEPLOYMENT_WORKER=true`.
`MODEL_DEPLOYMENT_TARGET=production-local` and
`MODEL_DEPLOYMENT_RUNTIME_URL=http://127.0.0.1:8002` identify the target.
Never enable this same target in platform 8000 or experimental runtime 8003.

After backing up and migrating the shared DB, start recognition with
`bash scripts/run_managed_coreml_local.sh`. This wrapper pins port 8002, disables
automatic schema creation by default, and opts into pointer restoration. Do not
restart managed production with the unmanaged launcher; it does not own or
restore the registry pointer. Existing `DEV_TEST_ENABLED`, `ALLOWED_ORIGINS`,
Core ML artifact/benchmark choices and collection configuration can be passed
explicitly. The wrapper does not enable Dev/Test or collection automatically.

`MODEL_REGISTRY_ROOTS` is a comma-separated allowlist (default `ml/artifacts`).
`MODEL_EVALUATION_ROOTS` is a separate comma-separated trusted evaluator report
allowlist (default `ml/evaluations`). Internal API path fields refer to files on
the server, not browser uploads. Reject symlinks, traversal, wrong hashes and wrong
inference contracts. Registry read responses never expose server-local paths.

Keep allowlisted files writable only by trusted local operators. These are
immutable artifacts by application contract, not a hostile-filesystem sandbox.
Do not edit or remove an artifact used by the registry, including prior models
needed for rollback. File/package and ordered-label hashes are verified again
when validating, approving, loading and activating a model.

Training reads all workspaces' registered directories from the file SQLite DB
without mutating it. For a non-file DB, set absolute, colon-separated
`MODEL_PROTECTED_ARTIFACT_ROOTS` explicitly before training. Missing legacy
registry tables do not bootstrap a schema; malformed/unreadable registries fail
closed. A shared POSIX file lock is held for the entire training write window;
registration and first baseline registration require the exclusive lock before
hash verification through commit. Registration is temporarily blocked while
any training run uses the same DB identity; existing immutable models may still
deploy. All processes must use the same local user and shared temp storage.
This lock is not distributed coordination across hosts/containers.

## Candidate Manifest

Successful personal fine-tunes publish `model_manifest.json` next to `best.pt`
and `labels.json`, with `status=candidate` and `development_only=true`.
Candidate checkpoints may be registered as PyTorch. To deploy to the Core ML
target, export to a separate `.mlpackage` and create a matching candidate
manifest and evaluation report for those actual exported bytes. A PyTorch
evaluation cannot approve a different Core ML artifact.

Required manifest fields:

```json
{
  "model_version": "candidate-example-v1",
  "artifact_sha256": "<actual file SHA256 or canonical .mlpackage hash>",
  "labels_sha256": "<SHA256 of ordered compact UTF-8 label array>",
  "backend": "coreml",
  "protocol_version": "1.0",
  "frame_count": 16,
  "frame_size": 224,
  "preprocessing_version": "rgb16-224-imagenet-v1",
  "confidence_threshold": 0.7,
  "margin_threshold": 0.15,
  "source_run_id": "training-run-id",
  "status": "candidate"
}
```

Optional fields: `labels_file_sha256`, `development_only`. All extra fields are
rejected. Core ML package hashing uses
`app.backends.coreml_artifact.package_hash`, not a concatenation of file bytes.

## Trusted Evaluation Report

Phase 3 imports an existing evaluator report; it does not execute evaluation
runs. A training summary's `deployment_gate_passed` is not this gate. The report
must bind candidate and current baseline artifact identities, ordered labels,
both models' thresholds, protocol, preprocessing, source run and dataset snapshot.
Held-out positives and independent negatives are mandatory.

```json
{
  "schema_version": "1",
  "candidate_artifact_sha256": "<candidate hash>",
  "baseline_artifact_sha256": "<active baseline hash>",
  "labels_sha256": "<same ordered labels for both models>",
  "source_run_id": "training-run-id",
  "preprocessing_version": "rgb16-224-imagenet-v1",
  "protocol_version": "1.0",
  "confidence_threshold": 0.7,
  "margin_threshold": 0.15,
  "baseline_confidence_threshold": 0.7,
  "baseline_margin_threshold": 0.15,
  "dataset_snapshot_sha256": "<actual evaluation snapshot hash>",
  "held_out": true,
  "independent_negatives": true,
  "positive_count": 100,
  "negative_count": 100,
  "baseline": {
    "macro_f1": 0.95,
    "false_accept_rate": 0.01,
    "latency_p95_ms": 500.0,
    "per_class": [{"label": "<each actual label>", "support": 10, "recall": 0.95}]
  },
  "candidate": {
    "macro_f1": 0.96,
    "false_accept_rate": 0.01,
    "latency_p95_ms": 490.0,
    "per_class": [{"label": "<each actual label>", "support": 10, "recall": 0.96}]
  }
}
```

Numbers above demonstrate schema only and are not measured model results. Use
all actual labels, nonempty supports and a trusted report generated on the same
runtime/compute configuration. The server does not independently recreate the
dataset or prove the truth of locally supplied reports. Trusted report writers
and local operator approval remain part of the acceptance boundary.

Policy `local-heldout-v1`: macro F1 drop <=0.02; false accepts <=0.05 and
<=baseline+0.01; p95 <=120% baseline and <=2000 ms; per-class recall drop <=0.10.
Missing/nonfinite fields fail. These bounds are a local gate policy, not a claim
of webcam quality, unseen-signer performance or release acceptance. New reports
invalidate old approval. A changed baseline requires another validation.

## Deployment And Recovery

POST requests carry a UUID and expected revision. Retries with the same UUID
and content are idempotent. Conflicting content, stale revision or a pending job
returns 409. Offline/unconfirmed workers return 503. The initial revision is 0.

The worker verifies and warms a new backend while the old model continues to
serve. It waits for active inference, rechecks artifacts, gate, permission and
worker ownership, then commits the pointer, successful job and audit before
switching the in-memory backend without yielding the event loop. Each prediction
uses one backend snapshot. Failed loading/verification/commit retains the old
model and pointer. Warm-up is a compatibility check, not accuracy evaluation.
Managed startup reloads from verified registered bytes rather than reusing the
backend created before registration. If the commit outcome is uncertain after
activation, health, metadata and inference fail closed; heartbeat cannot mark
the stale backend ready. Restart the managed worker to restore and verify the
durable active pointer before serving again.

Rollback resolves `previous_model_id` server-side and performs the same reload
and identity checks. Restart restores the committed active model; corrupt or
missing artifacts fail startup rather than claiming the launcher baseline is
active. Managed Core ML startup never falls back to PyTorch. A crashed loading
job is failed on takeover; a queued request is rechecked before execution.

Model registration/validation/approval and deploy/rollback requested/succeeded/
failed audit events are generated by the server. Browser `model.switched` events
remain endpoint-selection reports. Evaluation-run and integration event sources
are still not connected.

## Verification Limits

Current enterprise-admin UI, permissions and runtime verification are recorded
in `docs/reports/2026-10-15-enterprise-admin-workspace.md`. The registry GET
contract is unchanged and still includes technical fields; the customer UI
projects business fields only. This is not a claim of API field minimization.

Unit/integration and browser checks use isolated temporary DBs/artifacts and
tiny synthetic ONNX models. They prove the lifecycle mechanism and API/UI flow,
not recognition quality. No training or real candidate deployment is performed
by the implementation verification. The original local production artifact and
experimental runtime are preserved.
