# Live Capture Queue Implementation Plan

> **For agentic workers:** Use the executing-plans workflow inline in the current workspace. The user approved implementation on 2026-10-08. No commits or unrelated edits are requested. A read-only review follows the requesting-code-review skill; implementation stays local.

**Goal:** Continue collecting isolated webcam signs while inference processes an earlier sign, with one running request and at most two waiting clips.

**Architecture:** A small FIFO scheduler owns waiting clips and the running request. A React hook connects that scheduler to the existing WebSocket and local landmark callbacks. Capture pauses only when the waiting queue is full, not whenever inference is busy. Cancelling a context drops waiting clips and marks a running request cancelled, but retains its slot until its response arrives.

**Tech Stack:** Existing React, TypeScript, Vitest, WebSocket and RGB encoder.

**Spec:** The approved design in this conversation: separate live capture/inference, two waiting clips, explicit full indication, serial submission, context cancellation, stage timing and unchanged v3 thresholds.

## Global Constraints

- Preserve the current dirty worktree, model artifacts, data, and PROJECT_PLAN.md.
- Keep 16 RGB frames at 224x224, fixed center crop, and existing sign/prediction thresholds.
- Keep manual recognition and data collection working through their existing paths.
- No transcript insertion without explicit confirmation; no persistent camera storage.
- Timing names distinguish clip duration, encoding, queue wait and AI round trip. Round trip is not a pure model benchmark.
- Backend and frontend services already running are reused.

## Task 1: Bounded FIFO Scheduler

Files: create `apps/web/src/lib/automaticInferenceQueue.ts` and its test.

- [x] Add failing tests: three accepted clips mean one active plus two waiting; reject a fourth without replacing entries; mismatched/duplicate replies do not release the slot; matching replies advance FIFO; context cancellation drops waiting entries but drains the active slot; deterministic wait/response timing.
- [x] Run `npm test -- src/lib/automaticInferenceQueue.test.ts` and observe red.
- [x] Implement `AutomaticInferenceQueue.enqueue`, `startNext`, `complete`, `cancel`, `pendingCount`, `busy`, `full` using literal capacity 2 and monotonic timestamps.
- [x] Rerun the scheduler tests and observe green.

## Task 2: Capture/Inference Integration

Files: create `apps/web/src/hooks/useAutomaticInferenceQueue.ts`; modify `App.tsx`, `useAutomaticSignCapture.ts` and corresponding tests.

- [x] Add integration regressions for capturing while an earlier request is pending, FIFO draining, full-queue pause/resume, cancellation on camera/manual/route changes, local promise completion and failures, and uncancelled manual inference behavior.
- [x] Run `npm test -- src/App.automatic.test.tsx` and observe the old pause behavior fail.
- [x] Connect scheduler completion through the prediction callback; preserve the transport slot for cancelled requests; guard late local responses; publish queue state.
- [x] Replace inference-busy capture pause with queue-full pause. Do not let a rejected capture cancel an unrelated active request.
- [x] Pass optional capture/encode measurements with the existing sequence callback. Record queue wait and response duration only for matching completed requests.
- [x] Rerun integration and hook tests to green.

## Task 3: Visible Status, Documentation and Verification

Files: `CameraPanel.tsx`, its tests, `styles.css`, `README.md`.

- [x] Test visible queue counts, full-state indication and timing labels.
- [x] Add compact status/timing readouts without adding session/history/upload features.
- [x] Document capacities, cancellation, clip/round-trip timing meanings and camera-test boundary.
- [x] Run `npm test`, `npm run build`, `npm run lint`, `git diff --check`.
- [x] Use Playwright with system Chrome and a replay camera; delay inference responses to demonstrate queued capture. Check camera cancellation, 16-frame payloads, no automatic transcript insertion, and responsive layouts.
- [x] Report final evidence and the existing frontend URL; real-camera quality still requires user acceptance.

## Verification Record

- 2026-10-08: 131 frontend tests passed across 27 files; TypeScript/Vite build,
  ESLint and `git diff --check` passed.
- Scoped read-only review: no actionable findings. Added the identified coverage
  gap for manual -> automatic -> manual transitions during pending local inference;
  the regression passed without further production changes.
- Rerunnable Chrome smoke: `tests/e2e/live_capture_queue.mjs` passed against the
  existing PyTorch v3 backend. Evidence is at
  `/tmp/vsign-live-queue-smoke-20261008/report.json` and adjacent screenshots.
- Smoke submitted sequences 0 and 1 serially, cancelled waiting sequence 2, then
  successfully submitted manual sequence 3. All submitted payloads had 16 frames;
  decoded RGB dimensions were 224x224. No automatic transcript insertion or page
  errors; tested widths 320, 390, 768 and 1365 had no measured horizontal overflow.
- Smoke replies were held artificially. Its timings are not performance benchmarks;
  replay clips are not independent real-camera recognition-quality evidence.
- Existing frontend remains at `http://localhost:5173`. No model/threshold/data/
  PROJECT_PLAN.md changes, no commit/push, and no user-owned services stopped.
