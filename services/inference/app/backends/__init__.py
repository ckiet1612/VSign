from __future__ import annotations

from app.backends.base import InferenceBackend
from app.backends.mock import MockInferenceBackend
from app.backends.onnx import ONNXInferenceBackend
from app.backends.pytorch import PyTorchInferenceBackend
from app.backends.coreml import CoreMLInferenceBackend
from app.config import Settings


def create_backend(settings: Settings) -> InferenceBackend:
    if settings.inference_backend == "mock":
        return MockInferenceBackend(settings.model_version)
    if settings.inference_backend == "coreml":
        if settings.coreml_model_path is None:
            raise RuntimeError("COREML_MODEL_PATH là bắt buộc khi INFERENCE_BACKEND=coreml")
        if settings.label_map_path is None:
            raise RuntimeError("LABEL_MAP_PATH là bắt buộc khi INFERENCE_BACKEND=coreml")
        return CoreMLInferenceBackend(
            model_path=settings.coreml_model_path, label_map_path=settings.label_map_path,
            model_version=settings.model_version, confidence_threshold=settings.confidence_threshold,
            margin_threshold=settings.margin_threshold, compute_units=settings.coreml_compute_units,
            labels_verified=settings.labels_verified,
        )
    if settings.inference_backend == "pytorch":
        if settings.pytorch_model_path is None:
            raise RuntimeError(
                "PYTORCH_MODEL_PATH là bắt buộc khi INFERENCE_BACKEND=pytorch"
            )
        if settings.label_map_path is None:
            raise RuntimeError(
                "LABEL_MAP_PATH là bắt buộc khi INFERENCE_BACKEND=pytorch"
            )
        return PyTorchInferenceBackend(
            model_path=settings.pytorch_model_path,
            label_map_path=settings.label_map_path,
            model_version=settings.model_version,
            confidence_threshold=settings.confidence_threshold,
            margin_threshold=settings.margin_threshold,
            device=settings.pytorch_device,
            labels_verified=settings.labels_verified,
        )
    if settings.onnx_model_path is None:
        raise RuntimeError("ONNX_MODEL_PATH là bắt buộc khi INFERENCE_BACKEND=onnx")
    if settings.label_map_path is None:
        raise RuntimeError("LABEL_MAP_PATH là bắt buộc khi INFERENCE_BACKEND=onnx")
    return ONNXInferenceBackend(
        model_path=settings.onnx_model_path,
        label_map_path=settings.label_map_path,
        model_version=settings.model_version,
        confidence_threshold=settings.confidence_threshold,
        margin_threshold=settings.margin_threshold,
        labels_verified=settings.labels_verified,
    )


__all__ = [
    "InferenceBackend",
    "MockInferenceBackend",
    "ONNXInferenceBackend",
    "PyTorchInferenceBackend",
    "CoreMLInferenceBackend",
    "create_backend",
]
