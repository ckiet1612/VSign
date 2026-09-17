from __future__ import annotations

import argparse
import csv
import json
import tempfile
from pathlib import Path
from typing import Sequence

from ml.sales30_data import (
    MANIFEST_FIELDS,
    SourceInventory,
    build_sales30_manifest,
)
from ml.scripts.download_sales30_sources import _load_source_audit
from ml.visignlanguage import load_labels


def _write_manifest(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tạo manifest sales-30")
    parser.add_argument(
        "--output-root", type=Path, default=Path("ml/data/raw/sales30")
    )
    parser.add_argument(
        "--audit", type=Path, default=Path("ml/data/raw/sales30/source_audit.json")
    )
    parser.add_argument(
        "--labels", type=Path, default=Path("contracts/v1/sales30.labels.json")
    )
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--minimum-total-clips", type=int, default=15)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_audit = _load_source_audit(args.audit)
    inventory = SourceInventory(
        dataset_ref=source_audit.dataset_ref,
        version=source_audit.version,
        license_name=source_audit.license_name,
        files=source_audit.selected_files,
    )
    rows, readiness = build_sales30_manifest(
        args.output_root,
        load_labels(args.labels),
        inventory,
        seed=args.seed,
        minimum_total_clips=args.minimum_total_clips,
    )
    manifest_path = args.output_root / "manifest.csv"
    readiness_path = args.output_root / "readiness.json"
    _write_manifest(manifest_path, [row.to_dict() for row in rows])
    _write_json(readiness_path, readiness.to_dict())
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "rows": len(rows),
                "readiness": str(readiness_path),
                "blockers": list(readiness.blockers),
            },
            ensure_ascii=False,
        )
    )
    return 1 if readiness.blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
