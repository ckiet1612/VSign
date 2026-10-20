from __future__ import annotations

import csv
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

import av
import numpy as np
import pytest

from ml.scripts import split_seated_sales30 as splitter


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("10- Can_.mov", "Cần"),
        ("11-dien-thoai.mov", "Điện thoại"),
        ("12- Laptop_.mov", "Laptop"),
        ("tv.mp4", "Tivi"),
        ("14-tulanh.mov", "Tủ lạnh"),
        ("maygiat.mp4", "Máy giặt"),
        ("16- Noi com dien_.mov", "Nồi cơm điện"),
        ("17-gao.mov", "Gạo"),
        ("18- sua.mov", "Sữa"),
        ("cafe.mp4", "Cà phê"),
        ("20-moi.mov", "Mới"),
        ("21-cu.mov", "Cũ"),
        ("22-re.mov", "Rẻ"),
        ("23- dat_.mov", "Đắt"),
        ("24-sudung.mov", "Sử dụng"),
        ("25-muaban.mov", "Mua bán"),
        ("26- ngan hang_.mov", "Ngân hàng"),
        ("27-cungcap.mov", "Cung cấp"),
        ("28-thaydoi.mov", "Thay đổi"),
        ("29- tu choi_.mov", "Từ chối"),
        ("30- cam on_.mov", "Cảm ơn"),
        ("Điện thoại.mov", "Điện thoại"),
        (unicodedata.normalize("NFD", "28-Thay đổi.mov"), "Thay đổi"),
        ("chao.mov", "Chào"),
    ],
)
def test_normalizes_numbered_compact_and_unicode_labels(name: str, label: str) -> None:
    assert splitter.normalized_label(Path(name)) == label


@pytest.mark.parametrize("name", ["27-thaydoi.mov", "31-cungcap.mov", "unknown.mp4"])
def test_rejects_unknown_label_or_conflicting_number(name: str) -> None:
    with pytest.raises(ValueError):
        splitter.normalized_label(Path(name))


def test_hoai_anh_keeps_existing_signer_identity_and_filtering(tmp_path: Path) -> None:
    person = tmp_path / unicodedata.normalize("NFD", "Hoài Anh")
    person.mkdir()
    video = person / "10-can.mov"
    video.touch()
    assert splitter.normalized_person(video) == "HA"
    assert splitter.iter_sources(tmp_path, {"HA"}) == [video]


def legacy_utf8_archive(path: Path, names: list[str]) -> None:
    # Simulate the supplied ZIP: UTF-8 filename bytes with the UTF-8 flag unset.
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name in names:
            archive.writestr(name, b"original-video")
    data = bytearray(stream.getvalue())
    for signature, flags_offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
        offset = data.find(signature)
        while offset >= 0:
            flags = struct.unpack_from("<H", data, offset + flags_offset)[0]
            struct.pack_into("<H", data, offset + flags_offset, flags & ~0x800)
            offset = data.find(signature, offset + 4)
    path.write_bytes(data)


