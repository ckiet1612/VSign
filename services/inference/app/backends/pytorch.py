from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

import numpy as np
from PIL import Image

from app.backends.base import BackendCandidate, BackendPrediction, DecodedFrame
from app.backends.labels import load_labels
from app.models import FRAME_COUNT, FRAME_SIZE, PredictionStatus


IMAGENET_MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)


class PyTorchInferenceBackend:
    """MViTv2-S runtime compatible with the official Multi-VSL checkpoint."""

    name = "pytorch"
    is_mock = False

    def __init__(
        self,
        model_path: Path,
        label_map_path: Path,
        model_version: str,
        confidence_threshold: float,
        margin_threshold: float,
        device: str = "auto",
        labels_verified: bool = False,
    ) -> None:
        if not model_path.is_file():
            raise RuntimeError(f"Không tìm thấy PyTorch checkpoint: {model_path}")
        self.labels = load_labels(label_map_path)
        self.model_version = model_version
        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold
        self.candidate_labels_unverified = not labels_verified

        try:
            import torch
            from torchvision.models.video import mvit_v2_s
        except ImportError as exc:
            raise RuntimeError(
                "Thiếu PyTorch runtime; cài bằng 'pip install -e .[pytorch]'"
            ) from exc

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("PYTORCH_DEVICE=cuda nhưng CUDA không khả dụng")
        if device not in {"cpu", "cuda"}:
            raise RuntimeError("PYTORCH_DEVICE chỉ hỗ trợ auto, cpu hoặc cuda")
        self.device = device
        self.gpu_name = torch.cuda.get_device_name(0) if device == "cuda" else None
        resolved_device = torch.device(device)

        try:
            checkpoint = torch.load(
                model_path, map_location="cpu", weights_only=True
            )
        except TypeError:
            checkpoint = torch.load(model_path, map_location="cpu")
        except Exception as exc:
            raise RuntimeError(f"Không đọc được PyTorch checkpoint: {model_path}") from exc

        state_dict = self._extract_state_dict(checkpoint)
        model = mvit_v2_s(weights=None)
        model.head[-1] = torch.nn.Linear(model.head[-1].in_features, len(self.labels))
        try:
            model.load_state_dict(state_dict, strict=True)
        except Exception as exc:
            raise RuntimeError(
                "Checkpoint không khớp kiến trúc MViTv2-S hoặc số class trong label map"
            ) from exc
        self._torch = torch
        self._model = model.to(resolved_device).eval()
        self._device = resolved_device
        self.last_timings_ms: dict[str, float] = {}
        # On CUDA this also pays kernel selection before the first real clip.
        self._warmup()

    def _warmup(self) -> None:
        # Pay lazy operator initialization before the server accepts requests.
        tensor = self._torch.zeros(
            (1, 3, FRAME_COUNT, FRAME_SIZE, FRAME_SIZE), device=self._device
        )
        with self._torch.inference_mode():
            self._model(tensor)
        if self._device.type == "cuda":
            self._torch.cuda.synchronize(self._device)

    @staticmethod
    def _extract_state_dict(checkpoint: Any) -> Mapping[str, Any]:
        state_dict = checkpoint
        if isinstance(checkpoint, Mapping):
            for key in ("state_dict", "model"):
                nested = checkpoint.get(key)
                if isinstance(nested, Mapping):
                    state_dict = nested
                    break
        if not isinstance(state_dict, Mapping) or not state_dict:
            raise RuntimeError("Checkpoint không chứa state_dict hợp lệ")

        normalized = {}
        for raw_key, value in state_dict.items():
            if not isinstance(raw_key, str):
                raise RuntimeError("Checkpoint có tên tensor không hợp lệ")
            key = raw_key.removeprefix("module.")
            normalized[key] = value
        return normalized

    def _preprocess(self, frames: Sequence[DecodedFrame]) -> np.ndarray:
        if len(frames) != FRAME_COUNT:
            raise ValueError(f"PyTorch backend cần đúng {FRAME_COUNT} frame")
        arrays = []
        for decoded in frames:
            rgb = decoded.image
            if rgb.mode != "RGB":
                rgb = rgb.convert("RGB")
            if rgb.size != (FRAME_SIZE, FRAME_SIZE):
                rgb = rgb.resize((FRAME_SIZE, FRAME_SIZE), Image.Resampling.BILINEAR)
            arrays.append(np.asarray(rgb, dtype=np.float32) / 255.0)
        clip = np.stack(arrays, axis=0)
        clip = (clip - IMAGENET_MEAN) / IMAGENET_STD
        return np.ascontiguousarray(np.transpose(clip, (3, 0, 1, 2))[None, ...])

    def predict(
        self, frames: Sequence[DecodedFrame], sequence: int
    ) -> BackendPrediction:
        del sequence
        started = perf_counter()
        tensor = self._torch.from_numpy(self._preprocess(frames)).to(self._device)
        prepared = perf_counter()
        with self._torch.inference_mode():
            logits = self._model(tensor)
            probabilities = self._torch.softmax(logits, dim=1)[0].detach().cpu().numpy()
        inferred = perf_counter()
        if probabilities.size != len(self.labels):
            raise RuntimeError(
                f"PyTorch output có {probabilities.size} lớp nhưng label map có {len(self.labels)}"
            )
        indices = np.argsort(probabilities)[::-1]
        winner = int(indices[0])
        top_k = [
            BackendCandidate(self.labels[int(index)], float(probabilities[index]))
            for index in indices
            if self.labels[int(index)] != "Không ký hiệu"
        ][:3]
        margin = (
            float(probabilities[winner] - probabilities[int(indices[1])])
            if len(indices) > 1
            else float(probabilities[winner])
        )
        finished = perf_counter()
        self.last_timings_ms = {
            "preprocess_ms": (prepared - started) * 1000,
            "model_ms": (inferred - prepared) * 1000,
            "postprocess_ms": (finished - inferred) * 1000,
            "total_ms": (finished - started) * 1000,
        }
        full = tuple(float(value) for value in probabilities)
        if (
            self.labels[winner] == "Không ký hiệu"
            or probabilities[winner] < self.confidence_threshold
            or margin < self.margin_threshold
        ):
            return BackendPrediction(PredictionStatus.UNCERTAIN, None, None, top_k, full)
        return BackendPrediction(
            PredictionStatus.OK, top_k[0].label, top_k[0].confidence, top_k, full
        )
