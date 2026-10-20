from __future__ import annotations

import pytest


def test_timing_summary_reports_sample_count_median_and_interpolated_p95() -> None:
    from ml.scripts.benchmark_personal_cpu import timing_summary
    assert timing_summary([500., 100., 300., 200., 400.]) == {
        "samples": 5, "median_ms": 300., "p95_ms": 480.,
    }


@pytest.mark.parametrize("values", [[], [float("nan")], [float("inf")], [-1.]])
def test_timing_summary_rejects_invalid_measurements(values) -> None:
    from ml.scripts.benchmark_personal_cpu import timing_summary
    with pytest.raises(ValueError):
        timing_summary(values)


def prediction():
    return {"status": "ok", "label": "yes", "confidence": .9,
            "top_k": [{"label": "yes", "confidence": .9}, {"label": "no", "confidence": .1}]}


def test_prediction_parity_allows_small_float_error_but_not_changed_acceptance() -> None:
    from ml.scripts.benchmark_personal_cpu import prediction_delta
    reference = prediction()
    changed = prediction()
    changed["confidence"] += 1e-7
    assert prediction_delta(reference, changed) == pytest.approx(1e-7)
    changed["status"] = "uncertain"
    changed["label"] = None
    changed["confidence"] = None
    with pytest.raises(ValueError, match="decision"):
        prediction_delta(reference, changed)


@pytest.mark.parametrize("change", ["order", "confidence", "nonfinite", "missing"])
def test_prediction_parity_rejects_changed_suggestions_or_probabilities(change) -> None:
    from ml.scripts.benchmark_personal_cpu import prediction_delta
    changed = prediction()
    if change == "order":
        changed["top_k"].reverse()
    elif change == "confidence":
        changed["top_k"][0]["confidence"] = .8
    elif change == "nonfinite":
        changed["top_k"][0]["confidence"] = float("nan")
    else:
        changed["top_k"].pop()
    with pytest.raises(ValueError):
        prediction_delta(prediction(), changed)
