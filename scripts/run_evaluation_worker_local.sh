#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend="${1:-}"
case "${backend}" in
  onnx|pytorch) python_path="${project_dir}/.venv/bin/python" ;;
  coreml) python_path="${project_dir}/.venv-coreml/bin/python" ;;
  *) echo "Dùng: bash scripts/run_evaluation_worker_local.sh onnx|coreml|pytorch" >&2; exit 1 ;;
esac
if [[ ! -x "${python_path}" ]]; then
  echo "Thiếu môi trường Python cho worker ${backend}." >&2
  exit 1
fi
export DATABASE_URL="${DATABASE_URL:-sqlite:///${project_dir}/data/vsign-platform.db}"
export MODEL_REGISTRY_ROOTS="${MODEL_REGISTRY_ROOTS:-${project_dir}/ml/artifacts}"
export MODEL_EVALUATION_ROOTS="${MODEL_EVALUATION_ROOTS:-${project_dir}/ml/evaluations}"
export COLLECTION_DIR="${COLLECTION_DIR:-${project_dir}/ml/data/collected/sales30}"
export PYTHONPATH="${project_dir}/services/inference:${project_dir}${PYTHONPATH:+:${PYTHONPATH}}"
cd "${project_dir}"
exec "${python_path}" -m app.evaluation_worker --backend "${backend}"
