from __future__ import annotations

from collections import OrderedDict

import pytest

from app.backends.pytorch import PyTorchInferenceBackend
from app.config import Settings


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
