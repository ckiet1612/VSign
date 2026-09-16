from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable


CaptureKey = tuple[str, str, str, str, str]


def label_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def plan_key(row: dict[str, str]) -> CaptureKey:
    return (
        label_key(row.get("expected_label", "")),
        row.get("hand", ""),
        row.get("distance", ""),
        row.get("lighting", ""),
        row.get("negative_action", "") or "",
    )


def metadata_key(metadata: dict[str, object]) -> CaptureKey:
    return (
        label_key(str(metadata.get("expected_label", ""))),
        str(metadata.get("hand", "")),
        str(metadata.get("distance", "")),
        str(metadata.get("lighting", "")),
        str(metadata.get("negative_action") or ""),
    )


def audit_capture(
    plan_rows: Iterable[dict[str, str]], metadata: Iterable[dict[str, object]]
) -> tuple[Counter[CaptureKey], Counter[CaptureKey]]:
    planned = Counter(plan_key(row) for row in plan_rows)
    captured = Counter(metadata_key(item) for item in metadata)
    return planned - captured, captured - planned


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kiểm tra tiến độ bộ frozen-camera theo capture_plan.csv"
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path("ml/data/evaluation/frozen_camera_v4/capture_plan.csv"),
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("ml/data/evaluation/frozen_camera_v4/raw"),
    )
    args = parser.parse_args()
    with args.plan.open(encoding="utf-8", newline="") as handle:
        plan_rows = list(csv.DictReader(handle))
    metadata_paths = sorted(args.raw_dir.rglob("*.json")) if args.raw_dir.exists() else []
    metadata = [
        json.loads(path.read_text(encoding="utf-8")) for path in metadata_paths
    ]
    missing, unexpected = audit_capture(plan_rows, metadata)
    print(f"Đã thu {len(metadata_paths)}/{len(plan_rows)} metadata clip")
    print(f"Còn thiếu {sum(missing.values())}; ngoài lịch/trùng {sum(unexpected.values())}")
    if missing:
        print("Các lượt còn thiếu đầu tiên:")
        for key, count in list(missing.items())[:12]:
            print(f"- {count}× label={key[0]}, hand={key[1]}, distance={key[2]}, lighting={key[3]}, negative={key[4] or '-'}")
    if unexpected:
        print("Các lượt ngoài lịch hoặc bị trùng:")
        for key, count in list(unexpected.items())[:12]:
            print(f"- {count}× label={key[0]}, hand={key[1]}, distance={key[2]}, lighting={key[3]}, negative={key[4] or '-'}")
    if missing or unexpected:
        raise SystemExit(1)
    print("Bộ clip khớp chính xác capture plan; có thể trích và đóng băng.")


if __name__ == "__main__":
    main()
