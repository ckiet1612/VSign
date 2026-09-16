from __future__ import annotations

import random

import torch

from ml.visignlanguage import confusion_metrics, temporal_indices, topk_correct, update_confusion


def test_temporal_indices_are_deterministic_for_evaluation() -> None:
    assert temporal_indices(5, 3, training=False).tolist() == [0, 2, 4]
    assert temporal_indices(1, 4, training=False).tolist() == [0, 0, 0, 0]


def test_training_temporal_indices_stay_in_range() -> None:
    random.seed(7)
    indices = temporal_indices(9, 16, training=True)
    assert len(indices) == 16
    assert int(indices.min()) >= 0
    assert int(indices.max()) < 9


def test_classification_metrics() -> None:
    confusion = torch.zeros((3, 3), dtype=torch.int64)
    targets = torch.tensor([0, 1, 2, 2])
    predictions = torch.tensor([0, 2, 2, 2])
    update_confusion(confusion, targets, predictions)
    metrics = confusion_metrics(confusion)
    assert metrics["accuracy"] == 0.75
    assert 0.0 < metrics["macro_f1"] < 1.0

    logits = torch.tensor([[4.0, 2.0, 1.0], [0.0, 2.0, 3.0]])
    assert topk_correct(logits, torch.tensor([0, 1]), (1, 3)) == {1: 1, 3: 2}
