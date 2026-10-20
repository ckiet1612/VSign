from __future__ import annotations

import pytest

from ml.scripts import smoke_personal_runtime as smoke


def metadata(labels):
    return {"model_version": "candidate", "labels": labels, "backend": "pytorch",
            "mock": False, "candidate_labels_unverified": False,
            "frame_count": 16, "frame_width": 224, "frame_height": 224,
            "confidence_threshold": .7, "margin_threshold": .15}


def test_smoke_rejects_wrong_model_and_label_order() -> None:
    labels = [f"word-{index}" for index in range(30)] + ["Không ký hiệu"]
    smoke.validate_metadata(metadata(labels), "candidate", labels)
    with pytest.raises(ValueError, match="metadata"):
        smoke.validate_metadata(metadata(list(reversed(labels))), "candidate", labels)
    with pytest.raises(ValueError, match="metadata"):
        smoke.validate_metadata(metadata(labels), "old-v3", labels)


def test_smoke_rejects_mock_and_changed_rejection_thresholds() -> None:
    labels = [f"word-{index}" for index in range(30)] + ["Không ký hiệu"]
    for field, value in [("mock", True), ("candidate_labels_unverified", True),
                         ("confidence_threshold", .3), ("frame_count", 29)]:
        data = {**metadata(labels), field: value}
        with pytest.raises(ValueError, match="metadata"):
            smoke.validate_metadata(data, "candidate", labels)


def test_smoke_rejects_idle_in_accepted_label_or_suggestions() -> None:
    labels = ["word-a", "Không ký hiệu"]
    prediction = {"type": "prediction", "sequence": 1, "model_version": "candidate",
                  "status": "ok", "label": "Không ký hiệu", "confidence": .99,
                  "top_k": [{"label": "Không ký hiệu", "confidence": .99}]}
    with pytest.raises(ValueError, match="idle"):
        smoke.validate_reply(prediction, 1, "candidate", labels)
    prediction.update(status="uncertain", label=None, confidence=None)
    with pytest.raises(ValueError, match="idle"):
        smoke.validate_reply(prediction, 1, "candidate", labels)


def test_smoke_rejects_stale_reply_and_accepts_valid_uncertain_reply() -> None:
    prediction = {"type": "prediction", "sequence": 2, "model_version": "candidate",
                  "status": "uncertain", "label": None, "confidence": None,
                  "top_k": [{"label": "word-a", "confidence": .2}]}
    smoke.validate_reply(prediction, 2, "candidate", ["word-a", "Không ký hiệu"])
    with pytest.raises(ValueError, match="reply"):
        smoke.validate_reply(prediction, 1, "candidate", ["word-a", "Không ký hiệu"])


def test_smoke_validates_explicit_coreml_backend_without_weakening_pytorch_default() -> None:
    labels = ["word-a", "Không ký hiệu"]
    data = {**metadata(labels), "backend": "coreml"}
    smoke.validate_metadata(data, "candidate", labels, backend="coreml")
    with pytest.raises(ValueError, match="metadata"):
        smoke.validate_metadata(data, "candidate", labels)
    data["mock"] = True
    with pytest.raises(ValueError, match="metadata"):
        smoke.validate_metadata(data, "candidate", labels, backend="coreml")
