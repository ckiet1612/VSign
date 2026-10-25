#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_dir="${PERSONAL_MODEL_DIR:-${project_dir}/ml/artifacts/sales30_personal_v3_bodycrop_curated}"
python_path="${project_dir}/.venv/bin/python"

if [[ ! -x "${python_path}" || ! -f "${model_dir}/best.pt" ]]; then
  echo "Thiếu Python runtime hoặc checkpoint personal đã fine-tune." >&2
  exit 1
fi
model_dir="$(cd "${model_dir}" && pwd -P)"

verified="$("${python_path}" - "${model_dir}" "${project_dir}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
project = Path(sys.argv[2])
summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
labels = json.loads((root / "labels.json").read_text(encoding="utf-8"))
expected_labels = json.loads((project / "contracts/v1/sales30.labels.json").read_text(encoding="utf-8"))
if not summary.get("deployment_gate_passed"):
    raise SystemExit("Candidate không đạt gate hồi quy; dùng lại seated-v3.")
if labels != expected_labels + ["Không ký hiệu"]:
    raise SystemExit("Label map không đúng candidate 31 lớp.")
digest = hashlib.sha256((root / "best.pt").read_bytes()).hexdigest()
if digest != summary["best_sha256"]:
    raise SystemExit("Checkpoint không khớp SHA256 đã xác minh.")
framing = summary.get("input_framing", "center-square")
if framing not in {"center-square", "trim-bodycrop-v1"}:
    raise SystemExit("Checkpoint khai báo input_framing không hợp lệ.")
print(summary["model_version"] + "\t" + framing)
PY
)"
IFS=$'\t' read -r verified_version input_framing <<< "${verified}"

export INFERENCE_BACKEND=pytorch
export MODEL_VERSION="${verified_version}"
# The checkpoint was trained on this framing; the web client must send the same.
export INPUT_FRAMING="${input_framing}"
if [[ -f "${model_dir}/calibration.json" ]]; then
  export DECISION_POLICY_PATH="${model_dir}/calibration.json"
fi
export PYTORCH_MODEL_PATH="${model_dir}/best.pt"
export LABEL_MAP_PATH="${model_dir}/labels.json"
export PYTORCH_DEVICE="${PYTORCH_DEVICE:-cpu}"
export LABELS_VERIFIED=true
# Keep runtime acceptance identical to the measured regression gate.
export CONFIDENCE_THRESHOLD=0.40
export MARGIN_THRESHOLD=0.0
# Or a lead of 15 points over the second word, even below 40%.
export LEAD_THRESHOLD=0.15
export COLLECTION_ENABLED="${COLLECTION_ENABLED:-true}"
export COLLECTION_DIR="${COLLECTION_DIR:-${project_dir}/ml/data/collected/sales30}"
# Fresh-process Mac CPU benchmark: 8 threads had the best median and tail.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-8}"
if [[ ! "${OMP_NUM_THREADS}" =~ ^([1-9]|[1-5][0-9]|6[0-4])$ ]]; then
  echo "OMP_NUM_THREADS phải là số nguyên từ 1 đến 64." >&2
  exit 1
fi
export PYTHONPATH="${project_dir}/services/inference:${project_dir}${PYTHONPATH:+:${PYTHONPATH}}"

cd "${project_dir}"
exec "${project_dir}/.venv/bin/uvicorn" app.main:app \
  --host "${INFERENCE_HOST:-127.0.0.1}" --port "${INFERENCE_PORT:-8000}"
