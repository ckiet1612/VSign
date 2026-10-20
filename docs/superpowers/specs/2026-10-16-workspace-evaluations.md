# Workspace Evaluations

Approved 2026-10-16. Enterprise owner/admin request and cancel evaluations;
reviewers read. No enterprise register, approve, deploy or threshold controls.

## Contract

`GET /api/v1/workspace/evaluations` returns scoped model and sealed snapshot
choices, worker availability, permissions and the latest 50 runs. `POST` accepts
only `request_id`, `model_id`, `snapshot_id`. Baseline is the active pointer at
creation. `POST /{id}/cancel` is idempotent. IDs never select another tenant.
Repeated creation with the same ID, actor and payload returns the same run.
Only one queued/running run per workspace; at most 1000 clips per run.

Runs freeze both registry manifests, artifact identities, dataset/snapshot/label
versions and snapshot hash. States: queued, running, completed, failed,
cancelled. A separate worker process loads models, never the production backend.
It evaluates each model on the same immutable videos using 16 uniformly sampled
224px RGB JPEG frames. Predict-only latency excludes video decoding and model
loading, is not camera latency, and is measured on one worker with warmup.
Accuracy, macro-F1, per-class support/recall/errors, negative false accepts and
P95 derive from predictions. Uncertain predictions are rejections, not correct
positive classifications. Missing support or negatives leaves metrics absent.

## Trust And Deployment

Policy `workspace-heldout-v2` retains the existing numeric limits. A trusted,
out-of-band provenance document is required for deployment eligibility. Its
filename is `provenance-<snapshot SHA256>.json` inside MODEL_EVALUATION_ROOTS.
It binds workspace, snapshot and both artifact hashes/source runs, declares
complete training lineage, lists training video hashes/group IDs, and maps all
evaluation video hashes to group IDs. Both video hashes and signer/session group
IDs must be disjoint from training for both models. Files are operator-owned;
enterprise APIs never accept attestations or arbitrary report/path input.
Missing provenance is normal: evaluation remains informational, gate fails.
This is trusted operator evidence, not independently proven model quality.

Worker-generated validations bind the completed run and its report digest.
Approve, deploy API and deploy worker recheck frozen identity, report digest,
snapshot files, provenance digest and current baseline. Imported reports remain
diagnostic and cannot approve/deploy. Passing never auto-approves or deploys.

## Durability And Limits

SQLite write transactions/PostgreSQL workspace row locks serialize requests.
Worker heartbeats expire after 45 seconds; expired running jobs fail, not replay.
Per-run subprocess permits cancellation and a 30-minute hard timeout. Results
are fenced by run state and worker token; cancelled jobs never publish results.
Queued jobs survive restart. Clip size, dimensions and decoded frames are bounded.
No production pointer, legacy sample or capture/transcript changes.

## UI And Verification

Keep existing light workspace tokens. Compact run list, model/snapshot selectors,
comparison table, per-label results and gate reasons; no fabricated charts or
technical mutation controls. Scope/role changes erase prior results. Bounded
reads, polling and explicit same-ID retry handle uncertain acknowledgements.
Test auth-before-body, tenant isolation, metrics, queue/cancel/fencing, checksums,
provenance, legacy bypass denial, stale baseline and frontend races. Disposable
real-video/native-runtime testing proves integration only. Actual empty workspace
must stay empty; preserve runtime identities, active pointer and legacy hashes.
