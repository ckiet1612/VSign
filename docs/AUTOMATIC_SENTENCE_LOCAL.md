# Automatic Sentence Drafts

## B2B Scope

The enterprise operator enables the camera, automatic capture and automatic
word insertion once. The customer only signs; no web click, word confirmation
or sentence-completion click is required. Manual capture/insertion remain
available and remain the default outside that operator-selected flow.

This is a development workflow for isolated Sales30 signs, not continuous
sign-language translation. Recognition weights, frame sampling, thresholds
and original recordings are unchanged. It does not create an order, accept a
transaction or claim that the customer's complete intent was understood.

## Runtime

Run the backend and frontend in separate terminals from this repository:

```bash
./scripts/run_coreml_local.sh
```

```bash
npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://localhost:5173`. The operator selects recognition, enables the
camera, chooses `Tự động beta` and `Thêm từ tự động`. Automatic sentence
drafting requires a real verified recognition model, available backend
metadata and a local (not public demo) frontend. It is disabled in collection
mode and does not save videos. The operator clears the transcript between
customers; this invalidates old insertion/composition results, including
replies still in flight. This is not yet a separate kiosk/employee dashboard.

## Boundary And Late Words

After 1,800 ms without a new recognized word or capture end, the coordinator
may compose a draft, but only when capture/encoding are inactive, the FIFO is
empty, tracking is fresh (500 ms maximum age) and the page is visible.
Timing starts again when a delayed prediction arrives, so a queued adjective
cannot be excluded simply because the hands have already stopped.

Each capture receives an immutable sentence-owner token at capture start.
The pause between captures uses capture-end time, excluding frame-encoding
and model-reply latency. A new capture after at least 5,000 ms of rest begins
a new draft, even when the previous draft is still awaiting a prediction,
composing or marked for review. A shorter rest continues the same draft.
Late words and uncertainty stay with their original sentence, not whichever
draft is currently last on screen. An uncertainty in one sentence does not
block later sentences; its warning remains visible in the history.

Resuming the same sentence aborts its stale composition. Starting another
sentence preserves the previous composition and displayed history. Requests
are composed sequentially, with the existing 20-second deadline freeing the
slot after a failure. Repeated-word debounce still uses the one-second rule,
but in this automatic sentence flow its clock is capture-start time rather
than reply-arrival time, so two separately signed repetitions are not lost
when delayed FIFO replies arrive together. These constants are in
`apps/web/src/lib/automaticSentence.ts`.
They are engineering heuristics, not validated linguistic boundaries.

Example: the FIFO still contains `Rẻ` after `Tôi Muốn Mua Tủ lạnh`. No sentence
request is sent until that reply arrives and the pipeline is idle. The draft
then reads `Tôi muốn mua tủ lạnh rẻ.`. If an earlier draft was already visible,
resumed signing invalidates it and the late qualifier triggers recomposition.

All generated sentences are explicitly labeled `Dự thảo · chưa xác nhận`.
The recognized words remain visible. Clipboard output in automatic mode
also carries an unconfirmed-draft prefix and any missing-segment warning.

## Missing Segments And Limits

An uncertain/invalid/filtered result, capture cancellation/encoding error,
failed inference or full queue creates a persistent review warning. That
draft is composed once from the words that were actually recognized and stays
marked for review; the composer cannot invent the missing sign. A composer
failure itself is not retried forever. Later successful words in the same
sentence do not silently erase the gap and trigger a revised best-effort
draft. After a long pause, the next sentence
starts independently without a clear/confirm action. Camera/model/route/mode
changes also invalidate pending
composition and preserve a review condition when a transcript exists.
Composition has a 20-second deadline; a stalled request is aborted, keeps
the raw words and becomes a review warning rather than being retried forever.
The existing API accepts at most 30 labels per sentence request; longer
unsegmented drafts are rejected for review, never silently truncated.

The operator can clear a warning-only session even if no word was recognized.
Undo/clear invalidate pending automatic insertions; a late reply from the
previous transcript cannot repopulate a cleared customer session. Normal
inference still drains its transport slot before sending newer queued jobs.

**Silent omission cannot be detected from text alone.** If the detector never
captures `Rẻ`, or the model confidently outputs an incomplete/wrong sequence
without an uncertainty signal, this layer cannot reconstruct the lost word.
Long pauses can also split a qualifier into another draft. No rule or language
model is allowed to invent `Rẻ` to disguise that missing evidence. Before
enterprise acceptance, use independent camera sessions to measure missed
qualifiers, repeated words, boundary errors, queued suffixes and incorrect
acceptances. Drafts are not a substitute for that evaluation or employee
confirmation of a commercial request.

## Natural Wording

Update 2026-10-10: the default local composer now uses the approved expanded
rule families with separate grammar-review warnings. See
`docs/SENTENCE_RULES_LOCAL.md` for examples, limits, verification and
`SENTENCE_RULES=legacy` rollback. The narrower template description below
describes legacy behavior.

The backend runs without an external key. Its local composer reorders only
an unambiguous template with one `Tôi`, one sales action, one recognized
product, optional `Muốn`/`Cần` and compatible recognized qualifiers. It adds
no product, qualifier, quantity or intent; other sequences retain their
original order with basic case/punctuation normalization.

If an operator has explicitly configured the existing external AI composer,
its output must preserve the recognized lexical counts and complete label
phrases, and may add only a restricted set of grammatical words. Missing a
recognized qualifier, adding another product/price or inserting negation
rejects the output and uses the local fallback. This lexical guard is not a
general proof of semantic equivalence or language quality. No external model,
key, training job or new dependency was installed in this change.

