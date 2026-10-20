# VSign System Admin Local

This console administers the configured VSign instance, not multiple tenants.
`system_admin` is separate from enterprise `admin` and internal `model_admin`.
Local system administration is passwordless and must not be exposed publicly.

## Start

From the repository root, migrate once after backing up the existing SQLite
database. The migration does not promote any existing membership:

```sh
cd "/Users/macbook/Documents/Personal Library/VSign"
PYTHONPATH=services/inference:. .venv/bin/python -m app.migrate
bash scripts/run_system_admin_local.sh
```

In another terminal:

```sh
cd "/Users/macbook/Documents/Personal Library/VSign/apps/web"
VITE_PUBLIC_DEMO=false \
VITE_PLATFORM_HTTP_URL=http://127.0.0.1:8000 \
VITE_INFERENCE_HTTP_URL=http://127.0.0.1:8000 \
VITE_INFERENCE_WS_URL=ws://127.0.0.1:8000/ws/inference \
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Open `http://127.0.0.1:5174`. A system account starts on the system overview.
Stop the current listener before starting another on the same backend port.
The launcher keeps existing Core ML verification and fallback behavior; it does
not enable deployment, evaluation or integration workers automatically.

## Workflows

| View | Existing connected operations |
| --- | --- |
| Overview | Real runtime status and links to all administration views |
| Recognition | Manual/automatic capture and transcript |
| Data | Labels, dataset versions, quotas, collection sessions, samples, sealed snapshots |
| Evaluation | Model/snapshot selection, evaluation jobs, progress, reports and cancellation |
| Models | Candidate registration, report import, approval, explicit deployment and rollback |
| Monitoring | Health, metadata, endpoint/backend/protocol and unavailable telemetry states |
| Activity | Scoped event filters, pagination and audit details |
| Integrations | API keys, scopes, webhooks, configuration, rotation, tests, delivery retries and logs |
| Accounts | Members, business-role changes, suspension, invitations, permission matrix and audit |
| Configuration | Workspace configuration, retention preview, collection policy, runtime defaults and personal notifications |

No worker or encryption configuration is fabricated. Deployment requires the
configured managed worker to be healthy; evaluation requires an available worker
for the model backend; webhooks require the configured encryption key and worker.
The current evaluation engine only supports ONNX. A disabled control with a
prerequisite error does not mean the operation was performed. Candidate
registration never deploys a model. Runtime endpoint selection is Dev/Test, not
model promotion. Retention is a read-only preview, not a deletion action.

Internal roles cannot be granted through invitations or member editing. Local
system and enterprise accounts have separate deterministic identities; switching
launch modes neither upgrades nor deletes the other account. Revoked accounts
are not silently repaired. Use `LOCAL_ADMIN_ENABLED=false` for session mode;
provision a system membership out of band under separate operational control.

## Read-Only Browser Verification

With both servers running and Playwright installed:

```sh
node tests/e2e/workspace_system_admin_live.mjs
```

If Playwright is installed outside this checkout, set `VSIGN_PLAYWRIGHT_FROM`
to its absolute `package.json` path. The smoke test uses installed Chrome,
blocks browser writes, checks ten views at six widths, and saves screenshots
and `report.json` under `tmp/system-admin-browser-20261018` by default.
Override output with `VSIGN_E2E_OUTPUT`. It does not activate the camera or
prove recognition quality, deployment readiness, or public-access security.
