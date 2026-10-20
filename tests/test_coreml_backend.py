from __future__ import annotations

import numpy as np
import pytest


def backend():
    from app.backends.coreml import CoreMLInferenceBackend
    result = CoreMLInferenceBackend.__new__(CoreMLInferenceBackend)
    result.labels = ["word-a", "word-b", "Không ký hiệu"]
    result.confidence_threshold = .7
    result.margin_threshold = .15
    return result


@pytest.mark.parametrize("logits,status,label", [
    ([[10., 0., 0.]], "ok", "word-a"),
    ([[0., 0., 10.]], "uncertain", None),
    ([[0., 0., 0.]], "uncertain", None),
    ([[.8, .19, .01]], "ok", "word-a"),
])
def test_coreml_rejection_matches_existing_thresholds_and_never_offers_idle(logits, status, label) -> None:
    values = np.asarray(logits, dtype=np.float32)
    if logits == [[.8, .19, .01]]:
        values = np.log(values)
    prediction = backend()._postprocess(values)
    assert prediction.status.value == status
    assert prediction.label == label
    assert "Không ký hiệu" not in [item.label for item in prediction.top_k]
    if status == "uncertain":
        assert prediction.confidence is None


@pytest.mark.parametrize("logits", [np.zeros((3,)), np.zeros((1, 4)), np.zeros((2, 3)),
                                    np.array([[float("nan"), 0., 0.]]), np.array([[float("inf"), 0., 0.]])])
def test_coreml_rejects_wrong_output_shape_and_nonfinite_logits(logits) -> None:
    with pytest.raises(RuntimeError):
        backend()._postprocess(logits)


def test_coreml_applies_margin_even_when_confidence_threshold_passes() -> None:
    result = backend()
    result.margin_threshold = .7
    prediction = result._postprocess(np.log(np.array([[.75, .20, .05]], dtype=np.float32)))
    assert prediction.status.value == "uncertain"
    assert prediction.label is None


def test_coreml_settings_and_factory_require_an_explicit_model_path(monkeypatch) -> None:
    from app.backends import create_backend
    from app.config import Settings
    monkeypatch.setenv("INFERENCE_BACKEND", "coreml")
    monkeypatch.setenv("COREML_MODEL_PATH", "")
    settings = Settings.from_env()
    assert settings.inference_backend == "coreml"
    with pytest.raises(RuntimeError, match="COREML_MODEL_PATH"):
        create_backend(settings)


def test_coreml_settings_reject_invalid_compute_units(monkeypatch) -> None:
    from app.config import Settings
    monkeypatch.setenv("INFERENCE_BACKEND", "coreml")
    monkeypatch.setenv("COREML_COMPUTE_UNITS", "CUDA")
    with pytest.raises(RuntimeError, match="COREML_COMPUTE_UNITS"):
        Settings.from_env()


def test_invalid_coreml_options_do_not_block_pytorch_rollback(monkeypatch) -> None:
    from app.config import Settings
    monkeypatch.setenv("INFERENCE_BACKEND", "pytorch")
    monkeypatch.setenv("COREML_COMPUTE_UNITS", "CUDA")
    assert Settings.from_env().inference_backend == "pytorch"
