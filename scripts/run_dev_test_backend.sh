#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export INFERENCE_HOST=127.0.0.1
export INFERENCE_PORT="${INFERENCE_PORT:-8002}"
web_port="${DEV_TEST_WEB_PORT:-5174}"
export APP_ENV=development
export DEV_TEST_ENABLED=true
export COLLECTION_ENABLED=false
export DEV_TEST_DIR="${DEV_TEST_DIR:-${project_dir}/ml/data/dev-tests/manual}"
export ALLOWED_ORIGINS="http://localhost:${web_port},http://127.0.0.1:${web_port}"

"${project_dir}/.venv/bin/python" - "${INFERENCE_PORT}" <<'PY'
import socket
import sys

with socket.socket() as handle:
    try:
        handle.bind(("127.0.0.1", int(sys.argv[1])))
    except (OSError, ValueError) as error:
        raise SystemExit(f"Backend test port is unavailable: {error}")
PY

exec bash "${project_dir}/scripts/run_coreml_local.sh"
