from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List, Sequence


REQUIRED_COLUMNS = (
    "source_class_id",
    "gloss_vi",
    "display_text",
    "region",
    "source",
)


def validate_gloss_map(path: Path) -> List[str]:
    errors: List[str] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            missing = [column for column in REQUIRED_COLUMNS if column not in columns]
            if missing:
                return [f"Thiếu cột bắt buộc: {', '.join(missing)}"]

            seen_ids = {}
            for line_number, row in enumerate(reader, start=2):
                source_id = (row.get("source_class_id") or "").strip()
                if not source_id:
                    errors.append(f"Dòng {line_number}: source_class_id bị trống")
                elif source_id in seen_ids:
                    errors.append(
                        f"Dòng {line_number}: source_class_id '{source_id}' trùng dòng {seen_ids[source_id]}"
                    )
                else:
                    seen_ids[source_id] = line_number
                if not (row.get("display_text") or "").strip():
                    errors.append(f"Dòng {line_number}: display_text bị trống")
                if not (row.get("source") or "").strip():
                    errors.append(f"Dòng {line_number}: source bị trống")
    except OSError as exc:
        return [f"Không đọc được file {path}: {exc}"]
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kiểm tra schema và dữ liệu gloss map")
    parser.add_argument("gloss_map", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = validate_gloss_map(args.gloss_map)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: gloss map hợp lệ: {args.gloss_map}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
