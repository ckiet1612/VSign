# Personal Core ML Local

> Since 2026-10-19 the launchers default to
> `sales30-mvitv2s-personal-v3-bodycrop-curated-head-epoch36`, which uses the
> `trim-bodycrop-v1` input framing and the owner's data curation. Its package is
> in `ml/artifacts/sales30_personal_v3_bodycrop_curated_coreml_fp16/`: **FP16**, `CPU_AND_GPU`.
> FP16 benchmark: Core ML 297.8 ms median, p95 303.3 ms; PyTorch 625.3 ms median.
> On 1,600 body-framed clips (all 1,400 Personal + 200 seated/standing), FP16 made the same decision as FP32 on every clip, with and without sentence context; max |Δp| was 0.0035.
> The FP32 package (`..._coreml_fp32/`) remains for rollback via `COREML_MODEL_DIR`. See
> [BODY_FRAMING_LOCAL.md](BODY_FRAMING_LOCAL.md) and
> [the curation report](reports/2026-10-19-curation-v3/README.md). The personal-v1 record below
> is kept as the rollback target; launch it with explicit `PERSONAL_MODEL_DIR`
> and `COREML_MODEL_DIR`.

## Scope

Mac-only acceleration of `sales30-mvitv2s-personal-v1-head-epoch29`, not a
smaller model or a new training run. The original checkpoint, 31-label order,
16 RGB frames at 224x224, normalization and thresholds `0.70`/`0.15` are
preserved. Frontend capture, segmentation and queues are unchanged.

Original checkpoint: `ml/artifacts/sales30_personal_v1/best.pt`, SHA256
`720e94ac16dd0bce08ebcb1849411889015980a2a77655bb28223d632cc79951`.
Accepted converted artifact:
`ml/artifacts/sales30_personal_coreml_fp32_r4/model.mlpackage`.
The converter rewrites pooling and relative-position operations only in its
export model; tests compare them against torchvision originals. Three failed
conversion attempts are retained separately and never replace the checkpoint.

## Setup And Launch

Requires Apple Silicon and macOS 13 or newer. This run used Apple M1,
CoreMLTools 9.0 and FLOAT32. Install dependencies only into the isolated
environment; do not modify the existing `.venv`:

```bash
python3 -m venv .venv-coreml
.venv-coreml/bin/python -m pip install -r services/inference/requirements-coreml.txt
```

Inspect the current backend before stopping it:

```bash
curl -fsS http://127.0.0.1:8000/health
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Stop only its verified PID, then launch from the repository root:

```bash
./scripts/run_coreml_local.sh
```

The launcher rechecks checkpoint/package hashes, conversion status, both
PyTorch benchmark brackets, identical fixture identity, decision parity and
the speed gate. It pins the measured `CPU_AND_GPU` configuration and both
thresholds. Core ML compiles/loads and warms up before startup completes.
Measured worker startup including load/warm-up was about 4.48 seconds for
the selected configuration; cold compilation can vary. Reload the frontend
at `http://localhost:5173` and check `/health` reports `backend: coreml`.

Missing dependencies, invalid artifacts/gates or a nonzero runtime process
failure trigger the verified original PyTorch personal launcher. Explicit
INT/TERM stops do not relaunch anything, and the launcher waits for its
native child. There is no automatic per-request fallback: a prediction error
still follows the normal API error path. A clean runtime exit does not
trigger fallback.

## Benchmark: 2026-10-10

Fresh serial processes, two unmeasured worker-thread warm-ups, 20 recorded
training clips repeated twice per configuration. All workers consume the
same encoded fixture. PyTorch runs bracket the Core ML runs; the gate uses
the lower median and P95 of the two brackets and requires at least 5% lower
median with no P95 regression. A total of 200 measured requests were run.

| Backend | Decode + preprocessing + model median | P95 |
| --- | ---: | ---: |
| PyTorch CPU before | 721.61 ms | 896.08 ms |
| Core ML ALL | 375.11 ms | 384.87 ms |
| Core ML CPU_AND_GPU, selected | 371.76 ms | 385.22 ms |
| Core ML CPU_ONLY, rejected | 1550.81 ms | 1701.36 ms |
| PyTorch CPU after | 722.88 ms | 1152.78 ms |

