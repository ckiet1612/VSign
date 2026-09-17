from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Sequence

from ml.sales30_data import audit_sales30_manifest
from ml.visignlanguage import load_labels


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
    parser = argparse.ArgumentParser(description="Audit manifest sales-30")
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--data-root", type=Path, default=Path("ml/data/raw/sales30/media")
    )
    parser.add_argument(
        "--labels", type=Path, default=Path("contracts/v1/sales30.labels.json")
    )
    parser.add_argument("--minimum-total-clips", type=int, default=15)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audit = audit_sales30_manifest(
        args.manifest,
        args.data_root,
        load_labels(args.labels),
        minimum_total_clips=args.minimum_total_clips,
    )
    output = args.output or args.manifest.with_name("manifest_audit.json")
    _write_json(output, audit.to_dict())
    print(
        json.dumps(
            {
                "manifest": str(args.manifest),
                "valid": not audit.errors,
                "errors": list(audit.errors),
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 1 if audit.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
