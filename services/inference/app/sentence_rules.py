from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Optional, Sequence


PRODUCTS = frozenset({"điện thoại", "laptop", "tivi", "tủ lạnh", "máy giặt", "nồi cơm điện", "gạo", "sữa", "cà phê"})
INSTITUTIONS = frozenset({"siêu thị", "ngân hàng"})
SUBJECTS = INSTITUTIONS | {"tôi"}
ACTIONS = frozenset({"mua", "xem", "thử", "sử dụng", "mua bán", "cung cấp", "thay đổi"})
QUALITIES = frozenset({"mới", "cũ", "rẻ", "đắt"})
DESIRES = frozenset({"muốn", "cần"})
UNCLEAR = "Cấu trúc chưa rõ · giữ nguyên thứ tự, cần kiểm tra"
REPEATED = "Có từ lặp · giữ nguyên, cần kiểm tra"


def _sentence(text: str) -> str:
    return text[0].upper() + text[1:] + "."


def _groups(words: list[str], nouns: frozenset[str]) -> Optional[str]:
    groups: list[list[str]] = []
    for word in words:
        if word in nouns:
            groups.append([word])
        elif word in QUALITIES and groups:
            groups[-1].append(word)
        else:
            return None
    if not groups:
        return None
    for group in groups:
        attributes = group[1:]
        if len(attributes) != len(set(attributes)) or {"mới", "cũ"} <= set(attributes) or {"rẻ", "đắt"} <= set(attributes):
            return None
    # A trailing qualifier after multiple bare nouns has uncertain scope.
    if len(groups) > 1 and len(groups[-1]) > 1 and any(len(group) == 1 for group in groups[:-1]):
        return None
    return ", ".join(" ".join(group) for group in groups)


def _canonical(words: list[str]) -> Optional[str]:
    if words in (["chào"], ["cảm ơn"], ["tôi", "chào"], ["tôi", "cảm ơn"]):
        return " ".join(words)
    rest = list(words)
    prefix: list[str] = []
    subject = rest.pop(0) if rest and rest[0] in SUBJECTS else None
    if subject:
        prefix.append(subject)
    if rest and rest[0] == "cho":
        prefix.append(rest.pop(0))
        if not subject and rest and rest[0] == "tôi":
            prefix.append(rest.pop(0))
        if subject and rest and rest[0] in ACTIONS:
            return None
        if rest and rest[0] in ACTIONS and rest[0] not in {"xem", "thử", "sử dụng"}:
            return None
    elif rest and rest[0] in DESIRES | {"từ chối", "có"}:
        prefix.append(rest.pop(0))
    if not rest:
        return None
    if rest[0] not in ACTIONS:
        if subject and not any(word in DESIRES | {"cho", "từ chối", "có"} for word in prefix):
            return None
        grouped = _groups(rest, PRODUCTS)
        return " ".join(prefix + [grouped]) if grouped else None
    clauses: list[str] = []
    while rest:
        action = rest.pop(0)
        if action not in ACTIONS:
            return None
        objects: list[str] = []
        while rest and rest[0] not in ACTIONS:
            objects.append(rest.pop(0))
        if not objects:
            # Bare action fragments remain drafts; don't invent their objects.
            return action if not prefix and not clauses and not rest else None
        nouns = PRODUCTS | INSTITUTIONS if action == "thay đổi" else PRODUCTS
        grouped = _groups(objects, nouns)
        if not grouped:
            return None
        clauses.append(f"{action} {grouped}")
    if len(clauses) > 1 and any(word in {"cho", "từ chối", "có"} for word in prefix):
        return None
    if "có" in prefix:
        return None
    return " ".join(prefix + [", ".join(clauses)])


def _single_phrase(words: list[str]) -> Optional[str]:
    # Only one subject/action/object: never reorder recipient or multi-object clauses.
    if any(word in INSTITUTIONS | {"cho", "từ chối", "có", "chào", "cảm ơn"} for word in words):
        if not (words[0] == "tôi" and "thay đổi" in words and sum(word in INSTITUTIONS for word in words) == 1
                and all(word not in {"cho", "từ chối", "có", "chào", "cảm ơn"} for word in words)):
            return None
    nouns = PRODUCTS | INSTITUTIONS if "thay đổi" in words else PRODUCTS
    objects = [word for word in words if word in nouns]
    actions = [word for word in words if word in ACTIONS]
    desires = [word for word in words if word in DESIRES]
    qualities = [word for word in words if word in QUALITIES]
    subjects = [word for word in words if word == "tôi"]
    if len(objects) != 1 or len(actions) > 1 or len(desires) > 1 or len(subjects) > 1:
        return None
    if len(words) != len(objects + actions + desires + qualities + subjects):
        return None
    if subjects and not actions and not desires:
        return None
    if len(qualities) != len(set(qualities)) or {"mới", "cũ"} <= set(qualities) or {"rẻ", "đắt"} <= set(qualities):
        return None
    return " ".join(subjects + desires + actions + objects + qualities)


def expanded_sentence(words: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    normalized = [unicodedata.normalize("NFC", word.strip()).lower() for word in words if word.strip()]
    warnings: list[str] = []
    if "không ký hiệu" in normalized:
        warnings.append("Đã loại nhãn Không ký hiệu khỏi câu · cần kiểm tra đoạn nhận dạng")
        normalized = [word for word in normalized if word != "không ký hiệu"]
    if not normalized:
        raise ValueError("Cần ít nhất một từ để hoàn thiện câu")
    if any(count > 1 for count in Counter(normalized).values()):
        return _sentence(" ".join(normalized)), tuple(warnings + [REPEATED])
    core = list(normalized)
    opening: list[str] = []
    closing: list[str] = []
    if len(core) > 1 and core[0] == "chào":
        opening.append(_sentence(core.pop(0)))
    if len(core) > 1 and core[-1] == "cảm ơn" and core != ["tôi", "cảm ơn"]:
        closing.append(_sentence(core.pop()))
    text = _canonical(core) or _single_phrase(core)
    if text is None:
        text = " ".join(core)
        warnings.append(UNCLEAR)
    elif "có" in core:
        warnings.append("Chưa rõ câu hỏi hay khẳng định · cần kiểm tra")
    return " ".join(opening + [_sentence(text)] + closing), tuple(warnings)
