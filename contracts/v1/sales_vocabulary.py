from __future__ import annotations

import json
from importlib.resources import files
from typing import Tuple


def _load_sales_30_labels() -> Tuple[str, ...]:
    payload = json.loads(
        files("contracts.v1")
        .joinpath("sales30.labels.json")
        .read_text(encoding="utf-8")
    )
    if (
        not isinstance(payload, list)
        or len(payload) != 30
        or any(not isinstance(label, str) or not label.strip() for label in payload)
        or len(set(payload)) != len(payload)
    ):
        raise RuntimeError("sales30.labels.json phải chứa đúng 30 nhãn duy nhất")
    return tuple(payload)


SALES_30_LABELS = _load_sales_30_labels()
