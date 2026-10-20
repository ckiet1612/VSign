# Manual Dev/Test Local

## Scope

Development-only diagnostics for the existing word model. This page does not
train, fine-tune, change thresholds, join sentences or modify automatic capture.
It is an operator/developer tool, not a screen customers must interact with.

The Mac launcher uses the already verified personal Core ML runtime and its
existing PyTorch fallback, with confidence `0.70` and margin `0.15` unchanged.
The active backend's exact vocabulary is used; `Không ký hiệu` has separate
background-action controls and false-accept statistics. Both services still
share the Mac's CPU/GPU/memory, so concurrent tests can affect latency even
though they do not modify the model or the existing service's configuration.

## Start

From the repository root, in separate terminals:

```bash
bash scripts/run_dev_test_backend.sh
```

```bash
bash scripts/run_dev_test_web.sh
```

Open `http://127.0.0.1:5174/dev-test`. Backend: `127.0.0.1:8002`.
Both launchers bind loopback only and refuse occupied ports; they do not stop
the existing services at `8000`/`5173`. Stop these launchers with Ctrl+C.
For other free ports, set the same values in both terminals:

```bash
INFERENCE_PORT=8004 DEV_TEST_WEB_PORT=5175 bash scripts/run_dev_test_backend.sh
```

```bash
INFERENCE_PORT=8004 DEV_TEST_WEB_PORT=5175 bash scripts/run_dev_test_web.sh
```

The backend requires both `APP_ENV=development` and `DEV_TEST_ENABLED=true`.
Port 8003 is reserved for the separate seated + personal candidate. The local
test page offers `Model máy chủ` when that candidate is available. Switching
checks metadata and test configuration first, preserves the current selection
on failure, and is locked during capture, encoding, pending saves and clip
review. An unavailable candidate configuration does not prevent returning to
the old endpoint using the last verified label order. The normal 8002 test
backend and candidate 8003 share the local test store, with results grouped by
the immutable runtime key, not merged into a single accuracy denominator.
See [SEATED_PERSONAL_LOCAL.md](SEATED_PERSONAL_LOCAL.md).
The launcher pins these flags and disables collection. Direct production
startup defaults to `APP_ENV=production`, with no `/dev-tests` routes, even
when `DEV_TEST_ENABLED=true`. Vite production builds remove the lazy test
page, navigation, CSS and API calls. A production `/dev-test` URL is not a
test page. Public-demo development also does not expose it.

## Manual Workflow

1. Enter a non-sensitive signer alias, choose the expected word and conditions.
2. Enable camera; press **Bắt đầu test**, perform one complete sign, then
   **Kết thúc test**. Existing capture automatically ends at 3 seconds;
   clips shorter than 650 ms become technical failure records.
3. The expected word, signer, conditions and session are locked during capture,
   encoding and saving. The unchanged frameEncoder generates the center-square
   `224x224` RGB images; uniform sampling sends exactly 16 frames to the same
   backend predictor. There is no landmark fallback on this diagnostic page.
4. Repeat as often as needed. A new session has its own UUID. A page reload
   retains the current session in sessionStorage; persisted history survives
   backend restart. New tabs may have different sessions.
5. Open **Xem clip** to inspect the cropped recording and add review notes.
   Uncheck **Clip hợp lệ** only with a reason and reviewer alias. The original
   prediction is immutable and every review is retained. A removed clip still
   appears in history and exports; it is not deleted or rewritten as correct.
6. Export CSV/JSON for this session or all sessions. CSV escapes formula-like
   text; JSON includes full prediction, top-k, provenance and review history.

The source MP4 is the encoded/cropped sequence, not the full-resolution original
camera view. Exact encoded inference frames can be retrieved from
`GET /dev-tests/trials/{trial_id}/frames`; the MP4 is lossy and is not used to
reconstruct the exact input.

