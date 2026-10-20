#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${INFERENCE_PORT:-8002}" != "8002" ]]; then
  echo "Managed production local chỉ chạy ở port 8002; không thay đổi runtime thử nghiệm." >&2
  exit 1
fi
export MODEL_DEPLOYMENT_WORKER=true
export MODEL_DEPLOYMENT_TARGET="${MODEL_DEPLOYMENT_TARGET:-production-local}"
export MODEL_DEPLOYMENT_RUNTIME_URL="${MODEL_DEPLOYMENT_RUNTIME_URL:-http://127.0.0.1:8002}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///${project_dir}/data/vsign-platform.db}"
export DATABASE_AUTO_CREATE="${DATABASE_AUTO_CREATE:-false}"
export MODEL_REGISTRY_ROOTS="${MODEL_REGISTRY_ROOTS:-${project_dir}/ml/artifacts}"
export MODEL_EVALUATION_ROOTS="${MODEL_EVALUATION_ROOTS:-${project_dir}/ml/evaluations}"
export APP_ENV="${APP_ENV:-development}"
export AUTH_REQUIRED="${AUTH_REQUIRED:-false}"
export AUTH_COOKIE_SECURE="${AUTH_COOKIE_SECURE:-false}"
export COLLECTION_ENABLED="${COLLECTION_ENABLED:-false}"
export INFERENCE_HOST="${INFERENCE_HOST:-127.0.0.1}"
export INFERENCE_PORT=8002
if [[ -f "${HOME}/.config/vsign/integration-encryption.key" ]]; then
  export INTEGRATION_ENCRYPTION_KEY_FILE="${INTEGRATION_ENCRYPTION_KEY_FILE:-${HOME}/.config/vsign/integration-encryption.key}"
fi
exec bash "${project_dir}/scripts/run_coreml_local.sh"
