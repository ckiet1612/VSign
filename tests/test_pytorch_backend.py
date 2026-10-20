from __future__ import annotations

from collections import OrderedDict

import pytest

from app.backends.pytorch import PyTorchInferenceBackend
from app.config import Settings


@pytest.mark.parametrize("mode,size", [("RGB", (224, 224)), ("RGBA", (160, 190)), ("L", (224, 224))])
def test_preprocess_preserves_values_and_produces_contiguous_model_input(mode, size) -> None:
    import numpy as np
    from PIL import Image
    from app.backends.base import DecodedFrame

    backend = PyTorchInferenceBackend.__new__(PyTorchInferenceBackend)
    images = [Image.new(mode, size, index * 7) for index in range(16)]
    frames = [DecodedFrame(image, b"") for image in images]
    try:
        original = np.stack([
            np.asarray(image.convert("RGB").resize((224, 224), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
            for image in images
        ])
        original = (original - np.asarray([.485, .456, .406], dtype=np.float32)) / np.asarray([.229, .224, .225], dtype=np.float32)
        expected = np.transpose(original, (3, 0, 1, 2))[None, ...].astype(np.float32)
        actual = backend._preprocess(frames)
        np.testing.assert_array_equal(actual, expected)
        assert actual.shape == (1, 3, 16, 224, 224)
        assert actual.dtype == np.float32
        assert actual.flags.c_contiguous
    finally:
        for image in images:
            image.close()


def tiny_backend():
    torch = pytest.importorskip("torch")
    backend = PyTorchInferenceBackend.__new__(PyTorchInferenceBackend)
    backend._torch = torch
    backend._device = torch.device("cpu")
    backend.labels = ["yes", "no", "idle"]
    backend.confidence_threshold = .7
    backend.margin_threshold = .15
    model = torch.nn.Sequential(torch.nn.AdaptiveAvgPool3d(1), torch.nn.Flatten(), torch.nn.Linear(3, 3))
    with torch.no_grad():
        model[-1].weight.zero_()
        model[-1].bias.copy_(torch.tensor([5., 0., -1.]))
    backend._model = model.eval()
    return backend


def test_warmup_runs_real_forward_without_changing_predictions_or_weights() -> None:
    import numpy as np
    backend = tiny_backend()
    original = {key: value.clone() for key, value in backend._model.state_dict().items()}
    backend._warmup()
    for key, value in backend._model.state_dict().items():
        assert backend._torch.equal(value, original[key])
    backend._preprocess = lambda frames: np.zeros((1, 3, 16, 224, 224), dtype=np.float32)
    prediction = backend.predict([], 0)
    assert prediction.label == "yes"
    assert prediction.status.value == "ok"
    assert prediction.confidence > .98


def test_prediction_records_nonnegative_stage_timings_without_changing_result() -> None:
    import numpy as np
    backend = tiny_backend()
    backend._preprocess = lambda frames: np.zeros((1, 3, 16, 224, 224), dtype=np.float32)
    prediction = backend.predict([], 0)
    assert prediction.label == "yes"
    timing = backend.last_timings_ms
    assert set(timing) == {"preprocess_ms", "model_ms", "postprocess_ms", "total_ms"}
    assert all(value >= 0 for value in timing.values())
    assert timing["total_ms"] == pytest.approx(sum(timing[key] for key in ("preprocess_ms", "model_ms", "postprocess_ms")))


def test_extracts_plain_and_nested_state_dict() -> None:
    tensor = object()
    plain = OrderedDict([("head.weight", tensor)])
    nested = {"state_dict": {"module.head.weight": tensor}}

    assert PyTorchInferenceBackend._extract_state_dict(plain) == plain
    assert PyTorchInferenceBackend._extract_state_dict(nested) == {
        "head.weight": tensor
    }


def test_rejects_invalid_state_dict() -> None:
    with pytest.raises(RuntimeError, match="state_dict hợp lệ"):
        PyTorchInferenceBackend._extract_state_dict({})


def test_settings_accept_pytorch_backend(monkeypatch) -> None:
    monkeypatch.setenv("INFERENCE_BACKEND", "pytorch")
    monkeypatch.setenv("PYTORCH_MODEL_PATH", "/tmp/model.pth")
    monkeypatch.setenv("LABEL_MAP_PATH", "/tmp/labels.json")
    monkeypatch.setenv("PYTORCH_DEVICE", "cpu")
    monkeypatch.setenv("LABELS_VERIFIED", "true")

    settings = Settings.from_env()

    assert settings.inference_backend == "pytorch"
    assert settings.pytorch_model_path is not None
    assert settings.pytorch_device == "cpu"
    assert settings.labels_verified is True


def test_settings_reject_unsupported_device(monkeypatch) -> None:
    monkeypatch.setenv("PYTORCH_DEVICE", "mps")

    with pytest.raises(RuntimeError, match="auto, cpu hoặc cuda"):
        Settings.from_env()