If saving loses its response, **Thử lưu lại** keeps the same payload, trial UUID
and capture timestamp. It does not automatically retry. A saved same-payload
trial is returned without another inference, including after runtime changes.
Reusing the UUID for different data fails with `409`. A new capture carrying
an outdated runtime key is rejected. **Tải lại kết quả** refreshes configuration
as well as statistics, including after the backend was initially unavailable.
For a definitively rejected `409`/`422` capture, **Bỏ lượt bị từ chối** explicitly
discards only that unsaved browser payload; start a new capture under the new
configuration. Reloading never rewrites the old payload's runtime key. This
discard option is not offered for ambiguous network/`503` failures.
Pending, unconfirmed captures live only in browser memory: do not navigate or
reload the page until saving is confirmed. The in-page results/config refresh
does not discard pending footage. Reviews have append-only history, not an
idempotency key; after losing a review response, reload history before resaving.

## Interpretation

| Expected input | Backend decision | Outcome |
| --- | --- | --- |
| A word | Accepts that word | Correct |
| A word | Accepts a different word | Wrong / confused |
| A word | `uncertain` | Uncertain / unidentified |
| `Không ký hiệu` | `uncertain` | Correct rejection |
| `Không ký hiệu` | Accepts a word | False acceptance |
| Either | Capture/decode/model failure | Technical error |

Camera interruption cancels the active capture and records a technical event,
not model uncertainty. A source-video/frame/database persistence failure is
not acknowledged as a completed trial: it leaves the same footage pending for
explicit retry. It is not counted until complete evidence is durably saved.

Each word reports recorded, excluded, technical and evaluated counts, plus
correct/wrong/uncertain percentages and the words confused with it. Percentages
use only non-excluded, non-technical trials; a missing denominator displays
no percentage, not 0% or 100%. Background false-accept percentages have their
own denominator. A pipeline error is not evidence that the model was uncertain.

Statistics are separate for every session and runtime key: backend, model
version, artifact hash, label order, thresholds, device and capture pipeline.
They are not silently pooled across model versions or sessions.

New clips are provisionally included and marked **Chưa kiểm định** until a
reviewer checks them. Therefore these are manual diagnostic rates, not an
independent, validated accuracy result. Track signer/session independence and
review semantic labels before using the exported data as evaluation evidence.
This HTTP manual diagnostic path does not measure automatic segmentation,
sentence boundaries, WebSocket transport reliability or production camera
accuracy. `inference_ms` covers the backend predictor after frame decoding,
not capture/encoding/network/video-storage or end-to-end latency.

## Storage And Privacy

Default: `ml/data/dev-tests/manual/trials.sqlite3`, with UUID subdirectories
containing `clip.mp4` and `frames.json`. The directory is ignored by Git.
It is separate from collection, training, existing evaluation and model data;
there is no training importer or automatic promotion. Any future use for
training needs a separate approved, reviewed data workflow.

Run only one backend process per test directory. Back up the directory only
after stopping its test backend. Clips contain personal camera data: obtain
consent, use aliases, and restrict local filesystem access. Deleting/exporting
data outside this directory is an operator decision, not automatic retention.
`DEV_TEST_DIR` can select another isolated directory but must not overlap
protected data/models or use symlinks. Repository datasets outside the dedicated
`ml/data/dev-tests` namespace are rejected. On macOS `/tmp` is a symlink: for smoke
backend storage use its physical `/private/tmp` path instead.

## Verification

```bash
.venv/bin/python -m pytest tests/test_dev_test_api.py tests/test_dev_test_launchers.py
```

```bash
cd apps/web
npm test -- --maxWorkers=1
npm run lint
npm run build
```

From the repository root after building:

```bash
node tests/e2e/check_dev_test_bundle.mjs
```

Recorded browser smoke uses a separate empty database and replay camera, not
the operator's real test directory. On this Mac, the bundled Playwright entry
can be used after launching the backend with an isolated physical directory:

```bash
DEV_TEST_DIR=/private/tmp/vsign-manual-devtest-rerun/data bash scripts/run_dev_test_backend.sh
```

```bash
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
VSIGN_FAKE_CAMERA_FILE=/tmp/vsign-tracking-display.y4m \
VSIGN_TEST_DATA_ROOT=/tmp/vsign-manual-devtest-rerun/data \
VSIGN_SMOKE_OUTPUT=/tmp/vsign-manual-devtest-rerun/browser \
node tests/e2e/manual_dev_test.mjs
```

Use a fresh directory for each run. Replay verifies application mechanics,
not unseen-signer recognition or webcam acceptance. See
`docs/reports/2026-10-11-manual-dev-test.md` for this run's evidence.
