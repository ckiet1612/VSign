from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List


def load_labels(path: Path) -> List[str]:
    """Load output-index labels without guessing any semantic mapping."""
    if not path.is_file():
        raise RuntimeError(f"Không tìm thấy label map: {path}")

    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Label map JSON không hợp lệ: {path}") from exc
        if isinstance(payload, list):
            labels = [str(item).strip() for item in payload]
        elif isinstance(payload, dict):
            try:
                indexed: Dict[int, str] = {
                    int(key): str(value).strip() for key, value in payload.items()
                }
                labels = [indexed[index] for index in range(len(indexed))]
            except (ValueError, KeyError) as exc:
                raise RuntimeError("Label map JSON phải có index liên tiếp từ 0") from exc
        else:
            raise RuntimeError("Label map JSON phải là array hoặc object index -> label")
    elif path.suffix.lower() == ".csv":
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            raise RuntimeError(f"Không đọc được label map CSV: {path}") from exc
        if not rows or not {"source_class_id", "display_text"}.issubset(rows[0]):
            raise RuntimeError("Label map CSV cần source_class_id và display_text")
        source_ids = [(row.get("source_class_id") or "").strip() for row in rows]
        labels = [(row.get("display_text") or "").strip() for row in rows]
        if any(not source_id for source_id in source_ids) or len(set(source_ids)) != len(
            source_ids
        ):
            raise RuntimeError("Label map CSV có source_class_id trống hoặc trùng")
    else:
        raise RuntimeError("LABEL_MAP_PATH chỉ hỗ trợ file .json hoặc .csv")

    if not labels or any(not label for label in labels) or len(set(labels)) != len(labels):
        raise RuntimeError("Label map không được trống hoặc trùng display label")
    return labels
