# Shared local and public login on port 8000

The login screen mounts before the workspace when `AUTH_REQUIRED=true`.
The backend uses the existing Argon2 password hashes, HTTP-only session cookie,
login rate limit, origin checks and role permissions. Runtime HTTP operations
and the inference WebSocket also require a session in this mode. Health and
model metadata remain readable without login.

Short usernames resolve to `<username>@vsign.invalid` internally; the existing
email login still works. No new database column is required. Public signup is
not enabled. Existing accounts are never reset or promoted by provisioning.

## 1. Prepare the shared account

Run from the repository root:

```bash
PYTHONPATH=services/inference:. .venv/bin/python -m app.provision_admin \
  --database-url "sqlite:///$(pwd)/data/vsign-platform.db" \
  --username vsignadmin --initialize
```

For a new account, enter a strong password twice at the hidden prompts. The password
is not stored in source, frontend bundles, command arguments or documentation.
The explicit short-password exception applies only to this provisioning
command; normal bootstrap and invitation password requirements are unchanged.
Do not use a predictable temporary password for real public administration.

The shared runtime uses `data/vsign-platform.db`, preserving existing local
workspace and model records. The account has the `system_admin` role. Existing
accounts are never reset by this command. During the one-time migration from
port 8004, back up both databases and copy only the public account and its
membership if absent; keep `data/vsign-public.db` unchanged. Do not copy old
sessions or overwrite existing users. Sign in again after the migration.

## 2. Start the shared runtime

```bash
bash scripts/run_public_local.sh
```

This loads the existing model at `127.0.0.1:8000` for both local and public
clients. Stop the old passwordless process on 8000 before starting this launcher.
It does not switch a model pointer or enable a deployment worker. Collection and
Dev/Test remain off. The allowed browser origins are `https://vsign.io.vn` and
loopback frontend ports 5173-5176. Authentication is mandatory for both clients.
The shared database must already be provisioned and migrated.

For the local frontend, use `http://127.0.0.1:5174` with all backend URLs on
`127.0.0.1:8000`, including `ws://127.0.0.1:8000/ws/inference`. Keep the hostname
consistent; do not mix localhost and 127.0.0.1 for cookie-based sessions. Secure
cookies stay enabled; use a browser that accepts Secure cookies on trustworthy
loopback origins, or use HTTPS locally. Never disable Secure cookies for public use.

## 3. Configure the tunnel only after checking authentication

First, `GET http://127.0.0.1:8000/api/v1/auth/me` without cookies must return
401, not a local-admin identity. Health must return OK.

In Cloudflare, set:

| Field | Value |
| --- | --- |
| Subdomain | `api` |
| Domain | `vsign.io.vn` |
| Path | empty |
| Service URL | `http://127.0.0.1:8000` |

Only change the tunnel after port 8000 rejects anonymous users. Stop the retired
8004 runtime after verifying the public hostname. The legacy passwordless admin
launcher now defaults to port 8005 and refuses port 8000; never tunnel that launcher.

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

## 5. Update backend code

Test changes before restarting this shared runtime. Stop only its launcher,
then run `bash scripts/run_public_local.sh` again. Both local and public clients
are interrupted during the restart. Pushing Git does not restart this Mac backend.
Database migrations and model promotion still require their existing explicit
procedures; restarting does not perform either operation.
