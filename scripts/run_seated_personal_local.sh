#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PERSONAL_MODEL_DIR="${SEATED_PERSONAL_MODEL_DIR:-${project_dir}/ml/artifacts/sales30_seated_personal_v1_r2}"
export COREML_MODEL_DIR="${SEATED_COREML_MODEL_DIR:-${project_dir}/ml/artifacts/sales30_seated_personal_coreml_fp32}"
export COREML_BENCHMARK_JSON="${SEATED_COREML_BENCHMARK_JSON:-${COREML_MODEL_DIR}/benchmark/benchmark.json}"
export INFERENCE_HOST=127.0.0.1
export INFERENCE_PORT="${INFERENCE_PORT:-8003}"
export APP_ENV=development
export DEV_TEST_ENABLED=true
export DEV_TEST_DIR="${DEV_TEST_DIR:-${project_dir}/ml/data/dev-tests/manual}"
export COLLECTION_ENABLED=false
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175}"
export PYTHONPATH="${project_dir}/services/inference:${project_dir}${PYTHONPATH:+:${PYTHONPATH}}"

"${project_dir}/.venv/bin/python" - "${PERSONAL_MODEL_DIR}" "${INFERENCE_PORT}" <<'PY'
import json
import re
import socket
import sys
from pathlib import Path
from ml.scripts.personal_coreml import verify_source

root = Path(sys.argv[1])
identity = verify_source(root)
summary = json.loads((root / "summary.json").read_text())
if (not re.fullmatch(r"sales30-mvitv2s-seated-personal-v1-head-epoch\d+", identity["model_version"])
        or summary.get("source_files_unchanged") is not True):
    raise SystemExit("Seated candidate identity/preservation gate failed; original runtime unchanged")
port = int(sys.argv[2])
if not 1 <= port <= 65535 or port in {8000, 8002}:
    raise SystemExit("Candidate must use its own port, not the existing model ports")
with socket.socket() as handle:
    handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    handle.bind(("127.0.0.1", port))
PY

exec bash "${project_dir}/scripts/run_coreml_local.sh"
