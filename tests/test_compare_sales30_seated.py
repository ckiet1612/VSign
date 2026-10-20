from __future__ import annotations

import torch

from tmp.compare_sales30_seated import confusion_report


def test_confusion_report_returns_per_label_metrics_and_totals() -> None:
    confusion = torch.tensor(
        [
            [2, 1, 0],
            [0, 3, 0],
            [1, 0, 1],
        ],
        dtype=torch.int64,
    )

    report = confusion_report(confusion, ["A", "B", "C"])

    assert report["samples"] == 8
    assert report["correct"] == 6
    assert report["accuracy"] == 0.75
    assert report["labels"]["A"]["support"] == 3
    assert report["labels"]["A"]["correct"] == 2
    assert report["labels"]["B"]["precision"] == 0.75
    assert report["labels"]["C"]["recall"] == 0.5
    assert report["macro_f1"] == (
        0.6666666666666666 + 0.8571428571428571 + 0.6666666666666666
    ) / 3
    assert report["confusion_matrix"] == [[2, 1, 0], [0, 3, 0], [1, 0, 1]]


def test_confusion_report_handles_zero_predicted_class() -> None:
    confusion = torch.tensor([[2, 0], [2, 0]], dtype=torch.int64)

    report = confusion_report(confusion, ["A", "B"])

    assert report["labels"]["B"]["precision"] == 0.0
    assert report["labels"]["B"]["recall"] == 0.0
    assert report["labels"]["B"]["f1"] == 0.0
