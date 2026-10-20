from collections import Counter
from itertools import permutations, product

import pytest

from app.config import Settings
from app.sentence import LocalSentenceComposer, local_sentence


@pytest.mark.parametrize("words,expected", [
    (["Chào"], "Chào."),
    (["Tôi", "Chào"], "Tôi chào."),
    (["Cảm ơn"], "Cảm ơn."),
    (["Tôi", "Cảm ơn"], "Tôi cảm ơn."),
    (["Tôi", "Laptop", "Mới", "Muốn"], "Tôi muốn laptop mới."),
    (["Tôi", "Tủ lạnh", "Rẻ", "Cần"], "Tôi cần tủ lạnh rẻ."),
    (["Tôi", "Laptop", "Mới", "Cần", "Xem"], "Tôi cần xem laptop mới."),
    (["Tôi", "Điện thoại", "Muốn", "Thử"], "Tôi muốn thử điện thoại."),
    (["Tủ lạnh", "Mua"], "Mua tủ lạnh."),
    (["Cho", "Tôi", "Xem", "Tivi", "Mới"], "Cho tôi xem tivi mới."),
    (["Cho", "Tôi", "Thử", "Điện thoại"], "Cho tôi thử điện thoại."),
    (["Cho", "Tôi", "Sử dụng", "Laptop"], "Cho tôi sử dụng laptop."),
    (["Cho", "Tôi", "Cà phê"], "Cho tôi cà phê."),
    (["Tôi", "Cho", "Điện thoại"], "Tôi cho điện thoại."),
    (["Cho", "Tôi", "Điện thoại"], "Cho tôi điện thoại."),
    (["Tủ lạnh", "Mới", "Rẻ"], "Tủ lạnh mới rẻ."),
    (["Tôi", "Điện thoại", "Muốn", "Mua bán"], "Tôi muốn mua bán điện thoại."),
    (["Siêu thị", "Cung cấp", "Gạo"], "Siêu thị cung cấp gạo."),
    (["Tôi", "Ngân hàng", "Muốn", "Thay đổi"], "Tôi muốn thay đổi ngân hàng."),
    (["Tôi", "Từ chối", "Laptop"], "Tôi từ chối laptop."),
    (["Tôi", "Từ chối", "Mua", "Tivi"], "Tôi từ chối mua tivi."),
    (["Tôi", "Muốn", "Mua", "Gạo", "Sữa"], "Tôi muốn mua gạo, sữa."),
    (["Tôi", "Muốn", "Mua", "Laptop", "Mới", "Điện thoại", "Cũ"],
     "Tôi muốn mua laptop mới, điện thoại cũ."),
    (["Laptop", "Mới", "Tivi", "Cũ"], "Laptop mới, tivi cũ."),
    (["Tôi", "Muốn", "Xem", "Tủ lạnh", "Thử", "Điện thoại"],
     "Tôi muốn xem tủ lạnh, thử điện thoại."),
    (["Chào", "Tôi", "Muốn", "Mua", "Sữa"], "Chào. Tôi muốn mua sữa."),
    (["Tôi", "Muốn", "Xem", "Laptop", "Cảm ơn"], "Tôi muốn xem laptop. Cảm ơn."),
    (["Chào", "Tôi", "Laptop", "Mới", "Muốn", "Cảm ơn"],
     "Chào. Tôi muốn laptop mới. Cảm ơn."),
    (["Chào", "Tôi", "Cảm ơn"], "Chào. Tôi cảm ơn."),
])
def test_expanded_rules(words, expected):
    result = LocalSentenceComposer().compose(words)
    assert result.sentence == expected
    assert result.warnings == ()
    assert result.provider == "local"
    assert result.model is None


