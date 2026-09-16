from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

from app.backends.onnx import ONNXInferenceBackend


class FakeNodeMetadata:
    def __init__(self, name: str, data_type: str, shape: List[object]) -> None:
        self.name = name
        self.type = data_type
        self.shape = shape


class FakeSession:
    def __init__(
        self,
        input_metadata: FakeNodeMetadata,
        output_metadata: FakeNodeMetadata,
    ) -> None:
        self._input_metadata = input_metadata
        self._output_metadata = output_metadata

    def get_inputs(self):
        return [self._input_metadata]

    def get_outputs(self):
        return [self._output_metadata]


def backend_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    model_path = tmp_path / "model.onnx"
    model_path.touch()
    label_path = tmp_path / "labels.json"
    label_path.write_text(json.dumps(["a", "b", "c"]), encoding="utf-8")
    return model_path, label_path


def install_fake_runtime(monkeypatch, session: FakeSession) -> None:
    runtime = SimpleNamespace(InferenceSession=lambda *_args, **_kwargs: session)
    monkeypatch.setitem(sys.modules, "onnxruntime", runtime)


def create_backend(model_path: Path, label_path: Path) -> ONNXInferenceBackend:
    return ONNXInferenceBackend(
        model_path=model_path,
        label_map_path=label_path,
        model_version="test-onnx",
        confidence_threshold=0.7,
        margin_threshold=0.15,
    )


def test_onnx_fails_fast_on_wrong_input_shape(tmp_path: Path, monkeypatch) -> None:
    model_path, label_path = backend_artifacts(tmp_path)
    session = FakeSession(
        FakeNodeMetadata("frames", "tensor(float)", [1, 3, 8, 224, 224]),
        FakeNodeMetadata("logits", "tensor(float)", [1, 3]),
    )
    install_fake_runtime(monkeypatch, session)

    with pytest.raises(RuntimeError, match="axis 2 phải là 16"):
        create_backend(model_path, label_path)


def test_onnx_fails_fast_on_wrong_output_class_count(
    tmp_path: Path, monkeypatch
) -> None:
    model_path, label_path = backend_artifacts(tmp_path)
    session = FakeSession(
        FakeNodeMetadata("frames", "tensor(float)", [1, 3, 16, 224, 224]),
        FakeNodeMetadata("logits", "tensor(float)", [1, 4]),
    )
    install_fake_runtime(monkeypatch, session)

    with pytest.raises(RuntimeError, match="4 lớp nhưng label map có 3"):
        create_backend(model_path, label_path)


@pytest.mark.parametrize(
    ("input_type", "output_type"),
    [("tensor(float16)", "tensor(float)"), ("tensor(float)", "tensor(int64)")],
)
def test_onnx_fails_fast_on_wrong_tensor_type(
    tmp_path: Path, monkeypatch, input_type: str, output_type: str
) -> None:
    model_path, label_path = backend_artifacts(tmp_path)
    session = FakeSession(
        FakeNodeMetadata("frames", input_type, [1, 3, 16, 224, 224]),
        FakeNodeMetadata("logits", output_type, [1, 3]),
    )
    install_fake_runtime(monkeypatch, session)

    with pytest.raises(RuntimeError, match=r"tensor\(float\)"):
        create_backend(model_path, label_path)