Selected median improves by 48.48% (1.94x); P95 improves by 57.01% against
the conservative baseline. Model-only median is 329.52 ms versus 702.79 ms.
ALL and CPU_AND_GPU are close; the lower observed median selected GPU, not
proof of a robust advantage between those two configurations.
Every run passed status/accepted-label/top-3 parity with probability tolerance
`1e-5`. Selected maximum probability difference is `1.430511474609375e-06`.
The spare-server WebSocket replay measured median 792.80 -> 378.13 ms and
P95 981.94 -> 438.00 ms, retaining 12/13 positive accepts, uncertain `Chào`
and 7/7 negative rejections.

### Deployed Local Runtime

At 12:06 +07 on 2026-10-10, the verified PyTorch PID 75352 was replaced by
the managed Core ML launcher PID 17256 and native listener PID 17263 at
port 8000. Frontend PID 59320 at port 5173 was preserved. These PIDs are
historical observations; inspect the live listener before stopping anything.
The final port-8000 replay measured median 792.80 -> 380.51 ms and P95
981.94 -> 428.64 ms. All 20 decisions/top-3 matched the baseline within
`1e-5`, retaining 12/13 positive accepts and 7/7 negative rejections.
The original checkpoint checksum was rechecked after deployment and is
unchanged. No spare listeners remain at 8001/8002.

Verification: 335 Python tests passed, including artifact corruption,
startup fallback, invalid timing/fixture evidence and repeated-stop handling;
shell syntax and diff checks passed. Final read-only review reported no
remaining findings in the changed closure points. Existing dependency
warnings remain; the optional `coremltools.optimize.torch` version warning
does not prevent this conversion/runtime path. No frontend files were
changed in this acceleration step.

These are local sequential replay measurements, not camera-to-result latency,
load tests, independent accuracy or realtime acceptance. Capture, encode,
tracking, segmentation and queue delays are excluded from the warmed worker
benchmark. P95 is descriptive for 40 requests per configuration. FP32 parity
on these clips is not a universal mathematical guarantee near thresholds.

## Reproduce

Use fresh output directories so existing evidence cannot be overwritten:

```bash
PYTHONPATH=services/inference:. .venv-coreml/bin/python -m ml.scripts.personal_coreml \
  --output-dir ml/artifacts/sales30_personal_coreml_fp32_rerun --precision fp32

PYTHONPATH=services/inference:. .venv/bin/python -m ml.scripts.benchmark_personal_coreml \
  --coreml-dir ml/artifacts/sales30_personal_coreml_fp32_rerun \
  --baseline-json ml/artifacts/sales30_personal_v1/coreml_before_websocket.json \
  --output-dir ml/artifacts/sales30_personal_coreml_fp32_rerun/benchmark_r2 --rounds 2

COREML_MODEL_DIR="$PWD/ml/artifacts/sales30_personal_coreml_fp32_rerun" \
  ./scripts/run_coreml_local.sh

.venv/bin/python -m ml.scripts.smoke_personal_runtime \
  --url http://127.0.0.1:8000 --backend coreml \
  --output-json ml/artifacts/sales30_personal_coreml_fp32_rerun/api_smoke_local.json
```

Stop the verified existing backend before launching a replacement. The
replay's `passed` field establishes transport/schema success, not accuracy;
inspect decisions, false accepts and parity against the baseline separately.

Evidence in `ml/artifacts/sales30_personal_coreml_fp32_r4/`:
`conversion.json`, `benchmark_r2/benchmark.json`, byte-identical `fixture.json`
and per-worker logs/reports under `benchmark_r2/`, `api_smoke_spare.json`,
`fallback_probe.json` and `managed_stop_probe.json`. The invalid first
benchmark is retained under `benchmark/` and is not used for deployment.
Final deployment evidence is `api_smoke_local.json`,
`deployment_comparison.json` and `runtime_coreml_local.log`.

## Rollback

Inspect `/health` and the port-8000 listener. When launched with the managed
Core ML script, stop its current verified launcher PID with `kill -TERM`;
it forwards shutdown to the native child and waits. Do not reuse historical
PIDs. Check the port is free, then restore the unchanged checkpoint:

```bash
PERSONAL_MODEL_DIR="$PWD/ml/artifacts/sales30_personal_v1" ./scripts/run_personal_local.sh
curl -fsS http://127.0.0.1:8000/health
```

Expect `backend: pytorch` and personal epoch 29. The older seated-v3 model
also remains preserved; its separate rollback procedure is in
`docs/PERSONAL_FINETUNE_LOCAL.md`.

Core ML packages are Mac-specific. A later CUDA deployment should use the
preserved original PyTorch checkpoint and CUDA backend, not this package.
No CUDA host or performance has been verified by this local run.
