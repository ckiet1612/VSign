from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence
from urllib import request

from app.sentence_rules import expanded_sentence


logger = logging.getLogger("vsign.inference")


@dataclass(frozen=True)
class SentenceComposition:
    sentence: str
    provider: str
    model: Optional[str]
    warnings: tuple[str, ...] = ()


class SentenceComposer(Protocol):
    enabled: bool

    def compose(self, words: Sequence[str]) -> SentenceComposition: ...


def legacy_sentence(words: Sequence[str]) -> str:
    normalized = [word.strip().lower() for word in words if word.strip()]
    if not normalized:
        raise ValueError("Cần ít nhất một từ để hoàn thiện câu")
    products = {"điện thoại", "laptop", "tivi", "tủ lạnh", "máy giặt", "nồi cơm điện", "gạo", "sữa", "cà phê"}
    actions = {"mua", "xem", "thử", "sử dụng"}
    qualities = {"rẻ", "đắt", "mới", "cũ"}
    nouns = [word for word in normalized if word in products]
    verbs = [word for word in normalized if word in actions]
    modifiers = [word for word in normalized if word in qualities]
    desires = [word for word in normalized if word in {"muốn", "cần"}]
    # Reorder only an unambiguous sales template, preserving every input label.
    if (normalized.count("tôi") == 1 and len(nouns) == len(verbs) == 1 and len(desires) <= 1
            and len(set(modifiers)) == len(modifiers)
            and not {"rẻ", "đắt"}.issubset(modifiers) and not {"mới", "cũ"}.issubset(modifiers)
            and len(normalized) == 3 + len(desires) + len(modifiers)):
        normalized = ["tôi"] + desires + verbs + nouns + modifiers
    sentence = " ".join(normalized)
    return f"{sentence[0].upper()}{sentence[1:]}."


def local_sentence(words: Sequence[str], *, rules: str = "expanded") -> str:
    if rules == "legacy":
        return legacy_sentence(words)
    if rules != "expanded":
        raise ValueError("SENTENCE_RULES chỉ hỗ trợ expanded hoặc legacy")
    return expanded_sentence(words)[0]


class LocalSentenceComposer:
    enabled = False

    def __init__(self, *, rules: str = "expanded") -> None:
        if rules not in {"expanded", "legacy"}:
            raise ValueError("SENTENCE_RULES chỉ hỗ trợ expanded hoặc legacy")
        self.rules = rules

    def compose(self, words: Sequence[str]) -> SentenceComposition:
        sentence, warnings = (legacy_sentence(words), ()) if self.rules == "legacy" else expanded_sentence(words)
        return SentenceComposition(
            sentence=sentence,
            provider="local",
            model=None,
            warnings=warnings,
        )


def grounded_sentence(sentence: str, words: Sequence[str]) -> bool:
    def tokens(text: str) -> list[str]:
        return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", text).casefold())

    recognized = Counter(tokens(" ".join(words)))
    output = Counter(tokens(sentence))
    # Allow grammar words, never new prices, products, qualifiers or negation.
    grammar = {"cái", "chiếc", "loại", "và", "là", "của", "ở", "tại", "với", "để", "xin", "giúp"}
    if not all(output[token] == count for token, count in recognized.items()):
        return False
    if any(token not in recognized and token not in grammar for token in output):
        return False
    normalized_output = " ".join(tokens(sentence))
    return all(" ".join(tokens(word)) in normalized_output for word in words)


JsonTransport = Callable[[str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]]


def _post_json(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    http_request = request.Request(url, data=body, headers=dict(headers), method="POST")
    with request.urlopen(http_request, timeout=timeout_seconds) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("OpenAI trả về payload không hợp lệ")
    return decoded


def _extract_output_text(payload: Mapping[str, Any]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        raise RuntimeError("OpenAI response thiếu output")
    fragments: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
            ):
                fragments.append(part["text"])
    text = "".join(fragments).strip()
    if not text:
        raise RuntimeError("OpenAI response không có output_text")
    return text


class OpenAIResponsesComposer:
    enabled = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 15.0,
        transport: JsonTransport = _post_json,
        rules: str = "expanded",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.fallback = LocalSentenceComposer(rules=rules)

    def compose(self, words: Sequence[str]) -> SentenceComposition:
        payload = {
            "model": self.model,
            "instructions": (
                "Bạn hoàn thiện một câu tiếng Việt ngắn từ chuỗi từ nhận dạng ký hiệu của "
                "khách hàng trong ngữ cảnh bán hàng. Giữ nguyên ý nghĩa, không tự thêm giá, "
                "thuộc tính hoặc sản phẩm chưa có. Chỉ trả về đúng một câu, không giải thích."
            ),
            "input": json.dumps({"words": list(words)}, ensure_ascii=False),
            "max_output_tokens": 100,
        }
        try:
            response = self.transport(
                "https://api.openai.com/v1/responses",
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                payload,
                self.timeout_seconds,
            )
            sentence = _extract_output_text(response)
            if len(sentence) > 300:
                raise RuntimeError("Câu hoàn thiện vượt giới hạn")
            if not grounded_sentence(sentence, words):
                raise RuntimeError("Câu hoàn thiện thiếu từ hoặc thêm thông tin chưa nhận dạng")
            return SentenceComposition(sentence, "openai", self.model)
        except Exception as error:
            logger.warning("Sentence composition fallback (%s)", type(error).__name__)
            return self.fallback.compose(words)


def create_sentence_composer(
    api_key: Optional[str],
    model: Optional[str],
    rules: str = "expanded",
) -> SentenceComposer:
    if api_key and model:
        return OpenAIResponsesComposer(api_key=api_key, model=model, rules=rules)
    return LocalSentenceComposer(rules=rules)
