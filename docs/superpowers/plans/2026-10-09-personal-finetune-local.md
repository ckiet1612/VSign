# Personal Fine-Tune Local Implementation Plan

> **For agentic workers:** Execute inline with test-driven-development and verification-before-completion. Do not commit, push, or create a worktree. Use one bounded read-only review as required by requesting-code-review.

**Goal:** Train and deploy a reversible 31-class local candidate from the accepted seated-v3 checkpoint.

**Architecture:** Freeze the existing MViTv2 backbone, cache deterministic 16-frame CPU features, and optimize the 31-class linear head. Preserve all 30 existing output indices and append the idle class. Reject idle predictions in both server backends. Keep the old artifacts and validation/test split unchanged.

**Tech Stack:** Existing Python 3.9 environment, PyTorch 2.0, torchvision, PyAV, pytest, FastAPI, React/Vite.

**Spec:** User approval in this chat on 2026-10-09: perform real fine-tuning and deploy the current model. The hardware probe found 8 GB RAM, no CUDA, and unsupported MPS Conv3D.

## Global Constraints

- Baseline: `ml/artifacts/sales30_seated_v3/training/best.pt`.
- Input: `[1,3,16,224,224]`, ImageNet normalization, uniform temporal sampling.
- Personal batch: all 1,400 samples in train; no random same-session evaluation split.
- Old train/validation/test: 2,425 / 744 / 351, unchanged.
- Negative evaluation is training diagnostics only; no independent-session acceptance claim.
- Candidate artifacts and feature cache have distinct paths and content identities.
- No overwrite of v3, no changes to existing camera/capture/tracking behavior.
- Select checkpoint using validation, never test. Stop deployment if old validation or test accuracy, macro-F1, or correct-positive runtime acceptance drops by more than 0.02 absolute at unchanged 0.70/0.15 thresholds.

## Task 1: Dataset and Classifier Contracts

Files: create `ml/personal_finetune.py`, `tests/test_personal_finetune.py`.

- [x] Add failing tests for preserved head rows, exact label mapping, immutable baseline splits, same-session train-only assignment, and cross-split duplicate rejection.
- [x] Run `.venv/bin/python -m pytest tests/test_personal_finetune.py -q`; confirm missing implementation.
- [x] Implement `expand_head(head)`, `prepare_rows(root, baseline_manifest, collection_root, labels)`, and `evaluate_features(head, features, targets, labels)`.
- [x] Verify head expansion keeps the 30 original rows byte-for-byte and appends exactly one negative row.

## Task 2: Training and Real Execution

Files: create `ml/scripts/finetune_sales30_personal.py`.

- [x] Add CLI tests rejecting baseline/output/cache collisions and mismatched cache identity.
- [x] Implement SHA256-pinned manifest, resumable feature cache, and head-only training with fresh optimizer.
- [x] Save full compatible model `state_dict`, labels, provenance, metrics and run identity.
- [x] Execute `.venv/bin/python -m ml.scripts.finetune_sales30_personal --root . --output-dir ml/artifacts/sales30_personal_v1`.
- [x] Confirm weights actually changed, old backbone did not, original artifacts remained intact, and compare baseline/candidate on the same validation/test features.

## Task 3: Negative Handling and Deployment

Files: modify `services/inference/app/backends/pytorch.py`, `services/inference/app/backends/onnx.py`, their existing tests; create `scripts/run_personal_local.sh` and `docs/PERSONAL_FINETUNE_LOCAL.md`.

- [x] Add tests where idle wins with high confidence and must return uncertain with no accepted label; preserve positive acceptance and low-confidence rejection.
- [x] Run targeted tests before implementation, then add the idle rejection rule.
- [x] Run full backend tests, frontend tests/build, and `git diff --check` (263 Python tests, 253 frontend tests, build/lint passed before candidate deployment).
- [x] Start candidate on a spare port and verify metadata and real WebSocket positive/negative payloads.
- [x] Only after the measured regression gate passes, replace the local port-8000 backend; do not stop Vite or other services.
- [x] Record exact launch/rollback commands, model version, diagnostics, and remaining independent-camera evaluation limits.

## Continuation On 2026-10-09

- Reused the still-running original training process (PID 46240); did not launch duplicate extraction or modify its training code.
- Baseline checkpoint SHA256 remains `e95f9ed6d7501cfe49b66001245c1510d00940e2f39cb4aeccbc44768c9caceb`.
- One read-only reviewer found that the launcher inherited threshold overrides despite the fixed evaluation gate. A failing override test reproduced this; the launcher now pins confidence/margin at 0.70/0.15. All 32 focused personal-finetune/runtime/negative-backend tests pass.
- The first parallel frontend run had timeout failures during CPU extraction. The sequential run exposed a tracking-test setup race: the readout could appear before the animation effect registered callbacks. The helper now waits for that effect; all 253 frontend tests pass with `npm test -- --maxWorkers=1`. Build and lint pass.
- Final regression suite: 273 Python tests and 253 frontend tests pass; build/lint and `git diff --check` pass. Reviewer recheck reports no remaining actionable findings for the threshold correction.
- Training completed: selected epoch 29 of 40, `sales30-mvitv2s-personal-v1-head-epoch29`, checkpoint SHA256 `720e94ac16dd0bce08ebcb1849411889015980a2a77655bb28223d632cc79951`. Validation/test accuracy: 74.19% -> 74.87% / 96.58% -> 96.58%. Both regression gates pass; only `head.1.weight` and `head.1.bias` changed.
- The original 18:49 process predated the 19:28 cache-checksum implementation, so its final cache lacked `integrity_sha256`. Independent verification reproduced all recorded baseline/candidate metrics and regenerated 25 representative features (all byte-identical). Preserved `features.legacy-unsealed.pt`, then sealed/reloaded the cache without changing features. See `ml/artifacts/sales30_personal_v1/artifact_verification.json`; this was not a full re-extraction.
- Real port-8001 WebSocket smoke passes: 20 requests, 12/13 correct positive accepts (one `Chào` uncertain), 7/7 negatives rejected, verified 31-label map and 0.70/0.15 thresholds. See `api_smoke_spare.json`.
- Deployed to port 8000 at 20:22 +07 on 2026-10-09, PID 58764. The post-deployment smoke reproduces the spare-port result (`api_smoke_local.json`). Browser shows the candidate version and connected AI with camera still off. Original Vite PID 59320 remains running; spare backend stopped. Exact state and provenance are in `deployment.json`; launch/rollback commands and evidence limits are in `docs/PERSONAL_FINETUNE_LOCAL.md`.
