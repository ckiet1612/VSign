from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Sequence

import numpy as np

from app.backends.base import BackendCandidate, BackendPrediction, DecodedFrame
from app.backends.coreml_artifact import package_hash
from app.backends.labels import load_labels
from app.backends.pytorch import PyTorchInferenceBackend
from app.models import PredictionStatus


class CoreMLInferenceBackend:
    name = "coreml"
    is_mock = False

    def __init__(self, model_path: Path, label_map_path: Path, model_version: str,
                 confidence_threshold: float, margin_threshold: float,
                 compute_units: str = "ALL", labels_verified: bool = False) -> None:
        self.labels = load_labels(label_map_path)
        self.model_version = model_version
        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold
        self.candidate_labels_unverified = not labels_verified
        conversion = json.loads((model_path.parent / "conversion.json").read_text(encoding="utf-8"))
        if (conversion.get("passed") is not True or conversion.get("source_unchanged") is not True
                or conversion["source"]["model_version"] != model_version
                or conversion["source"]["labels"] != self.labels
                or conversion.get("package_sha256") != package_hash(model_path)):
            raise RuntimeError("Core ML artifact không khớp bản chuyển đổi đã xác minh")
        if compute_units not in {"ALL", "CPU_ONLY", "CPU_AND_GPU", "CPU_AND_NE"}:
            raise RuntimeError("COREML_COMPUTE_UNITS không hợp lệ")
        try:
            import coremltools as ct
        except ImportError as error:
            raise RuntimeError("Thiếu Core ML runtime; dùng .venv-coreml hoặc quay về PyTorch") from error
        self._model = ct.models.MLModel(str(model_path), compute_units=getattr(ct.ComputeUnit, compute_units))
        specification = self._model.get_spec().description
        if (len(specification.input) != 1 or specification.input[0].name != "frames"
                or list(specification.input[0].type.multiArrayType.shape) != [1, 3, 16, 224, 224]
                or len(specification.output) != 1 or specification.output[0].name != "logits"):
            raise RuntimeError("Core ML input/output không đúng hợp đồng 16x224")
        self.last_timings_ms: dict[str, float] = {}
        self._postprocess(self._model.predict({"frames": np.zeros((1, 3, 16, 224, 224), dtype=np.float32)})["logits"])

    def _preprocess(self, frames: Sequence[DecodedFrame]) -> np.ndarray:
        # Keep inputs byte-identical to the accepted PyTorch normalization.
        return PyTorchInferenceBackend._preprocess(self, frames)

    def _postprocess(self, logits: np.ndarray) -> BackendPrediction:
        values = np.asarray(logits, dtype=np.float32)
        if values.shape != (1, len(self.labels)) or not np.isfinite(values).all():
            raise RuntimeError("Core ML output shape hoặc logits không hợp lệ")
        exponentials = np.exp(values[0] - np.max(values[0]))
        probabilities = exponentials / exponentials.sum()
        indices = np.argsort(probabilities)[::-1]
        winner = int(indices[0])
        top_k = [BackendCandidate(self.labels[int(index)], float(probabilities[index]))
                 for index in indices if self.labels[int(index)] != "Không ký hiệu"][:3]
        margin = float(probabilities[winner] - probabilities[int(indices[1])]) if len(indices) > 1 else float(probabilities[winner])
        full = tuple(float(value) for value in probabilities)
        if (self.labels[winner] == "Không ký hiệu" or probabilities[winner] < self.confidence_threshold
                or margin < self.margin_threshold):
            return BackendPrediction(PredictionStatus.UNCERTAIN, None, None, top_k, full)
        return BackendPrediction(PredictionStatus.OK, top_k[0].label, top_k[0].confidence, top_k, full)

    def predict(self, frames: Sequence[DecodedFrame], sequence: int) -> BackendPrediction:
        del sequence
        started = perf_counter()
        inputs = self._preprocess(frames)
        prepared = perf_counter()
        output = self._model.predict({"frames": inputs})["logits"]
        inferred = perf_counter()
        prediction = self._postprocess(output)
        finished = perf_counter()
        self.last_timings_ms = {"preprocess_ms": (prepared - started) * 1000,
                                "model_ms": (inferred - prepared) * 1000,
                                "postprocess_ms": (finished - inferred) * 1000,
                                "total_ms": (finished - started) * 1000}
        return prediction
