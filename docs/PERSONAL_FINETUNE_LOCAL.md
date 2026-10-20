# Personal Fine-Tune Local

This run adapts the accepted Sales30 seated-v3 epoch-5 model to the new
`personal-100` recordings. It trains the final linear classifier, not the
backbone, and appends `Không ký hiệu` at output index 30. The first 30 labels
and their indices stay unchanged.

## Data Protocol

| Source | Train | Validation | Test |
| --- | ---: | ---: | ---: |
| Existing standing/seated | 2,425 | 744 | 351 |
| Personal recordings | 1,400 | 0 | 0 |
| Combined | 3,825 | 744 | 351 |

The personal batch has 13 positive labels with 100 clips each and 100
negative clips. All samples share one session. No random split creates a
supposed independent evaluation set. Exact MP4 and decoded-frame hash audits
found no duplicates; all 1,400 clips decoded at 224x224 with metadata-matching
frame counts (26-29). Semantic label and crop quality have not been verified.

## Train

From the repository root:

```bash
.venv/bin/python -u -m ml.scripts.finetune_sales30_personal \
  --root . --output-dir ml/artifacts/sales30_personal_v1
```

The pipeline validates the complete source manifest, hashes each clip,
preserves existing splits, and caches uniform-16 ImageNet-normalized features.
Feature extraction can resume from the cache only when its identity matches.
Selective video decoding converts only the uniformly selected frames to RGB;
missing/inaccurate container counts fall back to the original decoder. Tests
and eight real clips across all three sources produced byte-identical input
tensors with the old decoder. The actual run uses the existing PyTorch 2.0
CPU environment; an isolated PyTorch 2.8/MPS probe was not adopted.
Training uses a fresh AdamW optimizer, class-balanced cross-entropy and
distillation from the old classifier on the old training samples.

The default schedule is 40 epochs with learning rate 0.0005 and seed 20261009.
An epoch is eligible only when old validation accuracy, macro-F1 and
correct-positive runtime acceptance drop by no more than 0.02 absolute and
negative training recognition is at least 90%.
Among eligible epochs, choose the highest old-validation macro-F1. Evaluate
the unchanged standing test once after selection; do not tune against it.

Outputs include `best.pt`, `labels.json`, `manifest.csv`, `audit.json`,
`run_identity.json`, `features.pt`, `history.json`, `comparison.json` and
`summary.json`. Existing trained outputs cannot be overwritten.

## Completed Local Run: 2026-10-09

Selected epoch 29 of 40: `sales30-mvitv2s-personal-v1-head-epoch29`.
Checkpoint SHA256:
`720e94ac16dd0bce08ebcb1849411889015980a2a77655bb28223d632cc79951`.
Only `head.1.weight` and `head.1.bias` changed, including the original positive
rows; every backbone tensor and the original v3 checkpoint remain unchanged.

| Existing evaluation | Baseline accuracy | Candidate accuracy | Baseline macro-F1 | Candidate macro-F1 | Correct-positive acceptance, baseline -> candidate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Validation, 744 samples | 74.19% | 74.87% | 0.6976 | 0.7116 | 68.82% -> 70.97% |
| Standing test, 351 samples | 96.58% | 96.58% | 0.9485 | 0.9587 | 95.16% -> 95.73% |

Both regression gates pass. Personal-training negative recognition is 92/100,
with 1/100 false positive acceptances at the unchanged thresholds. These are
training diagnostics, not independent evaluation results.

The original extraction process started at 18:49, before cache-checksum code
was added at 19:28. Its final cache therefore lacked `integrity_sha256`.
Verification reproduced every recorded baseline/candidate evaluation metric
and regenerated 25 representative features across all source/split groups,
the 13 personal positive labels and seven negative actions. Every regenerated
feature was byte-identical. The original cache is retained as
`features.legacy-unsealed.pt`; the sealed cache has the same tensors and now
passes the strict loader. This was not a full 4,920-clip re-extraction.

At 20:22 +07, the candidate replaced the v3 backend at port 8000. Vite PID 59320
was preserved; the spare port-8001 server was stopped. Real WebSocket smoke
before and after deployment produced 12/13 correct positive accepts, one
uncertain `Chào`, and 7/7 negative rejections. No wrong word was accepted in
those 20 replays. The browser displayed the candidate version and connected
AI without enabling the camera.

Evidence under `ml/artifacts/sales30_personal_v1/`:

- `artifact_verification.json`: checkpoint/backbone checks, reproduced metrics,
  legacy-cache preservation and 25 regenerated features.
- `comparison.json`, `history.json`, `summary.json`: selection and regression.
- `api_smoke_spare.json`, `api_smoke_local.json`: actual recorded-clip WebSocket requests.
- `deployment.json`, `runtime_local.log`: local process state and startup evidence.

Verification after the launcher correction: 273 Python tests, 253 frontend
tests (`npm test -- --maxWorkers=1`), build, lint and diff checks pass.
The tracking test helper now waits for its animation effect before injecting
frames; camera/capture behavior was not modified. A bounded read-only review
found the threshold override issue and its recheck confirmed the correction.

## Launch and Roll Back

After the measured regression gate passes:

```bash
./scripts/run_personal_local.sh
```

This uses PyTorch CPU, validates checkpoint SHA256 and the exact 31-label
mapping, and keeps confidence/margin thresholds at 0.70/0.15. Idle predictions
return `uncertain` and are not offered as transcript words. Frontend remains
at `http://localhost:5173`; reload an already-open page to refresh metadata.
The launcher pins both thresholds even when the caller has different environment
values, so deployed acceptance matches the measured regression gate.

