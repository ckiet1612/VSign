#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_dir="${project_dir}/ml/artifacts/visignlanguage_common20"
model_path="${ONNX_MODEL_PATH:-${model_dir}/model.onnx}"
label_path="${LABEL_MAP_PATH:-${model_dir}/labels.json}"
python_path="${project_dir}/.venv/bin/python"
uvicorn_path="${project_dir}/.venv/bin/uvicorn"

if [[ ! -x "${python_path}" || ! -x "${uvicorn_path}" ]]; then
  echo "Thiếu .venv. Chạy: python3 -m venv .venv && .venv/bin/pip install -e 'services/inference[onnx,test]'" >&2
  exit 1
fi
if [[ ! -f "${model_path}" ]]; then
  echo "Không tìm thấy ONNX model: ${model_path}" >&2
  exit 1
fi
if [[ ! -f "${model_path}.data" ]]; then
  echo "Không tìm thấy trọng số ONNX đi kèm: ${model_path}.data" >&2
  exit 1
fi
if [[ ! -f "${label_path}" ]]; then
  echo "Không tìm thấy label map: ${label_path}" >&2
  exit 1
fi
if ! "${python_path}" -c 'import onnxruntime' >/dev/null 2>&1; then
  echo "Thiếu onnxruntime. Chạy: .venv/bin/pip install -e 'services/inference[onnx,test]'" >&2
  exit 1
fi

export INFERENCE_BACKEND=onnx
export MODEL_VERSION="${MODEL_VERSION:-visignlanguage-common20-mvitv2s-epoch5}"
export ONNX_MODEL_PATH="${model_path}"
export LABEL_MAP_PATH="${label_path}"
export LABELS_VERIFIED="${LABELS_VERIFIED:-true}"
export CONFIDENCE_THRESHOLD="${CONFIDENCE_THRESHOLD:-0.70}"
export MARGIN_THRESHOLD="${MARGIN_THRESHOLD:-0.15}"
export COLLECTION_ENABLED="${COLLECTION_ENABLED:-true}"
export COLLECTION_DIR="${COLLECTION_DIR:-${project_dir}/ml/data/collected/webcam}"
export COLLECTION_TARGET_PER_HAND="${COLLECTION_TARGET_PER_HAND:-5}"
export PYTHONPATH="${project_dir}/services/inference:${project_dir}${PYTHONPATH:+:${PYTHONPATH}}"

cd "${project_dir}"
exec "${uvicorn_path}" app.main:app \
  --host "${INFERENCE_HOST:-127.0.0.1}" \
  --port "${INFERENCE_PORT:-8000}"
