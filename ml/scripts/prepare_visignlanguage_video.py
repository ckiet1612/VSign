from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import pickle
import re
import shutil
import stat
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Sequence
from zipfile import ZipFile


SOURCE_ID = "star092304/ViSignLanguage-Video"
SOURCE_REVISION = "906306d7cc9c684b034bc8e96494ce9a99bc1bfc"
ARCHIVE_SHA256 = "cdfec1080e8b75cf10a972a4d7cf54fcfa4bf1b874002d28eae8405188a2a308"
MANIFEST_COLUMNS = (
    "path",
    "label_id",
    "label",
    "group_id",
    "split",
    "fps",
    "total_frames",
    "width",
    "height",
    "duration_s",
)
SUBSET_MANIFEST_COLUMNS = (
    "path",
    "label_id",
    "source_label_id",
    "label",
    "group_id",
    "split",
    "fps",
    "total_frames",
    "width",
    "height",
    "duration_s",
)
COMMON_20_LABELS = (
    "Chào",
    "Cảm ơn",
    "Xin lỗi",
    "Tôi",
    "Đi",
    "Uống",
    "Ăn",
    "Nhà",
    "Trường học",
    "Bệnh viện",
    "Giúp",
    "Đồng ý",
    "Nói",
    "Nghe",
    "Mua",
    "Đâu",
    "Nhìn",
    "Cho",
    "Biết",
    "Có thể",
)
METADATA_COLUMNS = {
    "split",
    "label",
    "filename",
    "fps",
    "total_frames",
    "width",
    "height",
    "duration_s",
}


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _PrimitiveUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        raise pickle.UnpicklingError(
            f"Không cho phép global pickle: {module}.{name}"
        )


def load_label_mapping(payload: bytes) -> Dict[str, int]:
    raw = _PrimitiveUnpickler(io.BytesIO(payload)).load()
    if not isinstance(raw, dict) or not raw:
        raise ValueError("label_mapping.pkl phải là dict không rỗng")

    mapping: Dict[str, int] = {}
    for raw_label, raw_index in raw.items():
        if not isinstance(raw_label, str) or not isinstance(raw_index, int):
            raise ValueError("label_mapping.pkl chỉ được chứa str -> int")
        label = normalize_text(raw_label)
        if not label or label in mapping:
            raise ValueError(f"Label trống hoặc trùng sau NFC: {raw_label!r}")
        mapping[label] = raw_index
    expected = set(range(len(mapping)))
    if set(mapping.values()) != expected:
        raise ValueError("Label ID phải liên tiếp từ 0 đến N-1")
    return mapping


def _safe_archive_paths(archive: ZipFile) -> Dict[str, Path]:
    normalized: Dict[str, Path] = {}
    for info in archive.infolist():
        raw = PurePosixPath(info.filename)
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError(f"Đường dẫn ZIP không an toàn: {info.filename}")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f"ZIP không được chứa symlink: {info.filename}")
        relative = Path(*(normalize_text(part) for part in raw.parts if part))
        key = relative.as_posix()
        if key in normalized:
            raise ValueError(f"Hai entry trùng sau NFC: {info.filename}")
        normalized[key] = relative
    return normalized


def extract_archive(archive_path: Path, output_root: Path) -> Path:
    target = output_root / "dataset"
    if target.exists():
        return target
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".extract-", dir=output_root))
    try:
        with ZipFile(archive_path) as archive:
            normalized = _safe_archive_paths(archive)
            for info in archive.infolist():
                destination = temporary / normalized[
                    Path(*(normalize_text(part) for part in PurePosixPath(info.filename).parts if part)).as_posix()
                ]
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        extracted = temporary / "dataset"
        if not extracted.is_dir():
            raise ValueError("Archive không có thư mục root 'dataset/'")
        extracted.replace(target)
        return target
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _group_name(filename: str) -> str:
    return re.sub(r"_\d+$", "", Path(filename).stem)


