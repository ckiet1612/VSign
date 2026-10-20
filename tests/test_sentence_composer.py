from __future__ import annotations

from typing import Any, Mapping

from app.sentence import OpenAIResponsesComposer, local_sentence


def test_local_sentence_normalizes_case_and_punctuation() -> None:
    assert local_sentence(["Tôi", "Muốn", "Mua", "Điện thoại"]) == (
        "Tôi muốn mua điện thoại."
    )


def test_local_sentence_orders_a_bounded_sales_phrase_without_inventing_a_qualifier() -> None:
    assert local_sentence(["Tôi", "Tủ lạnh", "Rẻ", "Muốn", "Mua"]) == "Tôi muốn mua tủ lạnh rẻ."
    assert local_sentence(["Tôi", "Tủ lạnh", "Muốn", "Mua"]) == "Tôi muốn mua tủ lạnh."
    assert local_sentence(["Tủ lạnh", "Rẻ"]) == "Tủ lạnh rẻ."
    assert local_sentence(["Tôi", "Từ chối", "Mua", "Tủ lạnh"]) == "Tôi từ chối mua tủ lạnh."


def test_composer_falls_back_when_ai_drops_a_recognized_qualifier_or_adds_facts() -> None:
    for text in ["Tôi muốn mua tủ lạnh.", "Tôi muốn mua tủ lạnh rẻ giá 5 triệu.",
                 "Tôi không muốn mua tủ lạnh rẻ.", "Tôi muốn mua tủ lạnh rẻ và điện thoại."]:
        composer = OpenAIResponsesComposer(api_key="test", model="test", transport=lambda *_: {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]})
        result = composer.compose(["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"])
        assert result.sentence == "Tôi muốn mua tủ lạnh rẻ."
        assert result.provider == "local"


def test_openai_composer_reads_output_text_from_responses_payload() -> None:
    captured: dict[str, Any] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        captured.update(
            url=url,
            headers=dict(headers),
            payload=dict(payload),
            timeout_seconds=timeout_seconds,
        )
        return {
            "output": [
                {"type": "reasoning"},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Tôi muốn mua điện thoại.",
                        }
                    ],
                },
            ]
        }

    composer = OpenAIResponsesComposer(
        api_key="secret-test-key",
        model="test-model",
        transport=transport,
    )

    result = composer.compose(["Tôi", "Muốn", "Mua", "Điện thoại"])

    assert result.sentence == "Tôi muốn mua điện thoại."
    assert result.provider == "openai"
    assert result.model == "test-model"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer secret-test-key"
    assert captured["payload"]["model"] == "test-model"


def test_openai_composer_falls_back_without_exposing_provider_failure() -> None:
    def failing_transport(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        raise TimeoutError("provider timeout")

    composer = OpenAIResponsesComposer(
        api_key="secret-test-key",
        model="test-model",
        transport=failing_transport,
    )

    result = composer.compose(["Cảm ơn"])

    assert result.sentence == "Cảm ơn."
    assert result.provider == "local"
    assert result.model is None