Automatic drafting sends recognized words to the existing `/sentence/compose`
endpoint at an idle boundary. The endpoint may forward those words to the
external provider only when its key/model were configured by the operator.
Camera frames are sent only along the existing inference path, not to the
sentence composer. Transcript/draft history stays in page memory.

## Verification

Focused tests cover pending/late qualifiers, resumed signing, stale HTTP
results, context changes, uncertainty, queue saturation, clear/undo,
warning-only reset, multiple sentences, recovery after review/timeouts and
repeated words with delayed replies. Backend tests check bounded grammar and rejection of
omitted qualifiers or invented facts. Use the existing sequential frontend
test configuration:

```bash
npm --prefix apps/web test -- --maxWorkers=1
npm --prefix apps/web run lint
npm --prefix apps/web run build
.venv/bin/python -m pytest -q
```

Browser smoke uses the real segmenter, RGB encoder, FIFO and sentence API,
with test-only raw tracking/prediction fixtures and a replay camera:

```bash
VSIGN_PLAYWRIGHT_FROM="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json" \
VSIGN_FAKE_CAMERA_FILE=/tmp/vsign-auto-transcript-camera-20261008.y4m \
VSIGN_SMOKE_OUTPUT="$PWD/tmp/automatic-sentence-rerun" \
node tests/e2e/automatic_sentence.mjs
```

Use an existing replay camera or prepare one with the E2E guide. Screenshots
and DOM overflow checks cover 320/390/768/1365 px. Fixtures/replays are not
real-camera quality, model accuracy, continuous-language accuracy, a latency
benchmark or production acceptance. In this run screenshots were captured,
but the image-viewing tool was unavailable for visual inspection.

### Local Evidence: 2026-10-10

- 272 frontend tests and 337 Python tests passed; lint, build and diff checks
  passed. No independent code review was performed for this change.
- Browser smoke passed with seven real 16-frame encoded requests, a delayed
  `Rẻ` fixture included in the only composed sentence, the then-current
  fail-closed behavior for an uncertain suffix, no page errors and no horizontal overflow at all
  four viewport widths. Final report:
  `tmp/automatic-sentence-20261010/browser_r2/report.json`.
- The restarted real Core ML backend remained personal epoch 29. Its 20-clip
  WebSocket replay retained every prior decision/top-3 within `1e-5`
  probability tolerance: 12/13 correct positive accepts, uncertain `Chào`
  and 7/7 negative rejections. This is training-clip replay, not new-session
  accuracy. The checkpoint SHA256 remains
  `720e94ac16dd0bce08ebcb1849411889015980a2a77655bb28223d632cc79951`.
- `tmp/automatic-sentence-20261010/verification.json`, `runtime.log` and
  `api_smoke_model.json` record verification and actual runtime evidence.
  Launcher PID 23864/native PID 23871 at port 8000 are historical observations;
  the existing frontend PID 59320 at port 5173 was preserved.

### Continuous-Sentence Fix: 2026-10-10

- 287 frontend tests and all 337 Python tests passed; lint, build and diff
  checks passed. The initial regressions reproduced one warning blocking all
  following sentences and two delayed sentences being merged into one.
- The final browser smoke passed 14 real 16-frame encoded requests against
  fixture predictions and the real sentence endpoint. It covered four
  consecutive drafts without clearing, recovery after an uncertain sentence,
  delayed results assigned to different sentences, and repeated words whose
  replies arrived together. No page errors or overflow at 320/390/768/1365 px.
  Report: `tmp/continuous-sentence-20261010/browser_final/report.json`.
- The real Core ML backend was not restarted or changed. A new replay of the
  same 20 clips exactly matched the preceding run's decisions, top-3 labels
  and probabilities (maximum delta 0). Checkpoint, segmenter, capture hook,
  sampling, encoding, FIFO and runtime/launcher SHA256 values were unchanged.
  Report: `tmp/continuous-sentence-20261010/model_comparison.json`.
- No training, model/API change, external model installation or independent
  review was performed. Replay/fixtures do not prove physical-camera,
  unseen-signer or semantic sentence-boundary quality. The 1,800/5,000 ms
  pause rules remain heuristics; no automatic customer-change detection or
  commercial transaction confirmation was added.

### Best-Effort Review Fix: 2026-10-10

- A real user screenshot showed five recognized words but no sentence draft,
  because one uncertain capture put the draft in `review` and `prepare()`
  rejected every reviewed draft. The coordinator now composes recognized
  words once, keeps the missing-segment warning, and never invents the absent
  sign. Changes to camera/model/transport context still cancel composition.
- 287 frontend tests, lint, build and diff checks passed. Browser smoke passed
  14 real 16-frame encoded requests with no page errors. The uncertain-suffix
  case displayed both the warning and the best-effort `Mua.` draft; the
  screenshot was visually inspected. Report and screenshot:
  `tmp/continuous-sentence-20261010/browser_best_effort/report.json` and
  `tmp/continuous-sentence-20261010/browser_best_effort/missing-qualifier.png`.
- The personal epoch-29 checkpoint, capture/segmentation, sampling, encoding
  and Core ML backend SHA256 values remained unchanged. This UI/coordinator
  fix does not improve classifier accuracy and cannot recover a sign that was
  never captured or confidently misclassified.

## Disable And Rollback

The operator selects manual capture or manual insertion to disable automatic
sentence drafting. Clear the transcript before the next customer. The
original manual sentence button remains available. The model checkpoint and
Core ML/PyTorch launchers remain unchanged; their rollback procedure is in
`docs/PERSONAL_COREML_LOCAL.md`.