def _group_order(seed: int, label_id: int, group_name: str) -> str:
    value = f"{seed}\0{label_id}\0{group_name}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def build_manifest(
    metadata_path: Path,
    dataset_root: Path,
    label_mapping: Dict[str, int],
    *,
    seed: int = 20260910,
) -> tuple[List[Dict[str, str]], Dict[str, Any]]:
    rows: List[Dict[str, str]] = []
    seen_paths: set[str] = set()
    groups_by_label: Dict[int, set[str]] = defaultdict(set)
    metadata_label_mismatches = 0
    disk_by_filename: Dict[str, Path] = {}
    for path in (dataset_root / "train").glob("*/*.mp4"):
        if path.name in disk_by_filename:
            raise ValueError(f"Filename xuất hiện ở nhiều class: {path.name}")
        disk_by_filename[path.name] = path

    with metadata_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_columns = sorted(METADATA_COLUMNS - set(reader.fieldnames or []))
        if missing_columns:
            raise ValueError(f"Metadata thiếu cột: {', '.join(missing_columns)}")
        for line_number, raw in enumerate(reader, start=2):
            metadata_label = normalize_text(raw.get("label") or "")
            filename = (raw.get("filename") or "").strip()
            if raw.get("split") != "train" or not metadata_label or not filename:
                raise ValueError(f"Metadata dòng {line_number}: split/label/filename không hợp lệ")
            path = disk_by_filename.get(filename)
            if path is None:
                raise ValueError(f"Metadata dòng {line_number}: thiếu video có filename {filename}")
            label = normalize_text(path.parent.name)
            if label not in label_mapping:
                raise ValueError(f"Thư mục video không có trong mapping: {label}")
            if metadata_label != label:
                metadata_label_mismatches += 1
            relative = path.relative_to(dataset_root).as_posix()
            if relative in seen_paths:
                raise ValueError(f"Metadata dòng {line_number}: video bị trùng {relative}")
            seen_paths.add(relative)
            label_id = label_mapping[label]
            group_name = _group_name(filename)
            group_id = f"{label_id}:{group_name}"
            groups_by_label[label_id].add(group_id)
            rows.append(
                {
                    "path": relative,
                    "label_id": str(label_id),
                    "label": label,
                    "group_id": group_id,
                    "split": "",
                    "fps": (raw.get("fps") or "").strip(),
                    "total_frames": (raw.get("total_frames") or "").strip(),
                    "width": (raw.get("width") or "").strip(),
                    "height": (raw.get("height") or "").strip(),
                    "duration_s": (raw.get("duration_s") or "").strip(),
                }
            )

    disk_paths = {
        path.relative_to(dataset_root).as_posix()
        for path in (dataset_root / "train").glob("*/*.mp4")
    }
    if disk_paths != seen_paths:
        missing = len(seen_paths - disk_paths)
        extra = len(disk_paths - seen_paths)
        raise ValueError(f"Metadata/video không khớp: thiếu={missing}, dư={extra}")
    if set(groups_by_label) != set(label_mapping.values()):
        raise ValueError("Không đủ class trong metadata")

    split_for_group: Dict[str, str] = {}
    for label_id, group_ids in groups_by_label.items():
        ordered = sorted(
            group_ids,
            key=lambda group_id: _group_order(seed, label_id, group_id),
        )
        if len(ordered) < 3:
            raise ValueError(f"Class {label_id} có dưới 3 group, không thể chia train/val/test")
        holdout = max(1, round(len(ordered) * 0.1))
        holdout = min(holdout, (len(ordered) - 1) // 2)
        for group_id in ordered[:holdout]:
            split_for_group[group_id] = "test"
        for group_id in ordered[holdout : holdout * 2]:
            split_for_group[group_id] = "validation"
        for group_id in ordered[holdout * 2 :]:
            split_for_group[group_id] = "train"

    for row in rows:
        row["split"] = split_for_group[row["group_id"]]
    rows.sort(key=lambda row: (row["split"], int(row["label_id"]), row["path"]))

    split_counts = Counter(row["split"] for row in rows)
    label_counts = Counter(row["label"] for row in rows)
    group_splits: Dict[str, set[str]] = defaultdict(set)
    for row in rows:
        group_splits[row["group_id"]].add(row["split"])
    leakage = sorted(group for group, splits in group_splits.items() if len(splits) > 1)
    if leakage:
        raise ValueError(f"Group leakage: {leakage[:5]}")

    audit = {
        "source": SOURCE_ID,
        "source_revision": SOURCE_REVISION,
        "license": "CC-BY-4.0",
        "seed": seed,
        "train_video_count": len(rows),
        "class_count": len(label_mapping),
        "group_count": len(group_splits),
        "split_counts": dict(sorted(split_counts.items())),
        "min_samples_per_class": min(label_counts.values()),
        "max_samples_per_class": max(label_counts.values()),
        "metadata_label_mismatch_count": metadata_label_mismatches,
        "group_leakage": leakage,
        "caveats": [
            "Nguồn không cung cấp signer_id; split này không đo signer-independent generalization.",
            "public_test/private_test không có nhãn nên không dùng để chọn model.",
        ],
    }
    return rows, audit


def write_outputs(
    manifest_path: Path,
    label_map_path: Path,
    audit_path: Path,
    rows: List[Dict[str, str]],
    label_mapping: Dict[str, int],
    audit: Dict[str, Any],
) -> None:
    for path in (manifest_path, label_map_path, audit_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    labels = [label for label, _ in sorted(label_mapping.items(), key=lambda item: item[1])]
    label_map_path.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_common_20(output_root: Path, rows: List[Dict[str, str]]) -> Dict[str, Any]:
    available = {row["label"] for row in rows}
    missing = [label for label in COMMON_20_LABELS if label not in available]
    if missing:
        raise ValueError(f"Common-20 thiếu label: {', '.join(missing)}")

    subset_label_ids = {
        label: index for index, label in enumerate(COMMON_20_LABELS)
    }
    subset: List[Dict[str, str]] = []
    for row in rows:
        label = row["label"]
        if label not in subset_label_ids:
            continue
        item = dict(row)
        item["source_label_id"] = item["label_id"]
        item["label_id"] = str(subset_label_ids[label])
        subset.append(item)
    subset.sort(key=lambda row: (row["split"], int(row["label_id"]), row["path"]))

    manifest_path = output_root / "common20_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUBSET_MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(subset)
    (output_root / "common20_label_map.json").write_text(
        json.dumps(list(COMMON_20_LABELS), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    common_20_audit = {
        "labels": list(COMMON_20_LABELS),
        "video_count": len(subset),
        "split_counts": dict(
            sorted(Counter(row["split"] for row in subset).items())
        ),
        "per_class_counts": dict(
            sorted(Counter(row["label"] for row in subset).items())
        ),
    }
    (output_root / "common20_audit.json").write_text(
        json.dumps(common_20_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return common_20_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Xác minh, giải nén và tạo split cho ViSignLanguage-Video"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260910)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    actual_sha = sha256_file(args.archive)
    if actual_sha != ARCHIVE_SHA256:
        print(f"ERROR: SHA256 không khớp: {actual_sha}")
        return 1
    with ZipFile(args.archive) as archive:
        _safe_archive_paths(archive)
        label_mapping = load_label_mapping(archive.read("dataset/label_mapping.pkl"))
    if len(label_mapping) != 100:
        print(f"ERROR: cần 100 class, nhận được {len(label_mapping)}")
        return 1

    dataset_root = extract_archive(args.archive, args.output_root)
    rows, audit = build_manifest(
        args.metadata,
        dataset_root,
        label_mapping,
        seed=args.seed,
    )
    audit["archive_sha256"] = actual_sha
    write_outputs(
        args.output_root / "manifest.csv",
        args.output_root / "label_map.json",
        args.output_root / "audit.json",
        rows,
        label_mapping,
        audit,
    )
    common_20_audit = write_common_20(args.output_root, rows)
    print(f"OK: {len(rows)} video train, {len(label_mapping)} class")
    print(f"Split: {audit['split_counts']}")
    print(f"Common-20: {common_20_audit['video_count']} video")
    print(f"Manifest: {args.output_root / 'manifest.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
