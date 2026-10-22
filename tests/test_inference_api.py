from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from typing import Sequence

from fastapi.testclient import TestClient
from PIL import Image

from app.backends.base import BackendPrediction, DecodedFrame
from app.backends.mock import MockInferenceBackend
from app.config import Settings
from app.main import create_app
from app.sentence import SentenceComposition


def image_data_url(image_format: str = "WEBP") -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 12), color=(34, 120, 190)).save(buffer, format=image_format)
    mime = "image/jpeg" if image_format == "JPEG" else "image/webp"
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def valid_payload(sequence: int = 12) -> dict:
    frame = image_data_url()
    return {
        "type": "frames",
        "session_id": "123e4567-e89b-12d3-a456-426614174000",
        "sequence": sequence,
        "captured_at": 1788980000000,
        "frames": [frame] * 16,
    }


def receive_prediction(client: TestClient, payload: dict) -> dict:
    with client.websocket_connect("/ws/inference") as socket:
        socket.send_json(payload)
        return socket.receive_json()


def test_metadata_reports_body_framing_for_models_trained_on_it(monkeypatch) -> None:
    monkeypatch.setenv("INPUT_FRAMING", "trim-bodycrop-v1")
    with TestClient(create_app(Settings.from_env())) as client:
        assert client.get("/metadata").json()["input_framing"] == "trim-bodycrop-v1"
    monkeypatch.setenv("INPUT_FRAMING", "stretch")
    try:
        Settings.from_env()
    except RuntimeError as error:
        assert "INPUT_FRAMING" in str(error)
    else:
        raise AssertionError("invalid INPUT_FRAMING accepted")


def test_gpu_identity_matches_metadata_and_the_connected_runtime() -> None:
    backend = MockInferenceBackend()
    backend.gpu_name = "NVIDIA T4"
    with TestClient(create_app(Settings(), backend=backend)) as client:
        assert client.get("/metadata").json()["gpu_name"] == "NVIDIA T4"
        with client.websocket_connect("/ws/inference") as socket:
            assert socket.receive_json() == {"type": "runtime_info", "gpu_name": "NVIDIA T4"}
            socket.send_json(valid_payload())
            assert socket.receive_json()["type"] == "prediction"


def test_health_and_metadata() -> None:
    with TestClient(create_app(Settings())) as client:
        health = client.get("/health")
        metadata = client.get("/metadata")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "backend": "mock",
        "model_version": "mock-common-20-v1",
        "protocol_version": "1.0",
    }
    body = metadata.json()
    assert body["input_framing"] == "center-square"
    assert body["mock"] is True
    assert body["candidate_labels_unverified"] is True
    assert body["frame_count"] == 16
    assert (body["frame_width"], body["frame_height"]) == (224, 224)
    assert len(body["labels"]) == 20
    assert body["collection_labels"] == [
        "Chào",
        "Tôi",
        "Muốn",
        "Mua",
        "Cho",
        "Xem",
        "Thử",
        "Siêu thị",
        "Có",
        "Cần",
        "Điện thoại",
        "Laptop",
        "Tivi",
        "Tủ lạnh",
        "Máy giặt",
        "Nồi cơm điện",
        "Gạo",
        "Sữa",
        "Cà phê",
        "Mới",
        "Cũ",
        "Rẻ",
        "Đắt",
        "Sử dụng",
        "Mua bán",
        "Ngân hàng",
        "Cung cấp",
        "Thay đổi",
        "Từ chối",
        "Cảm ơn",
    ]
    assert len(set(body["collection_labels"])) == 30
    assert body["sentence_ai_enabled"] is False


class FixedSentenceComposer:
    enabled = True

    def compose(self, words: Sequence[str]) -> SentenceComposition:
        assert list(words) == ["Tôi", "Muốn", "Mua", "Điện thoại"]
        return SentenceComposition(
            sentence="Tôi muốn mua điện thoại.",
            provider="openai",
            model="test-model",
        )


