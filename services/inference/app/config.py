from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} phải là một số") from exc
    if not 0 <= parsed <= 1:
        raise RuntimeError(f"{name} phải nằm trong khoảng 0..1")
    return parsed


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} phải là số nguyên") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} phải lớn hơn 0")
    return parsed


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} phải là true hoặc false")


@dataclass(frozen=True)
class Settings:
    inference_backend: str = "mock"
    model_version: str = "mock-common-20-v1"
    onnx_model_path: Optional[Path] = None
    pytorch_model_path: Optional[Path] = None
    pytorch_device: str = "auto"
    label_map_path: Optional[Path] = None
    labels_verified: bool = False
    confidence_threshold: float = 0.70
    margin_threshold: float = 0.15
    allowed_origins: Tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
    )
    max_frame_bytes: int = 256 * 1024
    max_message_bytes: int = 6 * 1024 * 1024
    collection_enabled: bool = False
    collection_dir: Path = Path("ml/data/collected/webcam")
    collection_target_per_hand: int = 5

    @classmethod
    def from_env(cls) -> "Settings":
        backend = os.getenv("INFERENCE_BACKEND", "mock").strip().lower()
        if backend not in {"mock", "onnx", "pytorch"}:
            raise RuntimeError(
                "INFERENCE_BACKEND chỉ hỗ trợ 'mock', 'onnx' hoặc 'pytorch'"
            )

        model_path = os.getenv("ONNX_MODEL_PATH", "").strip()
        pytorch_model_path = os.getenv("PYTORCH_MODEL_PATH", "").strip()
        pytorch_device = os.getenv("PYTORCH_DEVICE", "auto").strip().lower()
        if pytorch_device not in {"auto", "cpu", "cuda"}:
            raise RuntimeError("PYTORCH_DEVICE chỉ hỗ trợ auto, cpu hoặc cuda")
        label_path = os.getenv("LABEL_MAP_PATH", "").strip()
        origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "ALLOWED_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080",
            ).split(",")
            if origin.strip()
        )
        if not origins:
            raise RuntimeError("ALLOWED_ORIGINS không được để trống")

        default_versions = {
            "mock": "mock-common-20-v1",
            "onnx": "onnx-v1",
            "pytorch": "multivsl-mvitv2-s-1000-official",
        }
        default_version = default_versions[backend]
        return cls(
            inference_backend=backend,
            model_version=os.getenv("MODEL_VERSION", default_version).strip() or default_version,
            onnx_model_path=Path(model_path).expanduser() if model_path else None,
            pytorch_model_path=(
                Path(pytorch_model_path).expanduser() if pytorch_model_path else None
            ),
            pytorch_device=pytorch_device,
            label_map_path=Path(label_path).expanduser() if label_path else None,
            labels_verified=_bool_env("LABELS_VERIFIED", False),
            confidence_threshold=_float_env("CONFIDENCE_THRESHOLD", 0.70),
            margin_threshold=_float_env("MARGIN_THRESHOLD", 0.15),
            allowed_origins=origins,
            max_frame_bytes=_int_env("MAX_FRAME_BYTES", 256 * 1024),
            max_message_bytes=_int_env("MAX_MESSAGE_BYTES", 6 * 1024 * 1024),
            collection_enabled=_bool_env("COLLECTION_ENABLED", False),
            collection_dir=Path(
                os.getenv("COLLECTION_DIR", "ml/data/collected/webcam")
            ).expanduser(),
            collection_target_per_hand=_int_env("COLLECTION_TARGET_PER_HAND", 5),
        )
