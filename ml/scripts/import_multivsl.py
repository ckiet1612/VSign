from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence


MANIFEST_COLUMNS = (
    "path",
    "source_class_id",
    "signer_id",
    "view",
    "take",
    "split",
)
SPLITS = (("train", "train"), ("val", "validation"), ("test", "test"))
VIEWS = ("center", "left", "right")
FILENAME_PATTERN = re.compile(
    r"_(?P<view>center|left|right)_device.*?_signer(?P<signer>\d+)_"
    r"(?P=view)_ord(?P<take>\d+)_(?P<label>\d+)\.mp4$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImportResult:
    rows: List[Dict[str, str]]
    annotation_count: int
    missing_count: int
    errors: List[str]
    warnings: List[str]


def _index_videos(videos_root: Path) -> tuple[Dict[str, Path], List[str]]:
    index: Dict[str, Path] = {}
    errors: List[str] = []
    for path in sorted(videos_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".mp4":
            continue
        previous = index.get(path.name)
        if previous is not None:
            errors.append(
                f"Trùng basename video '{path.name}': '{previous}' và '{path}'"
            )
            continue
        index[path.name] = path
    return index, errors


def build_manifest(
    annotation_dir: Path,
    videos_root: Path,
    *,
    allow_partial: bool = False,
) -> ImportResult:
    video_index, errors = _index_videos(videos_root)
    rows: List[Dict[str, str]] = []
    warnings: List[str] = []
    missing: List[str] = []
    seen_names: set[str] = set()
    annotation_count = 0

    for source_split, target_split in SPLITS:
        for expected_view in VIEWS:
            annotation_path = (
                annotation_dir
                / f"{source_split}_1_1000_{expected_view}_ord1.csv"
            )
            if not annotation_path.is_file():
                errors.append(f"Thiếu annotation: {annotation_path}")
                continue

            try:
                with annotation_path.open(encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    columns = reader.fieldnames or []
                    if "name" not in columns or "label" not in columns:
                        errors.append(
                            f"{annotation_path}: cần có cột 'name' và 'label'"
                        )
                        continue
                    for line_number, raw_row in enumerate(reader, start=2):
                        annotation_count += 1
                        name = (raw_row.get("name") or "").strip()
                        label = (raw_row.get("label") or "").strip()
                        if not name or not label:
                            errors.append(
                                f"{annotation_path}:{line_number}: name/label bị trống"
                            )
                            continue
                        if name in seen_names:
                            errors.append(
                                f"{annotation_path}:{line_number}: video '{name}' lặp giữa các split/view"
                            )
                            continue
                        seen_names.add(name)

                        match = FILENAME_PATTERN.search(name)
                        if match is None:
                            errors.append(
                                f"{annotation_path}:{line_number}: không parse được filename '{name}'"
                            )
                            continue
                        parsed = match.groupdict()
                        if parsed["view"].lower() != expected_view:
                            errors.append(
                                f"{annotation_path}:{line_number}: view trong filename không phải '{expected_view}'"
                            )
                            continue
                        if parsed["label"] != label:
                            errors.append(
                                f"{annotation_path}:{line_number}: label CSV {label} khác filename {parsed['label']}"
                            )
                            continue

                        video_path = video_index.get(name)
                        if video_path is None:
                            missing.append(name)
                            continue
                        rows.append(
                            {
                                "path": video_path.relative_to(videos_root).as_posix(),
                                "source_class_id": label,
                                "signer_id": parsed["signer"],
                                "view": expected_view,
                                "take": parsed["take"],
                                "split": target_split,
                            }
                        )
            except OSError as exc:
                errors.append(f"Không đọc được {annotation_path}: {exc}")

    if missing:
        sample = ", ".join(missing[:5])
        message = (
            f"Thiếu {len(missing)}/{annotation_count} video theo official annotation"
            f"; ví dụ: {sample}"
        )
        if allow_partial:
            warnings.append(message)
        else:
            errors.append(message)
    if not rows:
        errors.append("Không tìm thấy video nào khớp official annotation")

    rows.sort(key=lambda row: (row["split"], row["view"], row["path"]))
    return ImportResult(rows, annotation_count, len(missing), errors, warnings)


def write_manifest(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Đối chiếu video được cấp với official Multi-VSL 1000-class split"
    )
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--videos", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Cho phép tạo manifest cho bộ demo/partial; full training không dùng cờ này",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_manifest(
        args.annotations,
        args.videos,
        allow_partial=args.allow_partial,
    )
    print(f"Annotations: {result.annotation_count}")
    print(f"Matched videos: {len(result.rows)}")
    print(f"Missing videos: {result.missing_count}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    if result.errors:
        for error in result.errors:
            print(f"ERROR: {error}")
        return 1
    write_manifest(args.output, result.rows)
    print(f"OK: đã ghi manifest tại {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
