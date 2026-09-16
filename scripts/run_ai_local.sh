#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
checkpoint_path="${PYTORCH_MODEL_PATH:-${project_dir}/ml/artifacts/source/mvitv2_s_multivsl1000.pth}"
label_path="${LABEL_MAP_PATH:-${project_dir}/ml/artifacts/source/multivsl1000_class_ids.json}"
python_path="${project_dir}/.venv/bin/python"
uvicorn_path="${project_dir}/.venv/bin/uvicorn"

if [[ ! -x "${python_path}" || ! -x "${uvicorn_path}" ]]; then
  echo "Thiếu .venv. Chạy: python3 -m venv .venv && .venv/bin/pip install -e 'services/inference[pytorch,test]'" >&2
  exit 1
fi
if [[ ! -f "${checkpoint_path}" ]]; then
  echo "Không tìm thấy checkpoint: ${checkpoint_path}" >&2
  exit 1
fi
if [[ ! -f "${label_path}" ]]; then
  "${python_path}" -m ml.scripts.generate_class_id_labels "${label_path}" --class-count 1000
fi

export INFERENCE_BACKEND=pytorch
export MODEL_VERSION="${MODEL_VERSION:-multivsl1000-mvitv2s-official-class-id-v1}"
export PYTORCH_MODEL_PATH="${checkpoint_path}"
export PYTORCH_DEVICE="${PYTORCH_DEVICE:-cpu}"
export LABEL_MAP_PATH="${label_path}"
export LABELS_VERIFIED="${LABELS_VERIFIED:-false}"
export CONFIDENCE_THRESHOLD="${CONFIDENCE_THRESHOLD:-0.70}"
export MARGIN_THRESHOLD="${MARGIN_THRESHOLD:-0.15}"
export PYTHONPATH="${project_dir}/services/inference:${project_dir}${PYTHONPATH:+:${PYTHONPATH}}"

cd "${project_dir}"
exec "${uvicorn_path}" app.main:app \
  --host "${INFERENCE_HOST:-127.0.0.1}" \
  --port "${INFERENCE_PORT:-8000}"