@pytest.mark.parametrize("words,expected", [
    (["Tôi", "Cho", "Xem", "Điện thoại"], "Tôi cho xem điện thoại."),
    (["Tôi", "Tủ lạnh", "Điện thoại", "Xem", "Thử"], "Tôi tủ lạnh điện thoại xem thử."),
    (["Tôi", "Muốn", "Mua", "Laptop", "Điện thoại", "Mới"],
     "Tôi muốn mua laptop điện thoại mới."),
    (["Tôi", "Muốn", "Mua", "Laptop", "Mới", "Cũ"], "Tôi muốn mua laptop mới cũ."),
    (["Laptop", "Rẻ", "Đắt"], "Laptop rẻ đắt."),
    (["Ngân hàng", "Thay đổi", "Cung cấp"], "Ngân hàng thay đổi cung cấp."),
    (["Ngân hàng", "Muốn", "Thay đổi"], "Ngân hàng muốn thay đổi."),
    (["Ngân hàng", "Thay đổi", "Tôi"], "Ngân hàng thay đổi tôi."),
    (["Ngân hàng", "Muốn", "Thay đổi", "Tôi"], "Ngân hàng muốn thay đổi tôi."),
    (["Tôi", "Tôi", "Muốn", "Mua", "Sữa"], "Tôi tôi muốn mua sữa."),
    (["Tôi", "Muốn", "Mua", "Sữa", "Cần", "Xem", "Tivi"],
     "Tôi muốn mua sữa cần xem tivi."),
])
def test_ambiguity_keeps_original_order_with_warning(words, expected):
    result = LocalSentenceComposer().compose(words)
    assert result.sentence == expected
    assert result.warnings


def test_has_is_not_converted_to_a_question():
    for words in (["Có", "Tủ lạnh"], ["Siêu thị", "Có", "Sữa"]):
        result = LocalSentenceComposer().compose(words)
        assert result.warnings
        assert "?" not in result.sentence
        assert "không" not in result.sentence


def test_safe_single_phrase_permutations_and_vocabulary_combinations_preserve_words():
    for words in permutations(["Tôi", "Tủ lạnh", "Rẻ", "Muốn", "Mua"]):
        assert local_sentence(words) == "Tôi muốn mua tủ lạnh rẻ."
    products = ["Điện thoại", "Laptop", "Tivi", "Tủ lạnh", "Máy giặt", "Nồi cơm điện", "Gạo", "Sữa", "Cà phê"]
    actions = ["Mua", "Xem", "Thử", "Sử dụng", "Mua bán", "Cung cấp", "Thay đổi"]
    for noun, action, desire in product(products, actions, ["Muốn", "Cần"]):
        words = ["Tôi", noun, "Mới", desire, action]
        text = local_sentence(words)
        assert text == f"Tôi {desire.lower()} {action.lower()} {noun.lower()} mới."
        assert Counter(text[:-1].lower().split()) == Counter(" ".join(words).lower().split())


def test_negative_label_is_not_a_word_and_empty_input_is_rejected():
    result = LocalSentenceComposer().compose(["Tôi", "Muốn", "Không ký hiệu", "Mua", "Sữa"])
    assert result.sentence == "Tôi muốn mua sữa."
    assert result.warnings
    with pytest.raises(ValueError):
        local_sentence(["Không ký hiệu"])
    with pytest.raises(ValueError):
        local_sentence([])


def test_legacy_switch_preserves_previous_behavior():
    assert local_sentence(["Tôi", "Laptop", "Mới", "Muốn"], rules="legacy") == "Tôi laptop mới muốn."
    assert LocalSentenceComposer(rules="legacy").compose(["Tôi", "Laptop", "Mới", "Muốn"]).warnings == ()


def test_rule_setting_is_explicit_and_validated(monkeypatch):
    monkeypatch.delenv("SENTENCE_RULES", raising=False)
    assert Settings.from_env().sentence_rules == "expanded"
    monkeypatch.setenv("SENTENCE_RULES", "legacy")
    assert Settings.from_env().sentence_rules == "legacy"
    monkeypatch.setenv("SENTENCE_RULES", "unknown")
    with pytest.raises(RuntimeError, match="SENTENCE_RULES"):
        Settings.from_env()


def test_all_sequences_preserve_lexical_counts_without_added_question_or_negation():
    import random
    import re
    from contracts.v1.sales_vocabulary import SALES_30_LABELS

    randomizer = random.Random(20261010)
    for _ in range(1000):
        words = randomizer.choices(SALES_30_LABELS, k=randomizer.randint(1, 30))
        result = LocalSentenceComposer().compose(words)
        tokens = lambda text: Counter(re.findall(r"[^\W_]+", text.lower()))
        assert tokens(result.sentence) == tokens(" ".join(words))
        assert "?" not in result.sentence
