# VSign Model Lifecycle

This document defines the boundary between model training and the production
recognition product.

The local managed registry, validation policy, permissions, deployment worker,
and recovery configuration are documented in
[WORKSPACE_MODELS_LOCAL.md](WORKSPACE_MODELS_LOCAL.md). The managed target is
runtime 8002; experimental runtime 8003 remains independent.

## Production Boundary

- Training and fine-tuning write to a versioned candidate artifact directory.
- The active production artifact is never overwritten by a training command.
- A production inference process may opt into a manifest with
  `MODEL_MANIFEST_PATH`.
- When a manifest is configured, startup fails if the runtime and manifest do
  not agree on model version, backend, labels, protocol, frame shape, or
  thresholds.
- `APP_ENV=production` accepts only a manifest with `status: "production"`.
- `status: "candidate"` is valid only for an isolated development or smoke
  process on a separate port.

## Manifest Identity

Every promoted artifact must record:

- `model_version`
- `artifact_sha256`
- `labels_sha256`
- `backend`
- `protocol_version`
- `frame_count` and `frame_size`
- `preprocessing_version`
- `confidence_threshold` and `margin_threshold`
- `source_run_id`
- `status`

The label digest preserves label order. A model cannot silently change output
meaning while keeping the same frontend contract.

## Promotion Sequence

1. Train into a new candidate directory.
2. Preserve the existing collection, validation, and test artifacts.
3. Generate the candidate manifest and record dataset provenance.
4. Start the candidate on a spare inference port with `APP_ENV=development`.
5. Verify `/health`, `/metadata`, protocol compatibility, label digest, and
   the fixed 16-frame 224x224 input contract.
6. Run the regression and positive/negative runtime gates against the same
   fixtures.
7. Explicitly register the candidate and import its trusted evaluation report
   against the current active baseline. Approve that exact validation separately.
8. Request deployment with the current target revision; verify the completed job,
   active pointer, observed model and actual prediction identity.
9. Keep immutable previous artifacts available for server-resolved rollback.

For managed runtime 8002, use the registry API/UI and managed launcher, not a
manual model-path change. A successful fine-tune only publishes a candidate;
it never registers, approves or deploys that candidate automatically. Imported
reports are not evaluation runs executed by the platform.

The frontend navigation, camera capture, transcript, collection format, and
raw tracking are not training outputs. They remain valid when a candidate is
rejected or rolled back.
