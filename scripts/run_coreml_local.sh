#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${PERSONAL_MODEL_DIR:-${project_dir}/ml/artifacts/sales30_personal_v3_bodycrop_curated}"
model_dir="${COREML_MODEL_DIR:-${project_dir}/ml/artifacts/sales30_personal_v3_bodycrop_curated_coreml_fp16}"
benchmark_path="${COREML_BENCHMARK_JSON:-${model_dir}/benchmark_r2/benchmark.json}"
python_path="${project_dir}/.venv/bin/python"
uvicorn_path="${project_dir}/.venv-coreml/bin/uvicorn"

fallback() {
  case "${MODEL_DEPLOYMENT_WORKER:-false}" in
    [Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss]|[Oo][Nn])
      echo "Managed runtime không được fallback: giữ active pointer và kiểm tra lỗi khởi động." >&2
      exit 1
      ;;
  esac
  echo "Core ML chưa đạt gate hoặc runtime lỗi; dùng PyTorch của checkpoint được chọn." >&2
  exec bash "${project_dir}/scripts/run_personal_local.sh"
}

if [[ ! -x "${python_path}" || ! -x "${uvicorn_path}" ]]; then
  fallback
fi
export PYTHONPATH="${project_dir}/services/inference:${project_dir}${PYTHONPATH:+:${PYTHONPATH}}"

if ! verified="$("${python_path}" - "${source_dir}" "${model_dir}" "${benchmark_path}" <<'PY'
import json
import sys
from pathlib import Path
from ml.scripts.personal_coreml import verify_deployment

version, units = verify_deployment(*(Path(argument) for argument in sys.argv[1:]))
framing = json.loads((Path(sys.argv[1]) / "summary.json").read_text(encoding="utf-8")).get("input_framing", "center-square")
if framing not in {"center-square", "trim-bodycrop-v1"}:
    raise SystemExit("Checkpoint khai báo input_framing không hợp lệ.")
print(version + "\t" + units + "\t" + framing)
PY
)"; then
  fallback
fi
IFS=$'\t' read -r version units input_framing <<< "${verified}"
model_dir="$(cd "${model_dir}" && pwd -P)"
export INFERENCE_BACKEND=coreml
export MODEL_VERSION="${version}"
export INPUT_FRAMING="${input_framing}"
# Per-word/context decision policy fitted for this checkpoint; the runtime rejects a mismatched file.
if [[ -f "${source_dir}/calibration.json" ]]; then
  export DECISION_POLICY_PATH="${source_dir}/calibration.json"
fi
export COREML_MODEL_PATH="${model_dir}/model.mlpackage"
export COREML_COMPUTE_UNITS="${units}"
export LABEL_MAP_PATH="${model_dir}/labels.json"
export LABELS_VERIFIED=true
export CONFIDENCE_THRESHOLD=0.40
export MARGIN_THRESHOLD=0.0
export COLLECTION_ENABLED="${COLLECTION_ENABLED:-true}"
export COLLECTION_DIR="${COLLECTION_DIR:-${project_dir}/ml/data/collected/sales30}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-8}"

cd "${project_dir}"
child_pid=""
stop_requested=false
forward_stop() {
  stop_requested=true
  if [[ -n "${child_pid}" ]]; then
    kill -s "$1" "${child_pid}" 2>/dev/null || true
  fi
}
# Background commands can inherit ignored SIGINT before Uvicorn installs handlers.
trap 'forward_stop TERM' INT
trap 'forward_stop TERM' TERM
set +e
"${uvicorn_path}" app.main:app --host "${INFERENCE_HOST:-127.0.0.1}" --port "${INFERENCE_PORT:-8000}" &
child_pid=$!
if [[ "${stop_requested}" == true ]]; then
  kill -TERM "${child_pid}" 2>/dev/null || true
fi
wait "${child_pid}"
status=$?
if [[ "${stop_requested}" == true ]]; then
  # Repeated trapped signals can interrupt each wait; reap before exiting.
  while kill -0 "${child_pid}" 2>/dev/null; do
    wait "${child_pid}" 2>/dev/null
  done
  exit 0
fi
trap - INT TERM
set -e
if [[ "${status}" -ne 0 && "${status}" -ne 130 && "${status}" -ne 143 ]]; then
  fallback
fi
exit "${status}"
