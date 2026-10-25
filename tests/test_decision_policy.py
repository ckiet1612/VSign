from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.backends.coreml import CoreMLInferenceBackend
from app.decision import DecisionPolicy, labels_digest
from app.models import PredictionStatus

LABELS = tuple(json.loads(Path("contracts/v1/sales30.labels.json").read_text(encoding="utf-8")) + ["Không ký hiệu"])


def vector(**weights: float) -> np.ndarray:
    values = np.full(len(LABELS), 1e-4)
    for label, weight in weights.items():
        values[LABELS.index(label.replace("_", " "))] = weight
    return values / values.sum()


def legacy(probabilities: np.ndarray):
    backend = CoreMLInferenceBackend.__new__(CoreMLInferenceBackend)
    backend.labels, backend.confidence_threshold, backend.margin_threshold = list(LABELS), .7, .15
    return backend._postprocess(np.log(probabilities)[None, :])


@pytest.mark.parametrize("weights", [
    {"Tôi": .9, "Muốn": .05}, {"Tôi": .6, "Muốn": .3}, {"Không_ký_hiệu": .8, "Tôi": .1},
    {"Gạo": .72, "Tủ_lạnh": .2}, {"Có": .5, "Rẻ": .45},
])
def test_baseline_policy_matches_fixed_threshold_runtime(weights):
    probabilities = vector(**weights)
    expected = legacy(probabilities)
    decided, adjusted = DecisionPolicy.baseline(LABELS, .7, .15).decide(probabilities)
    assert adjusted == ()
    assert (decided.status, decided.label, [item.label for item in decided.top_k]) == (
        expected.status, expected.label, [item.label for item in expected.top_k])
    assert decided.confidence == pytest.approx(expected.confidence)


def test_context_accepts_a_weak_winner_only_when_it_alone_fits_the_sentence():
    policy = DecisionPolicy(labels=LABELS, context_penalty=.5, context_floor=.4)
    # After "Tôi muốn", Mua fits; Chào and Cảm ơn cannot continue the sentence.
    probabilities = vector(Mua=.5, Chào=.3, Cảm_ơn=.15)
    decided, adjusted = policy.decide(probabilities, ["Tôi", "Muốn"])
    assert decided.status is PredictionStatus.OK and decided.label == "Mua"
    assert "context" in adjusted
    # The same low score without context stays uncertain.
    assert policy.decide(probabilities)[0].status is PredictionStatus.UNCERTAIN
    # Two grammatical candidates: context cannot vouch for either.
    ambiguous = vector(Mua=.5, Xem=.4)
    assert policy.decide(ambiguous, ["Tôi", "Muốn"])[0].status is PredictionStatus.UNCERTAIN


def test_context_reorders_within_top3_and_never_accepts_idle():
    policy = DecisionPolicy(labels=LABELS, context_penalty=.1, context_floor=.3)
    decided, _ = policy.decide(vector(Chào=.45, Mua=.4, Không_ký_hiệu=.1), ["Tôi", "Muốn"])
    assert decided.top_k[0].label == "Mua"
    assert decided.status is PredictionStatus.OK
    idle = vector(Không_ký_hiệu=.6, Mua=.3)
    assert policy.decide(idle, ["Tôi", "Muốn"])[0].status is PredictionStatus.UNCERTAIN
    # Unknown or idle context words are ignored instead of failing the request.
    assert policy.decide(vector(Mua=.95), ["???", "Không ký hiệu"])[1] == ()


def test_confuser_veto_and_per_word_threshold():
    policy = DecisionPolicy(labels=LABELS, thresholds={"Đắt": .9, "Tôi": .55}, confusers={"Có": {"Rẻ": .02}})
    assert policy.decide(vector(Có=.9, Rẻ=.05))[0].status is PredictionStatus.UNCERTAIN
    assert policy.decide(vector(Có=.95, Rẻ=.005))[0].label == "Có"
    assert policy.decide(vector(Đắt=.85, Rẻ=.14))[0].status is PredictionStatus.UNCERTAIN
    assert policy.decide(vector(Tôi=.6, Muốn=.1))[0].label == "Tôi"


def test_policy_file_must_match_model_and_labels(tmp_path):
    payload = {"model_version": "m1", "labels_sha256": labels_digest(LABELS), "temperature": 1.1,
               "bias": {"Gạo": -.2}, "thresholds": {"Gạo": .9}, "confusers": {"Có": {"Rẻ": .02}},
               "default_threshold": .7, "margin_threshold": .15, "context_penalty": .5, "context_floor": .4}
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    loaded = DecisionPolicy.load(path, LABELS, "m1")
    assert loaded.thresholds == {"Gạo": .9} and loaded.confusers == {"Có": {"Rẻ": .02}}
    with pytest.raises(ValueError):
        DecisionPolicy.load(path, LABELS, "other-model")
    path.write_text(json.dumps({**payload, "thresholds": {"Unknown": .9}}), encoding="utf-8")
    with pytest.raises(ValueError):
        DecisionPolicy.load(path, LABELS, "m1")


class ProbabilityBackend:
    name = "pytorch"
    model_version = "policy-test-v1"
    labels = list(LABELS)
    candidate_labels_unverified = False
    is_mock = False

    def __init__(self, probabilities):
        self.probabilities = probabilities

    def predict(self, frames, sequence):
        from app.backends.base import BackendPrediction
        return BackendPrediction(PredictionStatus.UNCERTAIN, None, None, [], tuple(float(v) for v in self.probabilities))