def test_compose_sentence_uses_configured_composer() -> None:
    app = create_app(Settings(), sentence_composer=FixedSentenceComposer())

    with TestClient(app) as client:
        response = client.post(
            "/sentence/compose",
            json={"words": ["Tôi", "Muốn", "Mua", "Điện thoại"]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "sentence": "Tôi muốn mua điện thoại.",
        "provider": "openai",
        "model": "test-model",
        "warnings": [],
    }


def test_expanded_composition_returns_review_warnings_and_legacy_is_reversible() -> None:
    words = ["Tôi", "Laptop", "Mới", "Muốn"]
    with TestClient(create_app(Settings())) as client:
        assert client.post("/sentence/compose", json={"words": words}).json() == {
            "sentence": "Tôi muốn laptop mới.", "provider": "local", "model": None, "warnings": [],
        }
        unclear = client.post("/sentence/compose", json={"words": ["Laptop", "Mới", "Cũ"]})
        assert unclear.status_code == 200
        assert unclear.json()["sentence"] == "Laptop mới cũ."
        assert unclear.json()["warnings"]
    with TestClient(create_app(Settings(sentence_rules="legacy"))) as client:
        assert client.post("/sentence/compose", json={"words": words}).json() == {
            "sentence": "Tôi laptop mới muốn.", "provider": "local", "model": None, "warnings": [],
        }


def test_composition_does_not_silently_truncate_a_long_draft() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.post("/sentence/compose", json={"words": ["Nồi cơm điện"] * 30})
        assert response.status_code == 422


def test_compose_sentence_falls_back_locally_without_api_configuration() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.post(
            "/sentence/compose",
            json={"words": ["Tôi", "Muốn", "Mua", "Điện thoại"]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "sentence": "Tôi muốn mua điện thoại.",
        "provider": "local",
        "model": None,
        "warnings": [],
    }


def test_compose_sentence_rejects_words_outside_current_model() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.post(
            "/sentence/compose",
            json={"words": ["Tôi", "mật khẩu bí mật"]},
        )

    assert response.status_code == 422


def test_valid_websocket_request_returns_schema_and_preserves_sequence() -> None:
    with TestClient(create_app(Settings())) as client:
        response = receive_prediction(client, valid_payload(sequence=41))

    assert response["type"] == "prediction"
    assert response["sequence"] == 41
    assert response["status"] == "ok"
    assert response["label"]
    assert 0 <= response["confidence"] <= 1
    assert len(response["top_k"]) == 3
    assert [item["confidence"] for item in response["top_k"]] == sorted(
        [item["confidence"] for item in response["top_k"]], reverse=True
    )


def test_mock_is_deterministic() -> None:
    with TestClient(create_app(Settings())) as client:
        first = receive_prediction(client, valid_payload(sequence=3))
        second = receive_prediction(client, valid_payload(sequence=3))
    assert first == second


def test_rejects_wrong_frame_count_and_invalid_uuid() -> None:
    wrong_count = valid_payload()
    wrong_count["frames"] = wrong_count["frames"][:-1]
    wrong_uuid = valid_payload(sequence=19)
    wrong_uuid["session_id"] = "not-a-uuid"
    with TestClient(create_app(Settings())) as client:
        count_response = receive_prediction(client, wrong_count)
        uuid_response = receive_prediction(client, wrong_uuid)
    assert count_response["status"] == "error"
    assert uuid_response["status"] == "error"
    assert uuid_response["sequence"] == 19


def test_rejects_coerced_integer_fields() -> None:
    string_sequence = valid_payload()
    string_sequence["sequence"] = "12"
    fractional_timestamp = valid_payload(sequence=23)
    fractional_timestamp["captured_at"] = 1788980000000.5
    with TestClient(create_app(Settings())) as client:
        sequence_response = receive_prediction(client, string_sequence)
        timestamp_response = receive_prediction(client, fractional_timestamp)
    assert sequence_response["status"] == "error"
    assert timestamp_response["status"] == "error"
    assert timestamp_response["sequence"] == 23


def test_rejects_mime_and_bad_base64() -> None:
    wrong_mime = valid_payload(sequence=20)
    png = io.BytesIO()
    Image.new("RGB", (4, 4)).save(png, format="PNG")
    wrong_mime["frames"][0] = "data:image/png;base64," + base64.b64encode(
        png.getvalue()
    ).decode("ascii")
    bad_base64 = valid_payload(sequence=21)
    bad_base64["frames"][0] = "data:image/webp;base64,%%%%"

    with TestClient(create_app(Settings())) as client:
        mime_response = receive_prediction(client, wrong_mime)
        base64_response = receive_prediction(client, bad_base64)
    assert mime_response["status"] == "error"
    assert base64_response["status"] == "error"


def test_rejects_payload_over_message_limit() -> None:
    settings = Settings(max_message_bytes=128)
    with TestClient(create_app(settings)) as client:
        response = receive_prediction(client, valid_payload())
    assert response["status"] == "error"


def test_rejects_frame_over_decoded_byte_limit() -> None:
    settings = Settings(max_frame_bytes=8)
    with TestClient(create_app(settings)) as client:
        response = receive_prediction(client, valid_payload(sequence=22))
    assert response["status"] == "error"
    assert response["sequence"] == 22


def test_request_error_does_not_close_websocket() -> None:
    invalid = valid_payload(sequence=50)
    invalid["frames"] = invalid["frames"][:-1]
    with TestClient(create_app(Settings())) as client:
        with client.websocket_connect("/ws/inference") as socket:
            socket.send_json(invalid)
            first = socket.receive_json()
            socket.send_json(valid_payload(sequence=51))
            second = socket.receive_json()
    assert first["status"] == "error"
    assert second["status"] == "ok"
    assert second["sequence"] == 51


class AlwaysBusySlots:
    def locked(self) -> bool:
        return True


def test_returns_busy_without_queueing() -> None:
    app = create_app(Settings())
    app.state.inference_slots = AlwaysBusySlots()
    with TestClient(app) as client:
        response = receive_prediction(client, valid_payload(sequence=7))
    assert response["status"] == "busy"
    assert response["sequence"] == 7


class ExplodingBackend(MockInferenceBackend):
    def predict(
        self, frames: Sequence[DecodedFrame], sequence: int
    ) -> BackendPrediction:
        raise RuntimeError("backend test failure")


def test_backend_exception_returns_error_without_logging_payload(caplog) -> None:
    app = create_app(Settings(), backend=ExplodingBackend())
    payload = valid_payload(sequence=33)
    raw_fragment = payload["frames"][0].split(",", 1)[1][:40]
    with caplog.at_level(logging.ERROR, logger="vsign.inference"):
        with TestClient(app) as client:
            response = receive_prediction(client, payload)
    assert response["status"] == "error"
    assert response["sequence"] == 33
    assert raw_fragment not in caplog.text


def test_collection_requires_explicit_enablement() -> None:
    payload = valid_payload()
    payload.update(
        {
            "duration_ms": 1600,
            "expected_label": "Chào",
            "hand": "right",
            "predicted_label": "chào",
            "predicted_confidence": 0.92,
        }
    )
    payload.pop("type")
    payload.pop("sequence")
    with TestClient(create_app(Settings())) as client:
        response = client.post("/collection/samples", json=payload)
    assert response.status_code == 403


def test_collection_saves_mp4_metadata_and_reports_counts(tmp_path: Path) -> None:
    settings = Settings(collection_enabled=True, collection_dir=tmp_path)
    payload = valid_payload()
    payload.update(
        {
            "duration_ms": 1600,
            "expected_label": "Chào",
            "hand": "left",
            "predicted_label": "ăn",
            "predicted_confidence": 0.81,
            "distance": "far",
            "lighting": "side",
            "negative_action": None,
        }
    )
    payload.pop("type")
    payload.pop("sequence")
    payload["frames"] = [image_data_url()] * 24

    with TestClient(create_app(settings)) as client:
        saved = client.post("/collection/samples", json=payload)
        summary = client.get("/collection/summary")

    assert saved.status_code == 200
    body = saved.json()
    assert body["status"] == "saved"
    assert body["expected_label"] == "Chào"
    assert body["hand"] == "left"
    assert body["label_hand_count"] == 1
    video = tmp_path / body["relative_video_path"]
    metadata = video.with_suffix(".json")
    assert video.is_file() and video.stat().st_size > 0
    assert metadata.is_file()
    stored = json.loads(metadata.read_text(encoding="utf-8"))
    assert stored["expected_label"] == "Chào"
    assert stored["predicted_label"] == "ăn"
    assert stored["distance"] == "far"
    assert stored["lighting"] == "side"
    assert stored["negative_action"] is None
    assert stored["frame_count"] == 24
    assert "frames" not in stored
    assert summary.status_code == 200
    assert summary.json()["counts"]["Chào"] == {"right": 0, "left": 1}


def test_collection_accepts_reserved_negative_label(tmp_path: Path) -> None:
    settings = Settings(collection_enabled=True, collection_dir=tmp_path)
    payload = valid_payload()
    payload.update(
        {
            "duration_ms": 1600,
            "expected_label": "Không ký hiệu",
            "hand": "right",
            "predicted_label": None,
            "predicted_confidence": None,
            "distance": "near",
            "lighting": "low",
            "negative_action": "overlap_hands",
        }
    )
    payload.pop("type")
    payload.pop("sequence")

    with TestClient(create_app(settings)) as client:
        saved = client.post("/collection/samples", json=payload)
        summary = client.get("/collection/summary")

    assert saved.status_code == 200
    assert saved.json()["expected_label"] == "Không ký hiệu"
    metadata_path = (tmp_path / saved.json()["relative_video_path"]).with_suffix(".json")
    stored = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert stored["negative_action"] == "overlap_hands"
    assert summary.json()["counts"]["Không ký hiệu"] == {"right": 1, "left": 0}


def test_collection_uses_sales_vocabulary_instead_of_runtime_labels(
    tmp_path: Path,
) -> None:
    settings = Settings(collection_enabled=True, collection_dir=tmp_path)
    payload = valid_payload()
    payload.update(
        {
            "duration_ms": 1600,
            "expected_label": "Điện thoại",
            "hand": "right",
            "predicted_label": "Chào",
            "predicted_confidence": 0.77,
            "distance": "standard",
            "lighting": "normal",
            "negative_action": None,
        }
    )
    payload.pop("type")
    payload.pop("sequence")

    with TestClient(create_app(settings)) as client:
        sales_label = client.post("/collection/samples", json=payload)
        runtime_label = client.post(
            "/collection/samples",
            json={**payload, "expected_label": "Xin lỗi"},
        )
        unknown_label = client.post(
            "/collection/samples",
            json={**payload, "expected_label": "Nhãn không hợp lệ"},
        )

    assert sales_label.status_code == 200
    assert sales_label.json()["expected_label"] == "Điện thoại"
    assert runtime_label.status_code == 422
    assert unknown_label.status_code == 422
