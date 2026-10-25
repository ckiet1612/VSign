"""Modal GPU runtime for recognition (/health, /metadata, /ws/inference only).

It serves the same checkpoint as the Mac (PyTorch on CUDA instead of Core ML) and accepts
the signed inference tokens the Mac issues. Deploy with scripts/deploy_modal.sh.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import modal

APP_NAME = "vsign-inference"
SECRET_NAME = "vsign-inference-token"
REMOTE_ROOT = "/root/vsign"
REMOTE_MODEL_DIR = f"{REMOTE_ROOT}/model"
MODEL_FILES = ("best.pt", "labels.json", "calibration.json", "summary.json")
DEFAULT_ORIGINS = (
    "https://vsign.io.vn,http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,"
    "http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175,http://localhost:5176,"
    "http://127.0.0.1:5176"
)

project_dir = Path(__file__).resolve().parents[1]
model_dir = Path(os.getenv(
    "PERSONAL_MODEL_DIR", project_dir / "ml/artifacts/sales30_personal_v3_bodycrop_curated"
)).expanduser()


def verified_model() -> tuple[str, str]:
    """(model_version, input_framing) after the same checks as scripts/run_personal_local.sh."""
    summary = json.loads((model_dir / "summary.json").read_text(encoding="utf-8"))
    labels = json.loads((model_dir / "labels.json").read_text(encoding="utf-8"))
    expected = json.loads((project_dir / "contracts/v1/sales30.labels.json").read_text(encoding="utf-8"))
    if not summary.get("deployment_gate_passed"):
        raise SystemExit("Candidate không đạt gate hồi quy.")
    if labels != expected + ["Không ký hiệu"]:
        raise SystemExit("Label map không đúng candidate 31 lớp.")
    if hashlib.sha256((model_dir / "best.pt").read_bytes()).hexdigest() != summary["best_sha256"]:
        raise SystemExit("Checkpoint không khớp SHA256 đã xác minh.")
    framing = summary.get("input_framing", "center-square")
    if framing not in {"center-square", "trim-bodycrop-v1"}:
        raise SystemExit("Checkpoint khai báo input_framing không hợp lệ.")
    return summary["model_version"], framing


runtime_env = {"PYTHONPATH": f"{REMOTE_ROOT}/services/inference:{REMOTE_ROOT}"}
if modal.is_local():
    model_version, input_framing = verified_model()
    runtime_env.update({
        "APP_ENV": "production",
        "RUNTIME_ROLE": "inference_only",
        "INFERENCE_BACKEND": "pytorch",
        "PYTORCH_DEVICE": "cuda",
        "PYTORCH_MODEL_PATH": f"{REMOTE_MODEL_DIR}/best.pt",
        "LABEL_MAP_PATH": f"{REMOTE_MODEL_DIR}/labels.json",
        "DECISION_POLICY_PATH": f"{REMOTE_MODEL_DIR}/calibration.json",
        # Must equal the Mac's version, or the browser keeps recognition on the Mac.
        "MODEL_VERSION": model_version,
        "INPUT_FRAMING": input_framing,
        "LABELS_VERIFIED": "true",
        "CONFIDENCE_THRESHOLD": "0.40",
        "MARGIN_THRESHOLD": "0.0",
        # Or a lead of 15 points over the second word, even below 40%.
        "LEAD_THRESHOLD": "0.15",
        "ALLOWED_ORIGINS": os.getenv("MODAL_ALLOWED_ORIGINS", DEFAULT_ORIGINS),
        "WORKSPACE_ID": os.getenv("WORKSPACE_ID", "local"),
        "DATABASE_URL": "sqlite:///:memory:",
        "COLLECTION_ENABLED": "false",
    })

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements(str(project_dir / "services/inference/requirements.txt"))
    # Same torch/torchvision release as the Mac checkpoint tooling, built for CUDA 11.8 (L4 support).
    # The PyTorch wheel does not reliably pull NVRTC when the index URL is restricted to
    # the CUDA wheel index, but cuDNN loads it during CUDA model initialization.
    .pip_install(
        "torch==2.0.0",
        "torchvision==0.15.1",
        "nvidia-cuda-nvrtc-cu11==11.7.99",
        index_url="https://download.pytorch.org/whl/cu118",
        extra_index_url="https://pypi.org/simple",
    )
    .env({
        "LD_LIBRARY_PATH": (
            "/usr/local/lib/python3.11/site-packages/nvidia/cuda_nvrtc/lib:"
            "/usr/local/lib/python3.11/site-packages/torch/lib"
        ),
    })
    .run_commands(
        "nvrtc_lib=$(find /usr/local/lib/python3.11/site-packages/nvidia/cuda_nvrtc/lib "
        "-maxdepth 1 -type f -name 'libnvrtc.so.*' -print -quit) && "
        "test -n \"$nvrtc_lib\" && ln -sf \"$nvrtc_lib\" "
        "/usr/local/lib/python3.11/site-packages/nvidia/cuda_nvrtc/lib/libnvrtc.so"
    )
    .env(runtime_env)
    .add_local_dir(project_dir / "services/inference/app", f"{REMOTE_ROOT}/services/inference/app",
                   ignore=["**/__pycache__"])
    .add_local_dir(project_dir / "contracts", f"{REMOTE_ROOT}/contracts", ignore=["**/__pycache__"])
)
for name in MODEL_FILES:
    image = image.add_local_file(model_dir / name, f"{REMOTE_MODEL_DIR}/{name}")

app = modal.App(APP_NAME)


@app.function(
    image=image,
    gpu=["L4", "A10", "T4", "L40S", "A100-40GB", "A100-80GB"],
    cpu=4.0,
    memory=16384,
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    # One container owns the GPU; it sleeps after 5 idle minutes and wakes on the next request.
    max_containers=1,
    scaledown_window=300,
    # Each WebSocket is one call; the browser reconnects after this.
    timeout=3600,
    region=os.getenv("MODAL_REGION") or "ap",
    # Routing regions are immutable per Function; use a new Function for Asia.
    routing_region="ap-south",
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def inference_ap_southeast():
    import torch

    print(f"VSign CUDA device: {torch.cuda.get_device_name(0)}", flush=True)
    # app.main builds the app at import; reuse it so the model loads once.
    from app.main import app as runtime

    return runtime
