from __future__ import annotations

import csv
from pathlib import Path

from ml.scripts.import_multivsl import build_manifest, write_manifest


def _write_annotations(root: Path, filename: str, row: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        for view in ("center", "left", "right"):
            path = root / f"{split}_1_1000_{view}_ord1.csv"
            body = "name,label\n"
            if split == "train" and view == "center" and row is not None:
                body += row
            path.write_text(body, encoding="utf-8")


def test_build_manifest_matches_official_filename(tmp_path: Path) -> None:
    name = "01_User___center_device02_2_signer01_center_ord1_136.mp4"
    annotations = tmp_path / "annotations"
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / name).touch()
    _write_annotations(annotations, name, f"{name},136\n")

    result = build_manifest(annotations, videos)

    assert result.errors == []
    assert result.missing_count == 0
    assert result.rows == [
        {
            "path": name,
            "source_class_id": "136",
            "signer_id": "01",
            "view": "center",
            "take": "1",
            "split": "train",
        }
    ]


def test_partial_import_warns_but_strict_import_fails(tmp_path: Path) -> None:
    name = "01_User___center_device02_signer01_center_ord1_136.mp4"
    annotations = tmp_path / "annotations"
    videos = tmp_path / "videos"
    videos.mkdir()
    _write_annotations(annotations, name, f"{name},136\n")

    strict = build_manifest(annotations, videos)
    partial = build_manifest(annotations, videos, allow_partial=True)

    assert any("Thiếu 1/1 video" in error for error in strict.errors)
    assert any("Thiếu 1/1 video" in warning for warning in partial.warnings)
    assert any("Không tìm thấy video nào" in error for error in partial.errors)


def test_write_manifest_uses_expected_schema(tmp_path: Path) -> None:
    output = tmp_path / "manifest.csv"
    rows = [
        {
            "path": "clip.mp4",
            "source_class_id": "7",
            "signer_id": "2",
            "view": "left",
            "take": "1",
            "split": "validation",
        }
    ]

    write_manifest(output, rows)

    with output.open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == rows
