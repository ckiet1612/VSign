# Public login on the Mac

The login screen mounts before the workspace when `AUTH_REQUIRED=true`.
The backend uses the existing Argon2 password hashes, HTTP-only session cookie,
login rate limit, origin checks and role permissions. Runtime HTTP operations
and the inference WebSocket also require a session in this mode. Health and
model metadata remain readable without login.

Short usernames resolve to `<username>@vsign.invalid` internally; the existing
email login still works. No new database column is required. Public signup is
not enabled. Existing accounts are never reset or promoted by provisioning.

## 1. Create the dedicated account

Run from the repository root:

```bash
PYTHONPATH=services/inference:. .venv/bin/python -m app.provision_admin \
  --database-url "sqlite:///$(pwd)/data/vsign-public.db" \
  --username vsignadmin --initialize --allow-short-password
```

Enter the agreed temporary password twice at the hidden prompts. The password
is not stored in source, frontend bundles, command arguments or documentation.
The explicit short-password exception applies only to this provisioning
command; normal bootstrap and invitation password requirements are unchanged.
Do not use a predictable temporary password for real public administration.

The dedicated DB starts empty, with a `system_admin` account. It does not copy
local workspace records, sessions or data from `data/vsign-platform.db`.

## 2. Start the public runtime

```bash
bash scripts/run_public_local.sh
```

This loads the existing model in a separate process at `127.0.0.1:8004`.
It does not restart port 8000, switch a model pointer or enable a deployment
worker. It consumes additional model memory. Collection and Dev/Test are off.
The only browser origin allowed by this launcher is `https://vsign.io.vn`.
The public database must already be provisioned and migrated.

## 3. Configure the tunnel only after checking authentication

First, `GET http://127.0.0.1:8004/api/v1/auth/me` without cookies must return
401, not a local-admin identity. Health must return OK.

In Cloudflare, set:

| Field | Value |
| --- | --- |
| Subdomain | `api` |
| Domain | `vsign.io.vn` |
| Path | empty |
| Service URL | `http://127.0.0.1:8004` |

Never point the public tunnel at the passwordless local admin on port 8000.

## 4. Configure Vercel and redeploy

```text
VITE_PLATFORM_HTTP_URL=https://api.vsign.io.vn
VITE_INFERENCE_HTTP_URL=https://api.vsign.io.vn
VITE_INFERENCE_WS_URL=wss://api.vsign.io.vn/ws/inference
VITE_PLATFORM_AUTH_REQUIRED=true
```

Do not enable `VITE_PUBLIC_DEMO`; it deliberately skips the workspace login.
Use `https://vsign.io.vn` to log in: the unrelated `vercel.app` address is not
an allowed origin and is cross-site for the API's SameSite=Lax cookie.
All frontend variables are public; never add an admin password to Vercel.

Code changes must reach the branch Vercel builds before redeploying. Local
verification does not mean the public site has been updated. Keep the backend
and tunnel running, then test wrong password, correct login, reload, logout,
and anonymous API/WebSocket denial over the real HTTPS hostname.