def test_extracts_zip_with_broken_unicode_and_ignores_resource_forks(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    legacy_utf8_archive(
        archive,
        [
            "21 từ còn lại/Hoài Anh/27-cungcap.mov",
            "21 từ còn lại/Như/thaydoi.mp4",
            "__MACOSX/21 từ còn lại/Hoài Anh/._27-cungcap.mov",
        ],
    )
    before = archive.read_bytes()
    root = splitter.extract_archive(archive, tmp_path / "sources")
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert files == ["HA/27-cungcap.mov", "Như/thaydoi.mp4"]
    assert (root / "HA/27-cungcap.mov").read_bytes() == b"original-video"
    assert archive.read_bytes() == before


@pytest.mark.parametrize("name", ["../HA/10-can.mov", "/HA/10-can.mov", "root/../HA/10-can.mov"])
def test_rejects_zip_traversal_before_extracting_any_file(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("root/Nhi/10-can.mov", b"valid")
        handle.writestr(name, b"unsafe")
    destination = tmp_path / "sources"
    with pytest.raises(ValueError):
        splitter.extract_archive(archive, destination)
    assert not destination.exists()


def test_rejects_duplicate_signer_label_before_extraction(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("root/HA/27-cungcap.mov", b"a")
        handle.writestr("root/Hoài Anh/cungcap.mp4", b"b")
    with pytest.raises(ValueError):
        splitter.extract_archive(archive, tmp_path / "sources")
    assert not (tmp_path / "sources").exists()


def test_cached_sources_are_reused_only_when_bytes_match_zip(tmp_path: Path) -> None:
    archive, destination = tmp_path / "input.zip", tmp_path / "sources"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("root/Nhi/10-can.mov", b"original")
    splitter.extract_archive(archive, destination)
    cached = destination / "Nhi/10-can.mov"
    first_mtime = cached.stat().st_mtime_ns
    splitter.extract_archive(archive, destination)
    assert cached.stat().st_mtime_ns == first_mtime
    cached.write_bytes(b"user-edit")
    with pytest.raises(FileExistsError):
        splitter.extract_archive(archive, destination)
    assert cached.read_bytes() == b"user-edit"


def test_rejects_source_cache_symlink(tmp_path: Path) -> None:
    archive, destination = tmp_path / "input.zip", tmp_path / "sources"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    destination.symlink_to(unrelated, target_is_directory=True)
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("root/Nhi/10-can.mov", b"video")
    with pytest.raises(ValueError):
        splitter.extract_archive(archive, destination)
    assert list(unrelated.iterdir()) == []


def test_coverage_reports_only_two_missing_nhi_words(tmp_path: Path) -> None:
    names = [
        "can", "dienthoai", "laptop", "tv", "tulanh", "maygiat", "noicomdien",
        "gao", "sua", "cafe", "moi", "cu", "re", "dat", "sudung", "muaban",
        "nganhang", "cungcap", "thaydoi", "tuchoi", "camon",
    ]
    sources = []
    for person in ["HA", "Nhi", "Như"]:
        for number, name in enumerate(names, 10):
            if person == "Nhi" and number in {27, 28}:
                continue
            sources.append(tmp_path / person / f"{name}.mp4")
    report = splitter.audit_sources(sources, expected_numbers=range(10, 31))
    assert report["source_video_count"] == 61
    assert report["expected_clips"] == 1220
    assert report["missing"] == [
        {"person": "Nhi", "number": 27, "label": "Cung cấp"},
        {"person": "Nhi", "number": 28, "label": "Thay đổi"},
    ]


@pytest.mark.parametrize(
    ("angle", "expected"),
    [(0, None), (-90, "transpose=1"), (90, "transpose=2"), (-180, "hflip,vflip")],
)
def test_rotation_metadata_is_baked_into_pixels(angle: int, expected: str | None) -> None:
    assert splitter.rotation_filter(angle) == expected


def make_video(path: Path, *, fps: int = 15) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 64, 96, "yuv420p"
        for i in range(6 * fps):
            rgb = np.zeros((96, 64, 3), dtype=np.uint8)
            rgb[5:20, 4:18] = (240, 30, 20)
            rgb[50:75, 30:50] = (20, 230, 40)
            rgb[25:40, 4 + i % 30:14 + i % 30] = (20, 30, 230)
            frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def first_frame(path: Path) -> np.ndarray:
    with av.open(str(path)) as container:
        return next(container.decode(video=0)).to_ndarray(format="rgb24")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
@pytest.mark.parametrize("direction", ["ccw", "cw"])
def test_encode_hoai_anh_rotates_actual_pixels_without_metadata(tmp_path: Path, direction: str) -> None:
    source = tmp_path / "HA" / "10-can.mp4"
    output = tmp_path / "clip.mp4"
    make_video(source)
    segment = splitter.Segment(1, 0, 1, 0, 15)
    splitter.encode_segment(source, output, segment, "HA", force=False, ha_rotation=direction)
    raw = first_frame(source)
    result = first_frame(output)
    expected = np.rot90(raw, 1 if direction == "ccw" else -1)
    assert result.shape == (64, 96, 3)
    assert np.abs(result.astype(float) - expected.astype(float)).mean() < 5
    assert splitter.probe_output(output)["rotation"] == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
@pytest.mark.parametrize("angle", [-90, 90, 180])
def test_metadata_orientation_matches_ffmpeg_autorotation(tmp_path: Path, angle: int) -> None:
    source, rotated = tmp_path / "source.mp4", tmp_path / "rotated.mp4"
    actual, expected = tmp_path / "actual.mp4", tmp_path / "expected.mp4"
    make_video(source)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(source), "-c", "copy", "-metadata:s:v:0", f"rotate={angle}", str(rotated)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(rotated), "-t", "1", "-an", "-c:v", "libx264", "-crf", "23", str(expected)],
        check=True,
    )
    splitter.encode_segment(rotated, actual, splitter.Segment(1, 0, 1, 0, 15), "Như", force=False, use_metadata=True)
    assert first_frame(actual).shape == first_frame(expected).shape
    assert np.abs(first_frame(actual).astype(float) - first_frame(expected).astype(float)).mean() < 5
    assert splitter.probe_output(actual)["rotation"] == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_split_creates_twenty_clips_and_does_not_overwrite_previous_run(tmp_path: Path) -> None:
    root, output = tmp_path / "source", tmp_path / "output"
    source = root / "Hoài Anh" / "10-can.mp4"
    make_video(source)
    before = source.read_bytes()
    summary = splitter.process(root, output, limit=None, dry_run=False, force=False)
    assert summary["clip_count"] == 20
    rows = list(csv.DictReader((output / "manifest.csv").open(encoding="utf-8")))
    assert len(rows) == 20
    assert {r["person"] for r in rows} == {"HA"}
    assert {r["label"] for r in rows} == {"Cần"}
    assert {r["orientation_filter"] for r in rows} == {"transpose=2"}
    assert all(r["sha256"] and int(r["width"]) == 96 and int(r["height"]) == 64 for r in rows)
    assert float(rows[0]["start_time"]) == 0
    assert float(rows[-1]["end_time"]) == pytest.approx(6)
    for left, right in zip(rows, rows[1:]):
        assert left["end_time"] == right["start_time"]
    assert source.read_bytes() == before
    saved_manifest = (output / "manifest.csv").read_bytes()
    with pytest.raises(FileExistsError):
        splitter.process(root, output, limit=None, dry_run=False, force=False)
    assert (output / "manifest.csv").read_bytes() == saved_manifest


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_cli_audit_zip_reports_missing_words_without_encoding(tmp_path: Path) -> None:
    source = tmp_path / "10-can.mp4"
    make_video(source)
    archive, output = tmp_path / "input.zip", tmp_path / "output"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(source, "root/Hoài Anh/10-can.mp4")
    result = subprocess.run(
        [
            sys.executable, "-m", "ml.scripts.split_seated_sales30",
            "--source-zip", str(archive), "--output-root", str(output), "--audit-only",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    audit = json.loads((output / "coverage.json").read_text(encoding="utf-8"))
    assert audit["source_video_count"] == 1
    assert audit["people"]["HA"]["present_numbers"] == [10]
    assert not (output / "clips").exists()
    assert not (output / "manifest.csv").exists()


def test_dry_run_keeps_existing_manifest_and_coverage_intact(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    make_video(source / "HA/10-can.mp4")
    output.mkdir()
    (output / "manifest.csv").write_text("existing-manifest", encoding="utf-8")
    (output / "coverage.json").write_text("existing-coverage", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable, "-m", "ml.scripts.split_seated_sales30", "--source-root", str(source),
            "--output-root", str(output), "--dry-run", "--person", "HA", "--repetitions", "4",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (output / "manifest.csv").read_text(encoding="utf-8") == "existing-manifest"
    assert (output / "coverage.json").read_text(encoding="utf-8") == "existing-coverage"
    summary = json.loads((output / "dry_run/summary.json").read_text(encoding="utf-8"))
    assert summary["clip_count"] == 4
    assert not (output / "dry_run/clips").exists()


@pytest.mark.parametrize("label,expected", [("Đắt", "Dat"), ("Điện thoại", "Dien-thoai")])
def test_output_slugs_preserve_vietnamese_d(label: str, expected: str) -> None:
    assert splitter.slug(label) == expected


def test_audit_cannot_replace_coverage_of_an_encoded_run(tmp_path: Path) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    (source / "HA").mkdir(parents=True)
    (source / "HA/10-can.mp4").touch()
    output.mkdir()
    (output / "manifest.csv").write_text("existing-manifest", encoding="utf-8")
    (output / "coverage.json").write_text("existing-coverage", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable, "-m", "ml.scripts.split_seated_sales30", "--source-root", str(source),
            "--output-root", str(output), "--audit-only", "--person", "HA",
        ], capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert (output / "coverage.json").read_text(encoding="utf-8") == "existing-coverage"


def test_audit_refuses_output_inside_source_before_writing_reports(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "HA").mkdir(parents=True)
    (source / "HA/10-can.mp4").touch()
    result = subprocess.run(
        [
            sys.executable, "-m", "ml.scripts.split_seated_sales30", "--source-root", str(source),
            "--output-root", str(source / "output"), "--audit-only",
        ], capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert not (source / "output").exists()


def test_rejects_internal_cache_signer_symlinks_before_any_extraction(tmp_path: Path) -> None:
    archive, destination = tmp_path / "input.zip", tmp_path / "sources"
    (destination / "HA").mkdir(parents=True)
    (destination / "Nhi").symlink_to(destination / "HA", target_is_directory=True)
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("root/HA/10-can.mov", b"ha")
        handle.writestr("root/Nhi/11-dienthoai.mov", b"nhi")
    with pytest.raises(ValueError):
        splitter.extract_archive(archive, destination)
    assert list((destination / "HA").iterdir()) == []


@pytest.mark.parametrize("cached", [True, False])
def test_rejects_cache_alias_even_when_signer_is_absent_from_zip(tmp_path: Path, cached: bool) -> None:
    archive, destination = tmp_path / "input.zip", tmp_path / "sources"
    (destination / "HA").mkdir(parents=True)
    (destination / "Nhi").symlink_to(destination / "HA", target_is_directory=True)
    if cached:
        (destination / "HA/10-can.mov").write_bytes(b"ha")
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("root/HA/10-can.mov", b"ha")
    with pytest.raises(ValueError):
        splitter.extract_archive(archive, destination)
    assert len(list((destination / "HA").iterdir())) == int(cached)


@pytest.mark.parametrize("symlink_at", ["clips", "clips/Can"])
def test_force_never_writes_through_clip_directory_symlinks(tmp_path: Path, symlink_at: str) -> None:
    source, output, unrelated = tmp_path / "source", tmp_path / "output", tmp_path / "unrelated"
    make_video(source / "HA/10-can.mp4")
    unrelated.mkdir()
    protected = unrelated / "HA_rep01.mp4"
    protected.write_bytes(b"keep-original")
    link = output / symlink_at
    link.parent.mkdir(parents=True)
    link.symlink_to(unrelated, target_is_directory=True)
    with pytest.raises(ValueError):
        splitter.process(source, output, limit=None, dry_run=False, force=True)
    assert protected.read_bytes() == b"keep-original"
    assert len(list(unrelated.iterdir())) == 1


@pytest.mark.parametrize("fps", [30, 60])
def test_segments_include_last_decoded_frame_above_sample_fps(tmp_path: Path, fps: int) -> None:
    source = tmp_path / "HA/10-can.mp4"
    make_video(source, fps=fps)
    segments, diagnostics = splitter.find_segments(source)
    assert segments[-1].end == pytest.approx(6, abs=1e-6)
    assert diagnostics["duration"] == pytest.approx(6, abs=1e-6)


@pytest.mark.parametrize("audit_only", [True, False])
def test_coverage_only_run_cannot_be_replaced_by_different_signer_selection(tmp_path: Path, audit_only: bool) -> None:
    source, output = tmp_path / "source", tmp_path / "output"
    for person in ["HA", "Nhi"]:
        (source / person).mkdir(parents=True)
        (source / person / "10-can.mp4").touch()
    base = [sys.executable, "-m", "ml.scripts.split_seated_sales30", "--source-root", str(source), "--output-root", str(output)]
    initial = subprocess.run([*base, "--audit-only"], capture_output=True, text=True)
    assert initial.returncode == 0, initial.stderr
    previous = (output / "coverage.json").read_bytes()
    result = subprocess.run([*base, "--person", "HA", *(["--audit-only"] if audit_only else [])], capture_output=True, text=True)
    assert result.returncode == 2
    assert (output / "coverage.json").read_bytes() == previous


@pytest.mark.parametrize("suffix", ["sales30_seated", "unused/../sales30_seated"])
def test_zip_cannot_target_old_dataset_even_with_force_and_parent_segments(tmp_path: Path, suffix: str) -> None:
    old_root = tmp_path / "ml/data/collected/sales30_seated"
    old_root.mkdir(parents=True)
    protected = old_root / "coverage.json"
    protected.write_text("old-private-coverage", encoding="utf-8")
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("root/HA/10-can.mov", b"video")
    result = subprocess.run(
        [
            sys.executable, "-m", "ml.scripts.split_seated_sales30", "--source-zip", str(archive),
            "--output-root", str(tmp_path / "ml/data/collected" / suffix), "--audit-only", "--force",
        ], cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert protected.read_text(encoding="utf-8") == "old-private-coverage"
