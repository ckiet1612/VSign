#!/usr/bin/env bash
set -euo pipefail

# Deploys the Modal GPU recognition runtime (Asia; L4/A10/T4/L40S/A100).
# The browser uses it while it is up and falls back to the Mac on port 8000 otherwise.
# Stop it with: .venv-modal/bin/modal app stop vsign-inference -y

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
modal_cli="${project_dir}/.venv-modal/bin/modal"
secret_file="${project_dir}/data/inference-token-secret"

if [[ ! -x "${modal_cli}" ]]; then
  echo "Thiếu Modal CLI: python3.12 -m venv .venv-modal && .venv-modal/bin/pip install modal python-dotenv" >&2
  exit 1
fi

# The Mac and Modal share this secret: the Mac signs inference tokens, Modal verifies them.
if [[ ! -f "${secret_file}" ]]; then
  mkdir -p "$(dirname "${secret_file}")"
  (umask 077 && python3 -c "import secrets; print(secrets.token_urlsafe(48))" > "${secret_file}")
  echo "Đã tạo ${secret_file}; khởi động lại service port 8000 theo docs/MODAL_GPU.md để Mac cấp token."
fi
dotenv="$(mktemp)"
trap 'rm -f "${dotenv}"' EXIT
chmod 600 "${dotenv}"
printf 'INFERENCE_TOKEN_SECRET=%s\n' "$(tr -d '\n' < "${secret_file}")" > "${dotenv}"
"${modal_cli}" secret create vsign-inference-token --from-dotenv "${dotenv}" --force >/dev/null

cd "${project_dir}"
"${modal_cli}" deploy deploy/modal_app.py

# Without a session the Mac answers 401 when it can issue tokens, 404 when it lacks the secret.
if [[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/api/v1/inference/token)" == 404 ]]; then
  echo "Cảnh báo: port 8000 chưa cấp inference token; khởi động lại service theo docs/MODAL_GPU.md." >&2
fi
