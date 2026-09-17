from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ml.sales30_data import KaggleFile, SourceAudit, download_inventory


def _load_source_audit(path: Path) -> SourceAudit:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Source audit không hợp lệ: {path}")
    raw_files = payload.get("selected_files")
    if not isinstance(raw_files, list):
        raise ValueError(f"Source audit thiếu selected_files: {path}")
    coverage = payload.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError(f"Source audit thiếu coverage: {path}")
    normalized_coverage: dict[str, dict[str, int]] = {}
    for label, raw_counts in coverage.items():
        if not isinstance(raw_counts, Mapping):
            raise ValueError(f"Coverage không hợp lệ cho label {label}")
        normalized_coverage[str(label)] = {
            "train": int(raw_counts.get("train") or 0),
            "test": int(raw_counts.get("test") or 0),
        }
    return SourceAudit(
        dataset_ref=str(payload.get("dataset_ref") or ""),
        version=int(payload.get("version") or 0),
        license_name=str(payload.get("license") or ""),
        coverage=normalized_coverage,
        selected_files=tuple(
            KaggleFile(
                name=str(item.get("name") or ""),
                total_bytes=int(item.get("total_bytes") or 0),
            )
            for item in raw_files
            if isinstance(item, Mapping)
        ),
        blockers=tuple(str(item) for item in payload.get("blockers") or ()),
        warnings=tuple(str(item) for item in payload.get("warnings") or ()),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tải chọn lọc canonical clips cho sales-30"
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("ml/data/raw/sales30/source_audit.json"),
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("ml/data/raw/sales30")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audit = _load_source_audit(args.audit)
    result = download_inventory(audit, args.output_root)
    print(
        json.dumps(
            {
                "downloaded": result.downloaded,
                "reused": result.reused,
                "media_root": str(result.media_root),
                "index": str(result.index_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
