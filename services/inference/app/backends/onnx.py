from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

from app.backends.base import BackendCandidate, BackendPrediction, DecodedFrame
from app.backends.labels import load_labels
from app.models import FRAME_COUNT, FRAME_SIZE, PredictionStatus


class ONNXInferenceBackend:
    name = "onnx"
    candidate_labels_unverified = False
    is_mock = False

    def __init__(
        self,
        model_path: Path,
        label_map_path: Path,
        model_version: str,
        confidence_threshold: float,
        margin_threshold: float,
        labels_verified: bool = False,
    ) -> None:
        if not model_path.is_file():
            raise RuntimeError(f"Không tìm thấy ONNX model: {model_path}")
        self.labels = load_labels(label_map_path)
        self.candidate_labels_unverified = not labels_verified
        self.model_version = model_version
        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "Thiếu onnxruntime; cài optional dependency bằng 'pip install -e .[onnx]'"
            ) from exc
        try:
            self._session = ort.InferenceSession(
                str(model_path), providers=["CPUExecutionProvider"]
            )
        except Exception as exc:
            raise RuntimeError(f"Không thể khởi tạo ONNX model: {model_path}") from exc
        inputs = self._session.get_inputs()
        if len(inputs) != 1:
            raise RuntimeError("ONNX model cần đúng một input [1,C,T,H,W]")
        input_metadata = inputs[0]
        if input_metadata.type != "tensor(float)":
            raise RuntimeError(
                f"ONNX input phải là tensor(float), nhận {input_metadata.type}"
            )
        input_shape = input_metadata.shape
        expected_input_shape = (1, 3, FRAME_COUNT, FRAME_SIZE, FRAME_SIZE)
        if not isinstance(input_shape, (list, tuple)) or len(input_shape) != len(
            expected_input_shape
        ):
            raise RuntimeError("ONNX input phải có rank 5 [1,C,T,H,W]")
        for axis, (actual, expected) in enumerate(
            zip(input_shape, expected_input_shape)
        ):
            if isinstance(actual, int) and actual != expected:
                raise RuntimeError(
                    f"ONNX input axis {axis} phải là {expected}, nhận {actual}"
                )
            if not isinstance(actual, (int, str)) and actual is not None:
                raise RuntimeError(f"ONNX input axis {axis} có dimension không hợp lệ")

        outputs = self._session.get_outputs()
        if len(outputs) != 1:
            raise RuntimeError("ONNX model cần đúng một logits output [1,num_classes]")
        output_metadata = outputs[0]
        if output_metadata.type != "tensor(float)":
            raise RuntimeError(
                f"ONNX output phải là tensor(float), nhận {output_metadata.type}"
            )
        output_shape = output_metadata.shape
        if not isinstance(output_shape, (list, tuple)) or len(output_shape) != 2:
            raise RuntimeError("ONNX output phải có rank 2 [1,num_classes]")
        output_batch, output_classes = output_shape
        if isinstance(output_batch, int) and output_batch != 1:
            raise RuntimeError(
                f"ONNX output batch dimension phải là 1, nhận {output_batch}"
            )
        if not isinstance(output_batch, (int, str)) and output_batch is not None:
            raise RuntimeError("ONNX output batch dimension không hợp lệ")
        if not isinstance(output_classes, int):
            raise RuntimeError("ONNX output num_classes phải là dimension tĩnh")
        if output_classes != len(self.labels):
            raise RuntimeError(
                f"ONNX output có {output_classes} lớp nhưng label map có {len(self.labels)}"
            )
        self._input_name = input_metadata.name
        self._output_name = output_metadata.name

    def _preprocess(self, frames: Sequence[DecodedFrame]) -> np.ndarray:
        if len(frames) != FRAME_COUNT:
            raise ValueError(f"ONNX backend cần đúng {FRAME_COUNT} frame")
        arrays = []
        for decoded in frames:
            rgb = decoded.image.convert("RGB").resize(
                (FRAME_SIZE, FRAME_SIZE), Image.Resampling.BILINEAR
            )
            arrays.append(np.asarray(rgb, dtype=np.float32) / 255.0)
        clip = np.stack(arrays, axis=0)
        mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
        clip = (clip - mean) / std
        return np.transpose(clip, (3, 0, 1, 2))[None, ...].astype(np.float32)

    def predict(
        self, frames: Sequence[DecodedFrame], sequence: int
    ) -> BackendPrediction:
        del sequence
        tensor = self._preprocess(frames)
        output = np.asarray(
            self._session.run([self._output_name], {self._input_name: tensor})[0]
        ).reshape(-1)
        if output.size != len(self.labels):
            raise RuntimeError(
                f"ONNX output có {output.size} lớp nhưng label map có {len(self.labels)}"
            )
        shifted = output - np.max(output)
        probabilities = np.exp(shifted) / np.exp(shifted).sum()
        indices = np.argsort(probabilities)[::-1]
        winner = int(indices[0])
        top_k = [
            BackendCandidate(self.labels[int(index)], float(probabilities[index]))
            for index in indices
            if self.labels[int(index)] != "Không ký hiệu"
        ][:3]
        margin = (
            float(probabilities[winner] - probabilities[int(indices[1])])
            if len(indices) > 1 else float(probabilities[winner])
        )
        if (self.labels[winner] == "Không ký hiệu"
                or probabilities[winner] < self.confidence_threshold
                or margin < self.margin_threshold):
            return BackendPrediction(PredictionStatus.UNCERTAIN, None, None, top_k)
        return BackendPrediction(
            PredictionStatus.OK, top_k[0].label, top_k[0].confidence, top_k
        )