### Mac CPU Optimization

The personal launcher now defaults to `OMP_NUM_THREADS=8` and performs CPU
warm-up before accepting requests. Preprocessing skips redundant conversion
and resizing for RGB 224x224 frames, caches normalization constants and returns
contiguous input. Tests compare every input value with the old preprocessing.
No checkpoint, labels, thresholds, camera segmentation or API schema changed.

Each thread configuration ran in a fresh process, with inference on one worker
thread as in FastAPI. Two unmeasured worker warm-ups preceded 40 requests
(the same 20 recorded clips repeated twice):

| CPU threads | Decode + preprocessing + model median | P95 |
| --- | ---: | ---: |
| 1 | 1,386 ms | 1,553 ms |
| 2 | 977 ms | 1,319 ms |
| 4 | 767 ms | 1,052 ms |
| 8 | 764 ms | 873 ms |

The 4/8-thread median difference is too small to establish a robust speed
advantage; 8 had the lower observed tail in this run. Model execution dominates:
8-thread medians were 745 ms model, 13 ms preprocessing and 6 ms decoding.
All 160 decisions, top-3 labels and probabilities matched the baseline exactly.
A short TorchScript probe was slower and was not adopted. Existing Python and
PyTorch versions remain unchanged.

After replacing the verified backend PID 58764 with PID 75352 at port 8000,
the same 20-clip real WebSocket replay had median 819 -> 696 ms and P95
1,069 -> 963 ms (15% lower observed median). Decisions, suggestions and
confidence were identical: 12/13 positive accepts, uncertain `Chào`, and 7/7
negative rejections. Frontend PID 59320 at port 5173 was preserved.
PIDs are historical observations; always inspect the current listener before
stopping a process. Verification: 295 Python tests passed, shell syntax and
diff checks passed; existing dependency warnings remain.

These are small sequential replay measurements, not independent-session
accuracy, a load benchmark or camera-to-result latency. The before replay
includes first-request overhead. The warmed sweep is separate, and its P95
is descriptive for 40 requests. Real camera segmentation and queue delays
remain unchanged; this does not establish realtime recognition.

Evidence in `ml/artifacts/sales30_personal_v1/`: `cpu_before_20261009.json`,
`cpu_thread_benchmark.json`, `cpu_after_optimized.json`,
`cpu_deployment_comparison.json` and `runtime_cpu_optimized.log`.

Rerun the warmed benchmark from the repository root using a fresh output path:

```bash
PYTHONPATH=services/inference:. .venv/bin/python -m ml.scripts.benchmark_personal_cpu \
  --baseline-json ml/artifacts/sales30_personal_v1/cpu_before_20261009.json \
  --threads 1 2 4 8 --rounds 2 \
  --output-json ml/artifacts/sales30_personal_v1/cpu_thread_benchmark_rerun.json
```

Normal launch remains `./scripts/run_personal_local.sh`. To restore the old
thread setting, stop only the verified current backend listener, then run
`OMP_NUM_THREADS=4 ./scripts/run_personal_local.sh`. Overrides must be integers
from 1 to 64; model and threshold verification remains mandatory.

To launch the preserved v3 PyTorch baseline after stopping the candidate:

Inspect `GET /health` and `lsof -nP -iTCP:8000 -sTCP:LISTEN`, then stop only
the verified candidate PID with `kill -TERM <pid>`. The deployment recorded
PID 58764, but check the current listener before using any historical PID.
Run the baseline command below from the repository root. To return to the
candidate later, stop the verified baseline process and use the personal launcher.

```bash
INFERENCE_BACKEND=pytorch \
MODEL_VERSION=sales30-mvitv2s-seated-v3-epoch5 \
PYTORCH_MODEL_PATH=ml/artifacts/sales30_seated_v3/training/best.pt \
LABEL_MAP_PATH=ml/artifacts/sales30_seated_v3/labels.json \
PYTORCH_DEVICE=cpu LABELS_VERIFIED=true COLLECTION_ENABLED=true \
OMP_NUM_THREADS=4 PYTHONPATH=services/inference:. \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Core ML Acceleration

The same personal epoch-29 checkpoint now has a separate FLOAT32 Core ML
candidate for Apple Silicon. The controlled warmed replay measured median
721.61 -> 371.76 ms with unchanged decisions at `1e-5` probability tolerance.
The original PyTorch artifact and launcher remain available for rollback.
See [PERSONAL_COREML_LOCAL.md](PERSONAL_COREML_LOCAL.md) for setup, gates,
before/after evidence, deployment status and rollback. This does not establish
camera-to-result realtime performance.

## Evidence Limits

Personal positive accuracy, negative recognition and false acceptance are
training diagnostics only. There is no independent-session negative set.
Unchanged standing test and old seated validation measure regression on
existing data, not new-session webcam accuracy or unseen-signer generalization.
Local deployment is not production acceptance. ONNX/Docker defaults remain
on the previously accepted v3 artifact; this candidate has its own launcher.

The rerunnable real WebSocket smoke sends one preselected positive per
collected label and representative negative actions, never accesses a real
webcam, and checks version, label mapping, framing and negative rejection:

```bash
.venv/bin/python -m ml.scripts.smoke_personal_runtime \
  --url http://127.0.0.1:8000 \
  --output-json ml/artifacts/sales30_personal_v1/api_smoke_rerun.json
```

Use a fresh output path for each smoke. `passed` means the runtime/transport
contract passed; positive/negative replay counts remain training diagnostics.
