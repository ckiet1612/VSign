from collections import Counter

from ml.scripts.generate_v5_development_plan import FOCUS_COUNTS, build_plan


def test_v5_plan_is_targeted_balanced_and_deterministic() -> None:
    first = build_plan()
    second = build_plan()
    assert first == second
    assert len(first) == 84
    positives = Counter(
        row["expected_label"] for row in first if row["kind"] == "positive"
    )
    assert positives == FOCUS_COUNTS
    negatives = [row for row in first if row["kind"] == "negative"]
    assert len(negatives) == 24
    assert len({row["negative_action"] for row in negatives}) == 8
    assert {row["execution"] for row in first if row["kind"] == "positive"} == {
        "natural",
        "slightly_slow",
        "slightly_fast",
    }
