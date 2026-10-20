#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export INFERENCE_HOST="${INFERENCE_HOST:-127.0.0.1}"
case "${INFERENCE_HOST}" in
  127.0.0.1|::1) ;;
  *) echo "Passwordless system admin requires a loopback IP (127.0.0.1 or ::1)." >&2; exit 1 ;;
esac
export APP_ENV="${APP_ENV:-development}"
export AUTH_REQUIRED="${AUTH_REQUIRED:-false}"
export AUTH_COOKIE_SECURE="${AUTH_COOKIE_SECURE:-false}"
export LOCAL_ADMIN_ENABLED=true
export LOCAL_ADMIN_ROLE=system_admin
export INFERENCE_PORT="${INFERENCE_PORT:-8000}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///${project_dir}/data/vsign-platform.db}"
export DATABASE_AUTO_CREATE="${DATABASE_AUTO_CREATE:-false}"
exec bash "${project_dir}/scripts/run_coreml_local.sh"
