from __future__ import annotations

import copy
import importlib

import pytest
import torch

from ml.personal_finetune import IDLE_LABEL, load_feature_cache, save_cache


def pipeline():
    try:
        return importlib.import_module("ml.seated_personal")
    except ModuleNotFoundError:
        pytest.fail("The seated + personal training pipeline is not implemented")


def rows_fixture():
    labels = [f"word-{i}" for i in range(30)] + [IDLE_LABEL]
    rows = []
    for source, split, person in [
        ("standing", "train", "unknown"), ("standing", "validation", "unknown"),
        ("standing", "test", "unknown"), ("seated", "train", "HA"),
        ("seated", "validation", "Như"), ("personal", "train", "unknown"),
    ]:
        for label_id in range(31 if source == "personal" else 30):
            path = f"{source}/{split}/{label_id}.mp4"
            rows.append({"path": path, "source": source, "split": split, "person": person,
                         "label_id": str(label_id), "label": labels[label_id],
                         "sha256": path, "group_id": f"{source}:{split}"})
    return rows, labels


def test_standing_never_enters_training_and_old_splits_are_unchanged():
    rows, labels = rows_fixture()
    old = copy.deepcopy(rows)
    selected, indices = pipeline().select_rows(rows, labels)
    assert rows == old
    assert len(selected) == 121
    assert [rows[i] for i in indices] == selected
    assert {r["source"] for r in selected if r["split"] == "train"} == {"seated", "personal"}
    assert {r["person"] for r in selected if r["split"] == "validation"} == {"Như"}
    assert {r["source"] for r in selected if r["split"] == "test"} == {"standing"}


@pytest.mark.parametrize("change", ["personal_validation", "missing_word", "hash_leak", "group_leak"])
def test_bad_split_or_leakage_is_rejected(change):
    rows, labels = rows_fixture()
    if change == "personal_validation":
        rows[-1]["split"] = "validation"
    elif change == "missing_word":
        rows = [r for r in rows if not (r["split"] == "train" and r["label_id"] == "29")]
    elif change == "hash_leak":
        rows[-1]["sha256"] = rows[-32]["sha256"]
    else:
        rows[-1]["group_id"] = "seated:validation"
    with pytest.raises(ValueError):
        pipeline().select_rows(rows, labels)


def test_balancing_equalizes_class_mass_and_sources_within_each_class():
    rows = [{"label_id": 0, "source": "seated"}] * 2 + [
        {"label_id": 0, "source": "personal"}] * 8 + [{"label_id": 1, "source": "seated"}] * 4
    weights = pipeline().sample_weights(rows, 2)
    assert weights[:2].sum().item() == pytest.approx(weights[2:10].sum().item())
    assert weights[:10].sum().item() == pytest.approx(weights[10:].sum().item())
    assert weights.mean().item() == pytest.approx(1)


def test_cached_features_are_mapped_by_manifest_identity_and_completed_rows(tmp_path):
    rows, _ = rows_fixture()
    identity = {"manifest_sha256": "trusted"}
    path = tmp_path / "features.pt"
    cache = load_feature_cache(path, identity, len(rows), 2)
    cache["features"] = torch.arange(len(rows) * 2).reshape(len(rows), 2).float()
    cache["completed"].fill_(True)
    save_cache(path, cache)
    selected = [rows[-1], rows[0]]
    actual = pipeline().reuse_features(path, identity, rows, selected, 2)
    assert actual.tolist() == [[360., 361.], [0., 1.]]
    changed = copy.deepcopy(selected)
    changed[0]["sha256"] = "changed"
    with pytest.raises(ValueError, match="row"):
        pipeline().reuse_features(path, identity, rows, changed, 2)
    cache["completed"][-1] = False
    save_cache(path, cache)
    with pytest.raises(ValueError, match="complete"):
        pipeline().reuse_features(path, identity, rows, selected, 2)


def test_per_word_reports_distinguish_wrong_accept_from_uncertain():
    head = torch.nn.Identity()
    features = torch.tensor([[8., 0., 0.], [0., 8., 0.], [.1, 0., 0.], [0., 0., 8.]])
    report = pipeline().evaluate(head, features, torch.tensor([0, 0, 0, 2]), ["a", "b", IDLE_LABEL])
    word = report["per_class"]["a"]
    assert word["correct_accept_count"] == 1
    assert word["wrong_accept_count"] == 1
    assert word["uncertain_count"] == 1
    assert word["confusions"] == {"b": 1}
    assert report["negative_false_accept_rate"] == 0


def test_training_rejects_a_standing_sample_before_any_optimization(tmp_path):
    rows, labels = rows_fixture()
    selected, _ = pipeline().select_rows(rows, labels)
    selected[0]["split"] = "train"
    with pytest.raises(ValueError, match="Standing"):
        pipeline().train_head(torch.zeros(len(selected), 2), selected,
                              torch.nn.Linear(2, 30), torch.nn.Linear(2, 31), labels, 1, .001, tmp_path)


def test_exactly_90_of_100_negative_recognitions_pass_without_float32_rounding_loss():
    features = torch.tensor([[0., 0., 8.]] * 90 + [[8., 0., 0.]] + [[.1, 0., 0.]] * 9)
    result = pipeline().evaluate(torch.nn.Identity(), features, torch.full((100,), 2), ["a", "b", IDLE_LABEL])
    assert result["negative_recognition_rate"] < .9
    assert pipeline().negative_fit_gate(result)
    features[89] = torch.tensor([.1, 0., 0.])
    result = pipeline().evaluate(torch.nn.Identity(), features, torch.full((100,), 2), ["a", "b", IDLE_LABEL])
    assert not pipeline().negative_fit_gate(result)
