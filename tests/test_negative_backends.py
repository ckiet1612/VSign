from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import torch

from app.backends.onnx import ONNXInferenceBackend
from app.backends.pytorch import PyTorchInferenceBackend
from app.models import PredictionStatus


@pytest.mark.parametrize("backend_type", [PyTorchInferenceBackend, ONNXInferenceBackend])
@pytest.mark.parametrize(
    ("logits", "expected_status", "expected_label"),
    [([0., 0., 10.], PredictionStatus.UNCERTAIN, None),
     ([10., 0., 0.], PredictionStatus.OK, "word-a"),
     ([0., 0., 0.], PredictionStatus.UNCERTAIN, None)],
)
def test_idle_is_never_accepted_or_offered_as_a_transcript_word(
    backend_type, logits, expected_status, expected_label,
) -> None:
    backend = backend_type.__new__(backend_type)
    backend.labels = ["word-a", "word-b", "Không ký hiệu"]
    backend.confidence_threshold = .7
    backend.margin_threshold = .15
    backend._preprocess = lambda _frames: np.zeros((1, 1), dtype=np.float32)
    if backend_type is PyTorchInferenceBackend:
        backend._torch = torch
        backend._device = torch.device("cpu")
        backend._model = lambda _tensor: torch.tensor([logits])
    else:
        backend._input_name = "frames"
        backend._output_name = "logits"
        backend._session = SimpleNamespace(run=lambda *_args: [np.asarray([logits])])
    result = backend.predict([], 1)
    assert result.status == expected_status
    assert result.label == expected_label
    assert "Không ký hiệu" not in [item.label for item in result.top_k]
    if expected_label is None:
        assert result.confidence is None
