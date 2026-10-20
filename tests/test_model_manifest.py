from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.backends.mock import MOCK_CANDIDATE_LABELS
from app.main import create_app
from app.model_manifest import ModelManifestError, labels_digest


def write_manifest(tmp_path, **overrides):
    labels = list(MOCK_CANDIDATE_LABELS)
    body = {
        "model_version": "mock-common-20-v1",
        "artifact_sha256": "a" * 64,
        "labels_sha256": labels_digest(labels),
        "backend": "mock",
        "protocol_version": "1.0",
        "frame_count": 16,
        "frame_size": 224,
        "preprocessing_version": "rgb-16x224-imagenet-v1",
        "confidence_threshold": 0.70,
        "margin_threshold": 0.15,
        "source_run_id": "baseline",
        "status": "production",
        **overrides,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_backend_accepts_matching_production_manifest(tmp_path) -> None:
    manifest_path = write_manifest(tmp_path)
    app = create_app(Settings(model_manifest_path=manifest_path))
    assert app.state.model_manifest.model_version == "mock-common-20-v1"


@pytest.mark.parametrize("override", [
    {"model_version": "candidate-v2"},
    {"backend": "coreml"},
    {"labels_sha256": "b" * 64},
    {"frame_count": 8},
    {"confidence_threshold": 0.65},
])
def test_backend_rejects_manifest_that_does_not_match_runtime(tmp_path, override) -> None:
    with pytest.raises(ModelManifestError):
        create_app(Settings(model_manifest_path=write_manifest(tmp_path, **override)))


def test_production_runtime_rejects_candidate_manifest(tmp_path) -> None:
    with pytest.raises(ModelManifestError, match="production"):
        create_app(Settings(model_manifest_path=write_manifest(tmp_path, status="candidate")))
