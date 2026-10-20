#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
public_database="sqlite:///${project_dir}/data/vsign-public.db"
reject() { echo "Public runtime: $*" >&2; exit 1; }
[[ "${INFERENCE_PORT:-8004}" == 8004 ]] || reject "use port 8004, never local port 8000."
[[ "${INFERENCE_HOST:-127.0.0.1}" == 127.0.0.1 ]] || reject "bind to 127.0.0.1 behind the tunnel."
[[ "${DATABASE_URL:-${public_database}}" == "${public_database}" ]] || reject "use the dedicated public database."
[[ "${LOCAL_ADMIN_ENABLED:-false}" == false ]] || reject "passwordless admin must be disabled."
[[ "${AUTH_REQUIRED:-true}" == true ]] || reject "authentication must be required."
[[ "${AUTH_COOKIE_SECURE:-true}" == true ]] || reject "secure cookies are required for the HTTPS tunnel."
[[ -f "${project_dir}/data/vsign-public.db" ]] || reject "provision the public account first; see docs/PUBLIC_LOGIN.md."
if lsof -nP -iTCP:8004 -sTCP:LISTEN >/dev/null 2>&1; then
  reject "port 8004 is already in use; do not start a duplicate."
fi

export APP_ENV=production AUTH_REQUIRED=true LOCAL_ADMIN_ENABLED=false AUTH_COOKIE_SECURE=true
export INFERENCE_HOST=127.0.0.1 INFERENCE_PORT=8004 DATABASE_URL="${public_database}"
export DATABASE_AUTO_CREATE=false MODEL_DEPLOYMENT_WORKER=false COLLECTION_ENABLED=false DEV_TEST_ENABLED=false
export ALLOWED_ORIGINS="https://vsign.io.vn"
unset BOOTSTRAP_ADMIN_EMAIL BOOTSTRAP_ADMIN_PASSWORD BOOTSTRAP_ADMIN_NAME
exec bash "${project_dir}/scripts/run_coreml_local.sh"
