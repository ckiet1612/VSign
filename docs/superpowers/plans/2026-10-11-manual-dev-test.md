# Manual Dev/Test Implementation Plan

**Goal:** Implement the approved manual word test, persistent evidence, review,
per-word statistics and CSV/JSON exports without changing recognition models.

**Architecture:** Reuse uniform manual RGB capture and frameEncoder. Add a
development-only lazy frontend page and a conditional local-only backend router.
The backend runs the existing predictor, records authoritative outcomes and exact
inference frames plus a source MP4; SQLite separates immutable trials from reviews.

**Constraints:** No model, threshold or training-data edits. Test data lives under
`ml/data/dev-tests`, never collection/train. Production is the backend default;
both `APP_ENV=development` and `DEV_TEST_ENABLED=true` are required. Production
frontend builds must contain no test page, API strings or dev CSS. No commits.

## Execution

- [x] Write failing API tests for feature gates, local access, authoritative
  outcomes, negative false accepts, durable replay, idempotency and review/export.
- [x] Implement `app/dev_test_contract.py`, `app/dev_test_store.py`,
  `app/dev_test.py`; add settings and conditional router registration only.
- [x] Write failing frontend tests for capture, pending retries,
  review failures and explicit excluded/technical counts.
- [x] Implement `src/dev-test/` using existing useCamera/useSignCapture and a
  dev-only dynamic entry; keep customer App behavior unchanged.
- [x] Verify backend/frontend regressions, production bundle exclusion and
  screenshots plus recorded-camera browser flows on desktop/mobile.
- [x] Add separate local launchers and operating documentation. Start the dev
  servers on free ports, verify model preservation and report evidence limits.

Review follow-up: camera interruption, initial/stale runtime config recovery,
and transient video-encoder failure were reproduced with failing tests, then
fixed. Final closure: 177 related Python tests, 307 frontend tests, lint,
normal/public builds and dev-bundle exclusion passed; latest browser replay
saved five trials from six submissions and checked simulated camera loss.
Independent rereview closed the three findings. The live dedicated backend
uses the empty default test directory at `ml/data/dev-tests/manual`; frontend
is at `http://127.0.0.1:5174/dev-test`. Original 8000/5173 listeners remain.

**Verification commands:** `.venv/bin/python -m pytest tests/test_dev_test_api.py`,
`npm test -- --maxWorkers=1`, `npm run build`, `npm run lint`, and browser smoke
against the isolated dev backend. Fake/replay camera proves mechanics only.
