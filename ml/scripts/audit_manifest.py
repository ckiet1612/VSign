from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


REQUIRED_COLUMNS = ("path", "source_class_id", "signer_id", "view", "take", "split")
VALID_SPLITS = {"train", "validation", "test"}


@dataclass(frozen=True)
class ManifestAudit:
    errors: List[str]
    distribution: Dict[Tuple[str, str, str], int]
    row_count: int


def audit_manifest(path: Path, data_root: Path | None = None) -> ManifestAudit:
    errors: List[str] = []
    distribution: Counter[Tuple[str, str, str]] = Counter()
    signer_splits = defaultdict(set)
    seen_records = {}
    root = data_root if data_root is not None else path.parent
    row_count = 0

    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            missing = [column for column in REQUIRED_COLUMNS if column not in columns]
            if missing:
                return ManifestAudit(
                    [f"Thiếu cột bắt buộc: {', '.join(missing)}"], {}, 0
                )
            for line_number, raw_row in enumerate(reader, start=2):
                row_count += 1
                row = {column: (raw_row.get(column) or "").strip() for column in REQUIRED_COLUMNS}
                empty = [column for column, value in row.items() if not value]
                if empty:
                    errors.append(f"Dòng {line_number}: thiếu giá trị {', '.join(empty)}")
                    continue
                split = row["split"]
                if split not in VALID_SPLITS:
                    errors.append(
                        f"Dòng {line_number}: split '{split}' không thuộc train/validation/test"
                    )
                signer_splits[row["signer_id"]].add(split)
                record_key = tuple(row[column] for column in REQUIRED_COLUMNS)
                if record_key in seen_records:
                    errors.append(f"Dòng {line_number}: record trùng dòng {seen_records[record_key]}")
                else:
                    seen_records[record_key] = line_number

                media_path = Path(row["path"])
                resolved_path = media_path if media_path.is_absolute() else root / media_path
                if not resolved_path.is_file():
                    errors.append(f"Dòng {line_number}: không tìm thấy file '{row['path']}'")
                distribution[(row["source_class_id"], row["signer_id"], row["view"])] += 1
    except OSError as exc:
        return ManifestAudit([f"Không đọc được file {path}: {exc}"], {}, 0)

    for signer, splits in sorted(signer_splits.items()):
        valid_signer_splits = splits & VALID_SPLITS
        if len(valid_signer_splits) > 1:
            errors.append(
                f"Signer leakage: signer '{signer}' xuất hiện trong {', '.join(sorted(valid_signer_splits))}"
            )
    return ManifestAudit(errors, dict(distribution), row_count)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit manifest VSign theo signer")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--data-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audit = audit_manifest(args.manifest, args.data_root)
    print(f"Records: {audit.row_count}")
    print("class × signer × view:")
    for (class_id, signer_id, view), count in sorted(audit.distribution.items()):
        print(f"  {class_id} × {signer_id} × {view}: {count}")
    if audit.errors:
        for error in audit.errors:
            print(f"ERROR: {error}")
        return 1
    print("OK: manifest hợp lệ và không phát hiện signer leakage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
