from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path
from typing import Any


SIGNER_PATTERN = re.compile(r"signer(\d+)", re.IGNORECASE)
EXPECTED_LABELS = set(range(1000))
SPLIT_FILES = {
    "train": "train_1_1000_center_ord1.csv",
    "validation": "val_1_1000_center_ord1.csv",
    "test": "test_1_1000_center_ord1.csv",
}
SEMANTIC_COLUMNS = {
    "gloss",
    "gloss_vi",
    "word",
    "display_text",
    "class_name",
    "label_name",
}


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise RuntimeError(f"Không đọc được {path}") from exc


def _parse_label(row: dict[str, str], path: Path) -> int:
    try:
        return int(row["label"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Label không hợp lệ trong {path}") from exc


def _parse_signer(name: str, path: Path) -> int:
    match = SIGNER_PATTERN.search(name)
    if not match:
        raise RuntimeError(f"Không đọc được signer từ '{name}' trong {path}")
    return int(match.group(1))


def _git_commit(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _has_semantic_mapping(repo: Path) -> bool:
    for path in (repo / "data").rglob("*.csv"):
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                fields = set(csv.DictReader(handle).fieldnames or [])
        except OSError:
            continue
        if fields & SEMANTIC_COLUMNS:
            return True
    return False


def audit_source(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    data_root = repo / "data" / "label_1_1000"
    full_path = data_root / "labels_1_1000.csv"
    if not full_path.is_file():
        raise RuntimeError(f"Thiếu annotation chính: {full_path}")

    full_rows = _read_rows(full_path)
    full_labels = {_parse_label(row, full_path) for row in full_rows}
    full_signers = {
        _parse_signer(row.get("name", ""), full_path) for row in full_rows
    }
    if full_labels != EXPECTED_LABELS:
        missing = sorted(EXPECTED_LABELS - full_labels)
        extra = sorted(full_labels - EXPECTED_LABELS)
        raise RuntimeError(f"Class ID không đúng 0..999; missing={missing}, extra={extra}")

    split_summary: dict[str, Any] = {}
    signer_owners: dict[int, str] = {}
    leakage: list[dict[str, Any]] = []
    for split, filename in SPLIT_FILES.items():
        path = data_root / filename
        rows = _read_rows(path)
        labels = {_parse_label(row, path) for row in rows}
        signers = sorted(
            {_parse_signer(row.get("name", ""), path) for row in rows}
        )
        duplicates = len(rows) - len({row.get("name", "") for row in rows})
        split_summary[split] = {
            "file": str(path.relative_to(repo)),
            "rows": len(rows),
            "class_count": len(labels),
            "signers": signers,
            "duplicate_video_names": duplicates,
        }
        for signer in signers:
            previous = signer_owners.get(signer)
            if previous is not None:
                leakage.append({"signer": signer, "splits": [previous, split]})
            else:
                signer_owners[signer] = split

    license_candidates = [
        name
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
        if (repo / name).is_file()
    ]
    return {
        "source_repo": "https://github.com/Etdihatthoc/Multi-VSL_WACV_2025",
        "local_repo": str(repo),
        "commit": _git_commit(repo),
        "full_annotations": {
            "file": str(full_path.relative_to(repo)),
            "rows": len(full_rows),
            "class_count": len(full_labels),
            "class_id_min": min(full_labels),
            "class_id_max": max(full_labels),
            "signer_count": len(full_signers),
        },
        "center_view_splits": split_summary,
        "signer_leakage": leakage,
        "semantic_gloss_map_found": _has_semantic_mapping(repo),
        "root_license_files": license_candidates,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit annotation/split công khai của Multi-VSL mà không đọc video"
    )
    parser.add_argument("repo", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = audit_source(args.repo)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"Đã ghi audit tại {args.output}")
    else:
        print(payload, end="")
    return 1 if result["signer_leakage"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
