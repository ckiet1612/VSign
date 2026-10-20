#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${INFERENCE_PORT:-8002}"
export VITE_PUBLIC_DEMO=false
export VITE_INFERENCE_HTTP_URL="http://127.0.0.1:${port}"
export VITE_INFERENCE_WS_URL="ws://127.0.0.1:${port}/ws/inference"
cd "${project_dir}/apps/web"
exec npm run dev -- --host 127.0.0.1 --port "${DEV_TEST_WEB_PORT:-5174}" --strictPort