def _frames_payload(sequence, context=None):
    import base64
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), (30, 90, 160)).save(buffer, format="WEBP")
    frame = "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    payload = {"type": "frames", "session_id": "123e4567-e89b-12d3-a456-426614174000", "sequence": sequence,
               "captured_at": 1788980000000, "frames": [frame] * 16}
    if context is not None:
        payload["context_words"] = context
    return payload


def test_websocket_applies_policy_with_sentence_context(tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    policy = tmp_path / "calibration.json"
    policy.write_text(json.dumps({"model_version": "policy-test-v1", "labels_sha256": labels_digest(LABELS),
                                  "temperature": 1.0, "bias": {}, "thresholds": {}, "confusers": {},
                                  "default_threshold": .7, "margin_threshold": .15,
                                  "context_penalty": .5, "context_floor": .4}), encoding="utf-8")
    backend = ProbabilityBackend(vector(Mua=.5, Chào=.3, Cảm_ơn=.15))
    with TestClient(create_app(replace(Settings(), decision_policy_path=policy), backend=backend)) as client:
        with client.websocket_connect("/ws/inference") as socket:
            socket.send_json(_frames_payload(1))
            plain = socket.receive_json()
            socket.send_json(_frames_payload(2, ["Tôi", "Muốn"]))
            contextual = socket.receive_json()
    assert plain["status"] == "uncertain" and plain["adjusted"] == []
    assert contextual["status"] == "ok" and contextual["label"] == "Mua" and contextual["adjusted"] == ["context"]


def test_policy_for_another_model_is_ignored(tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    policy = tmp_path / "calibration.json"
    policy.write_text(json.dumps({"model_version": "other", "labels_sha256": labels_digest(LABELS),
                                  "temperature": 1.0, "default_threshold": .7, "margin_threshold": .15,
                                  "context_penalty": .5, "context_floor": .4}), encoding="utf-8")
    backend = ProbabilityBackend(vector(Mua=.5, Chào=.3, Cảm_ơn=.15))
    with TestClient(create_app(replace(Settings(), decision_policy_path=policy), backend=backend)) as client:
        with client.websocket_connect("/ws/inference") as socket:
            socket.send_json(_frames_payload(1, ["Tôi", "Muốn"]))
            reply = socket.receive_json()
    assert reply["status"] == "uncertain" and reply["adjusted"] == []


def test_lead_over_the_runner_up_accepts_below_the_confidence_threshold():
    policy = DecisionPolicy(labels=LABELS, default_threshold=.4, margin_threshold=0, lead_threshold=.15)
    # 32% but 17 points ahead of the second word: accepted on the lead.
    assert policy.decide(vector(Mua=.32, Xem=.15, Cần=.14, Tivi=.13, Gạo=.12, Sữa=.12))[0].label == "Mua"
    # 30% and only 5 points ahead: neither rule holds.
    assert policy.decide(vector(Mua=.3, Xem=.25, Cần=.2, Tivi=.13, Gạo=.12))[0].status is PredictionStatus.UNCERTAIN
    # 45% with a 3-point lead still passes on confidence alone.
    assert policy.decide(vector(Mua=.45, Xem=.42, Cần=.13))[0].label == "Mua"
    # A lead never accepts idle, and a confuser still vetoes a leading word.
    assert policy.decide(vector(Không_ký_hiệu=.5, Mua=.2))[0].status is PredictionStatus.UNCERTAIN
    vetoed = DecisionPolicy(labels=LABELS, default_threshold=.4, margin_threshold=0, lead_threshold=.15, confusers={"Có": {"Rẻ": .1}})
    assert vetoed.decide(vector(Có=.35, Rẻ=.12, Mua=.1))[0].status is PredictionStatus.UNCERTAIN
    # Without the rule the 32% winner stays uncertain, as before.
    assert DecisionPolicy(labels=LABELS, default_threshold=.4, margin_threshold=0).decide(
        vector(Mua=.32, Xem=.15, Cần=.14, Tivi=.13, Gạo=.12, Sữa=.12))[0].status is PredictionStatus.UNCERTAIN


@pytest.mark.parametrize("with_policy", [True, False])
def test_runtime_applies_the_configured_lead_with_or_without_a_policy_file(tmp_path, with_policy, monkeypatch):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    monkeypatch.setenv("LEAD_THRESHOLD", ".15")
    assert Settings.from_env().lead_threshold == pytest.approx(.15)
    monkeypatch.setenv("LEAD_THRESHOLD", "0")
    assert Settings.from_env().lead_threshold is None
    settings = replace(Settings(), lead_threshold=.15)
    if with_policy:
        policy = tmp_path / "calibration.json"
        policy.write_text(json.dumps({"model_version": "policy-test-v1", "labels_sha256": labels_digest(LABELS),
                                      "temperature": 1.0, "default_threshold": .4, "margin_threshold": 0,
                                      "context_penalty": 1, "context_floor": None}), encoding="utf-8")
        settings = replace(settings, decision_policy_path=policy)
    backend = ProbabilityBackend(vector(Mua=.32, Xem=.15, Cần=.14, Tivi=.13, Gạo=.12, Sữa=.12))
    backend.confidence_threshold, backend.margin_threshold = .4, 0.0
    with TestClient(create_app(settings, backend=backend)) as client:
        with client.websocket_connect("/ws/inference") as socket:
            socket.send_json(_frames_payload(1))
            reply = socket.receive_json()
    assert reply["status"] == "ok" and reply["label"] == "Mua"
