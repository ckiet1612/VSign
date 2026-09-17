from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Sequence

from ml.sales30_data import audit_source, list_kaggle_files, load_source_config
from ml.visignlanguage import load_labels


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Sales-30 source audit",
        "",
        f"- Dataset: `{payload['dataset_ref']}`",
        f"- Version: `{payload['version']}`",
        f"- License: `{payload['license']}`",
        f"- Baseline ready: **{'yes' if payload['ready_for_baseline_training'] else 'no'}**",
        f"- Split strength: `{payload['split_strength']}`",
        "",
        "| Label | Train | Test | Total |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, counts in payload["coverage"].items():
        train = counts["train"]
        test = counts["test"]
        lines.append(f"| {label} | {train} | {test} | {train + test} |")
    lines.extend(["", "## Blockers", ""])
    blockers = payload["blockers"]
    lines.extend(f"- {item}" for item in blockers) if blockers else lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {item}" for item in payload["warnings"])
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit nguồn Kaggle cho sales-30")
    parser.add_argument(
        "--config", type=Path, default=Path("ml/configs/sales30_sources.json")
    )
    parser.add_argument(
        "--labels", type=Path, default=Path("contracts/v1/sales30.labels.json")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("ml/data/raw/sales30")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_source_config(args.config)
    labels = load_labels(args.labels)
    inventory = list_kaggle_files(config)
    audit = audit_source(config, labels, inventory)
    payload = audit.to_dict()
    _write_atomic(
        args.output_dir / "source_audit.json",
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    _write_atomic(args.output_dir / "source_audit.md", _markdown_report(payload))
    print(
        json.dumps(
            {
                "dataset_ref": audit.dataset_ref,
                "version": audit.version,
                "selected_files": len(audit.selected_files),
                "blockers": list(audit.blockers),
            },
            ensure_ascii=False,
        )
    )
    return 1 if audit.blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
