from __future__ import annotations

import hashlib
import csv
import json

import pytest

from ml.scripts import evaluate_personal_runtime as evaluation


LABELS = ["word-a", "word-b", "Không ký hiệu"]


def sample(expected, status, label=None, raw_top1=None, reasons=()):
    return {"expected_label": expected,
            "reply": {"status": status, "label": label},
            "diagnostic": {"raw_top1": raw_top1 or label, "rejection_reasons": list(reasons)}}


def test_rates_use_all_samples_and_uncertain_suggestions_are_not_wrong_accepts():
    rows = [sample("word-a", "ok", "word-a"),
            sample("word-a", "ok", "word-b"),
            sample("word-a", "uncertain", raw_top1="word-b", reasons=["low_confidence"]),
            sample("word-a", "uncertain", raw_top1="word-a", reasons=["low_confidence"])]
    report = evaluation.summarize(rows, LABELS)
    word = report["per_word"][0]
    assert word["samples"] == 4
    assert word["correct_pct"] == 25.0
    assert word["wrong_pct"] == 25.0
    assert word["uncertain_pct"] == 50.0
    assert word["raw_top1_correct_pct"] == 50.0
    assert word["wrong_labels"] == {"word-b": 1}
    assert word["uncertain_top1"] == {"word-b": 1, "word-a": 1}
    assert word["uncertain_reasons"] == {"low_confidence": 2}
    assert word["dominant_error"] == "uncertain"


def test_missing_word_is_reported_as_unmeasured_not_zero_accuracy():
    report = evaluation.summarize([sample("word-a", "ok", "word-a")], LABELS)
    assert len(report["per_word"]) == 2
    absent = report["per_word"][1]
    assert absent["samples"] == 0
    assert absent["correct_pct"] is None
    assert absent["dominant_error"] == "no_samples"


def test_tied_errors_and_zero_errors_have_distinct_classification():
    report = evaluation.summarize([sample("word-a", "ok", "word-b"),
                                  sample("word-a", "uncertain", raw_top1="word-a"),
                                  sample("word-b", "ok", "word-b")], LABELS)
    assert report["per_word"][0]["dominant_error"] == "mixed"
    assert report["per_word"][1]["dominant_error"] == "none"


def test_api_errors_are_not_silently_counted_as_uncertain():
    with pytest.raises(ValueError, match="status"):
        evaluation.summarize([sample("word-a", "error")], LABELS)


@pytest.mark.parametrize("probabilities,reasons,winner", [
    ([.80, .19, .01], [], "word-a"),
    ([.69, .30, .01], ["low_confidence"], "word-a"),
    ([.50, .45, .05], ["low_confidence", "low_margin"], "word-a"),
    ([.10, .10, .80], ["idle_winner"], "Không ký hiệu"),
    ([.36, .24, .40], ["idle_winner", "low_confidence", "low_margin"], "Không ký hiệu"),
])
def test_diagnostics_explain_idle_confidence_and_margin_separately(probabilities, reasons, winner):
    diagnostic = evaluation.diagnose_probabilities(probabilities, LABELS, .7, .15)
    assert diagnostic["raw_top1"] == winner
    assert diagnostic["rejection_reasons"] == reasons


def manifest_row(path, split="test", group="group-a"):
    return {"path": path.name, "label_id": "0", "label": "word-a", "split": split,
            "group_id": group, "source": "standing", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_manifest_rejects_training_overlap_instead_of_reporting_it_as_held_out(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"clip")
    train = manifest_row(path, "train")
    test = {**train, "path": "second.mp4", "split": "test"}
    with pytest.raises(ValueError, match="leak"):
        evaluation.select_held_out([train, test], LABELS, tmp_path)


def test_manifest_checks_actual_held_out_bytes_against_original_hash(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"clip")
    row = manifest_row(path)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        evaluation.select_held_out([row], LABELS, tmp_path)


def test_selection_never_adds_training_samples_to_fill_missing_words(tmp_path):
    test = tmp_path / "test.mp4"
    train = tmp_path / "train.mp4"
    test.write_bytes(b"test")
    train.write_bytes(b"train")
    rows = [manifest_row(test), manifest_row(train, "train", "group-b")]
    assert evaluation.select_held_out(rows, LABELS, tmp_path) == [rows[0]]


def test_group_leakage_is_rejected_even_when_clip_hashes_are_different(tmp_path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    with pytest.raises(ValueError, match="leak"):
        evaluation.select_held_out([manifest_row(first, "train"), manifest_row(second)], LABELS, tmp_path)


@pytest.mark.parametrize("probabilities", [[1.], [float("nan"), .5, .5], [-.1, .6, .5], [.1, .2, .3]])
def test_diagnostics_reject_invalid_probabilities_instead_of_generating_reasons(probabilities):
    with pytest.raises(ValueError, match="probabilities"):
        evaluation.diagnose_probabilities(probabilities, LABELS, .7, .15)


def test_written_csv_and_json_keep_all_words_and_distinguish_uncertain_from_confusion(tmp_path):
    rows = [sample("word-a", "ok", "word-b"),
            sample("word-a", "uncertain", raw_top1="word-a", reasons=["low_confidence"])]
    for index, row in enumerate(rows):
        row.update(split="test", source="standing", path=f"clip-{index}.mp4")
        row["diagnostic"]["raw_confidence"] = .9 if index == 0 else .5
    report = {"finished_at": "2026-10-10", "metadata_before": {"model_version": "test"},
              "project_root": str(tmp_path), "samples": rows,
              "groups": {"test:standing": evaluation.summarize(rows, LABELS)},
              "metadata_unchanged": True, "protected_artifacts_unchanged": True}
    evaluation.write_reports(report, tmp_path)
    stored = json.loads((tmp_path / "report.json").read_text())
    assert stored["groups"]["test:standing"]["per_word"][0]["wrong_labels"] == {"word-b": 1}
    with (tmp_path / "errors.csv").open(encoding="utf-8-sig", newline="") as handle:
        errors = list(csv.DictReader(handle))
    assert len(errors) == 2
    assert errors[0]["accepted_label"] == "word-b"
    assert errors[1]["accepted_label"] == ""
    assert errors[1]["status"] == "uncertain"
    assert errors[1]["raw_top1"] == "word-a"
    with (tmp_path / "per_word.csv").open(encoding="utf-8-sig", newline="") as handle:
        words = list(csv.DictReader(handle))
    assert len(words) == 2
    assert words[1]["samples"] == "0"
    assert words[1]["correct_pct"] == ""
