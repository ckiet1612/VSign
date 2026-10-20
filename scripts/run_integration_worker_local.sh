#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
key_file="${INTEGRATION_ENCRYPTION_KEY_FILE:-${HOME}/.config/vsign/integration-encryption.key}"
if [[ -z "${INTEGRATION_ENCRYPTION_KEY:-}" ]]; then
  if [[ ! -f "${key_file}" ]]; then
    echo "Chưa có khóa mã hóa webhook của máy chủ." >&2
    exit 1
  fi
  INTEGRATION_ENCRYPTION_KEY="$(<"${key_file}")"
  export INTEGRATION_ENCRYPTION_KEY
fi
export DATABASE_URL="${DATABASE_URL:-sqlite:///${project_dir}/data/vsign-platform.db}"
export PYTHONPATH="${project_dir}/services/inference:${project_dir}${PYTHONPATH:+:${PYTHONPATH}}"
cd "${project_dir}"
exec "${project_dir}/.venv/bin/python" -m app.integration_worker
