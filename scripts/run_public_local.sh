#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
shared_database="sqlite:///${project_dir}/data/vsign-platform.db"
reject() { echo "Public runtime: $*" >&2; exit 1; }
[[ "${INFERENCE_PORT:-8000}" == 8000 ]] || reject "use shared port 8000."
[[ "${INFERENCE_HOST:-127.0.0.1}" == 127.0.0.1 ]] || reject "bind to 127.0.0.1 behind the tunnel."
[[ "${DATABASE_URL:-${shared_database}}" == "${shared_database}" ]] || reject "use the shared platform database."
[[ "${LOCAL_ADMIN_ENABLED:-false}" == false ]] || reject "passwordless admin must be disabled."
[[ "${AUTH_REQUIRED:-true}" == true ]] || reject "authentication must be required."
[[ "${AUTH_COOKIE_SECURE:-true}" == true ]] || reject "secure cookies are required for the HTTPS tunnel."
[[ -f "${project_dir}/data/vsign-platform.db" ]] || reject "provision the shared account first; see docs/PUBLIC_LOGIN.md."
if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  reject "port 8000 is already in use; do not start a duplicate."
fi

export APP_ENV=production AUTH_REQUIRED=true LOCAL_ADMIN_ENABLED=false AUTH_COOKIE_SECURE=true
export INFERENCE_HOST=127.0.0.1 INFERENCE_PORT=8000 DATABASE_URL="${shared_database}"
export DATABASE_AUTO_CREATE=false MODEL_DEPLOYMENT_WORKER=false COLLECTION_ENABLED=false DEV_TEST_ENABLED=false
export ALLOWED_ORIGINS="https://vsign.io.vn,http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175,http://localhost:5176,http://127.0.0.1:5176"
unset BOOTSTRAP_ADMIN_EMAIL BOOTSTRAP_ADMIN_PASSWORD BOOTSTRAP_ADMIN_NAME
exec bash "${project_dir}/scripts/run_coreml_local.sh"
