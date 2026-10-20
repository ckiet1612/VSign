"""Split long seated Sales30 recordings into independently decodable clips.

The input recordings contain repeated executions of one label.  This tool uses
RGB motion energy to place exactly N-1 boundaries at quiet points, then encodes
each segment with a physically normalized orientation.  Source recordings are
never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

import av
import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d

from contracts.v1.sales_vocabulary import SALES_30_LABELS


EXPECTED_REPETITIONS = 20
TARGET_SAMPLE_FPS = 15.0
MOTION_SIZE = (64, 64)
SEGMENTATION_VERSION = "motion-dp-v2"

LEGACY_OUTPUT = Path("ml/data/collected/sales30_seated")
REMAINING_OUTPUT = Path("ml/data/collected/sales30_seated_remaining21")
VIDEO_SUFFIXES = {".mov", ".mp4"}


def reject_symlinks(path: Path) -> None:
    for component in (path.absolute(), *path.absolute().parents):
        if component.is_symlink():
            raise ValueError(f"Không ghi dữ liệu qua symlink: {component}")


def validate_roots(source_root: Path, output_root: Path) -> None:
    source, output = source_root.resolve(), output_root.resolve()
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError("Thư mục nguồn và đầu ra phải tách biệt")


def text_key(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_value.lower())


LABELS = {text_key(label): label for label in SALES_30_LABELS}
LABELS.update({"tv": "Tivi", "cafe": "Cà phê"})
PERSON_ALIASES = {"ha": "HA", "hoaianh": "HA", "nhi": "Nhi", "nhu": "Như"}

# These recordings were captured in three different phone orientations.  The
# transforms rotate pixels, so the generated clips do not rely on container
# rotation metadata at training time.
ORIENTATION_FILTERS = {
    "HA": "transpose=2",
    "Nhi": "hflip,vflip",
    "Như": None,
}


@dataclass(frozen=True)
class Segment:
    repetition: int
    start: float
    end: float
    start_sample: int
    end_sample: int

    @property
    def duration(self) -> float:
        return self.end - self.start


def slug(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return "-".join("".join(ch if ch.isalnum() else "-" for ch in ascii_value).split("-")) or "label"


def normalized_person(path: Path) -> str:
    try:
        return PERSON_ALIASES[text_key(path.parent.name)]
    except KeyError as error:
        raise ValueError(f"Người quay chưa có orientation transform: {path.parent.name!r}") from error


def normalized_label(path: Path) -> str:
    stem = unicodedata.normalize("NFC", path.stem).strip().rstrip("_")
    numbered = re.match(r"^(\d+)\s*[-_. ]\s*(.+)$", stem)
    number = int(numbered.group(1)) if numbered else None
    key = text_key(numbered.group(2) if numbered else stem)
    try:
        label = LABELS[key]
    except KeyError as error:
        raise ValueError(f"Không nhận diện được label từ tên file: {path.name!r}") from error
    if number is not None and (not 1 <= number <= 30 or SALES_30_LABELS[number - 1] != label):
        raise ValueError(f"Số thứ tự không khớp nhãn {label!r}: {path.name!r}")
    return label


def iter_sources(source_root: Path, people: set[str] | None = None) -> list[Path]:
    paths = sorted(
        path
        for path in source_root.glob("*/*")
        if path.is_file()
        and not path.name.startswith("._")
        and path.suffix.lower() in VIDEO_SUFFIXES
        and (people is None or normalized_person(path) in people)
    )
    if not paths:
        raise ValueError(f"Không tìm thấy video trong {source_root}")
    return paths


def decoded_zip_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if not info.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("utf-8")
        except UnicodeError:
            pass
    return unicodedata.normalize("NFC", name)


def extract_archive(archive_path: Path, destination: Path) -> Path:
    """Preflight all members before extracting only canonical, known videos."""
    reject_symlinks(destination)
    for path in destination.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Cache nguồn chứa symlink: {path}")
    with zipfile.ZipFile(archive_path) as archive:
        members: list[tuple[zipfile.ZipInfo, Path]] = []
        identities: set[tuple[str, str]] = set()
        for info in archive.infolist():
            name = decoded_zip_name(info)
            path = PurePosixPath(name)
            if info.is_dir() or "__MACOSX" in path.parts or path.name.startswith("._"):
                continue
            if path.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            if (
                path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise ValueError(f"Đường dẫn ZIP không an toàn: {name!r}")
            source = Path(name)
            person, label = normalized_person(source), normalized_label(source)
            identity = (person, label)
            if identity in identities:
                raise ValueError(f"Trùng video cho người/nhãn: {identity}")
            identities.add(identity)
            members.append((info, Path(person) / path.name))
        if not members:
            raise ValueError("ZIP không chứa video được hỗ trợ")
        if sum(info.file_size for info, _ in members) > 10 * 1024**3:
            raise ValueError("ZIP vượt giới hạn giải nén 10 GiB")
        root = destination.resolve()
        # Existing cache entries must match; never overwrite modified source media.
        for info, relative in members:
            output = destination / relative
            reject_symlinks(output)
            if not output.resolve().is_relative_to(root) or output.is_symlink():
                raise ValueError(f"Cache nguồn không an toàn: {output}")
            if output.exists():
                digest = hashlib.sha256()
                with archive.open(info) as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                if sha256_file(output) != digest.hexdigest():
                    raise FileExistsError(f"Cache nguồn khác ZIP, hãy dùng output-root mới: {output}")
        expected = {relative.as_posix() for _, relative in members}
        if destination.exists():
            actual = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
            if actual - expected:
                raise FileExistsError("Cache chứa tệp ngoài ZIP, hãy dùng output-root mới")
        for info, relative in members:
            output = destination / relative
            if output.exists():
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                try:
                    with archive.open(info) as source:
                        shutil.copyfileobj(source, handle, length=1024 * 1024)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            temporary.replace(output)
    return destination


def audit_sources(
    sources: Sequence[Path], *, expected_numbers: Iterable[int] = range(1, 31),
    repetitions: int = EXPECTED_REPETITIONS, people: Iterable[str] = ORIENTATION_FILTERS,
) -> dict[str, object]:
    if repetitions <= 0:
        raise ValueError("Số lần lặp phải lớn hơn 0")
    numbers = list(expected_numbers)
    if any(not 1 <= number <= 30 for number in numbers):
        raise ValueError("Số thứ tự nhãn phải nằm trong 1..30")
    present: dict[str, set[int]] = {person: set() for person in people}
    records: list[dict[str, object]] = []
    for source in sources:
        person, label = normalized_person(source), normalized_label(source)
        number = SALES_30_LABELS.index(label) + 1
        if number in present.setdefault(person, set()):
            raise ValueError(f"Trùng video cho người/nhãn: {person}/{label}")
        present[person].add(number)
        records.append({"person": person, "number": number, "label": label, "source_video": str(source)})
    missing = [
        {"person": person, "number": number, "label": SALES_30_LABELS[number - 1]}
        for person, labels in present.items() for number in numbers if number not in labels
    ]
    return {
        "source_video_count": len(sources), "expected_clips": len(sources) * repetitions,
        "repetitions": repetitions,
        "people": {p: {"video_count": len(labels), "present_numbers": sorted(labels)} for p, labels in present.items()},
        "missing": missing, "videos": records,
    }


def rotation_filter(angle: float) -> str | None:
    normalized = angle % 360
    for rotation, video_filter in [(0, None), (90, "transpose=2"), (180, "hflip,vflip"), (270, "transpose=1")]:
        if math.isclose(normalized, rotation, abs_tol=0.01) or (rotation == 0 and math.isclose(normalized, 360, abs_tol=0.01)):
            return video_filter
    raise ValueError(f"Góc xoay không được hỗ trợ: {angle}")


def source_orientation(
    source: Path, person: str, *, ha_rotation: str = "ccw", use_metadata: bool = False,
) -> str | None:
    if person == "HA":
        if ha_rotation not in {"cw", "ccw"}:
            raise ValueError("Chiều xoay HA phải là cw hoặc ccw")
        return "transpose=1" if ha_rotation == "cw" else "transpose=2"
    if use_metadata:
        return rotation_filter(float(probe_output(source)["rotation"]))
    return ORIENTATION_FILTERS[person]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def decode_motion_signal(path: Path, repetitions: int = EXPECTED_REPETITIONS) -> tuple[np.ndarray, np.ndarray, float, int, int, float]:
    """Return sampled times, smoothed RGB motion energy, source fps and size."""

    images: list[np.ndarray] = []
    times: list[float] = []
    end_time = 0.0
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        source_fps = float(stream.average_rate or TARGET_SAMPLE_FPS)
        width, height = int(stream.width), int(stream.height)
        step = max(1, int(round(source_fps / TARGET_SAMPLE_FPS)))
        for frame_index, frame in enumerate(container.decode(video=0)):
            frame_time = float(frame.time) if frame.time is not None else frame_index / source_fps
            duration = getattr(frame, "duration", None)
            frame_duration = float(duration * stream.time_base) if duration and stream.time_base else 1.0 / source_fps
            end_time = max(end_time, frame_time + frame_duration)
            if frame_index % step:
                continue
            gray = frame.to_ndarray(format="gray")
            frame_height, frame_width = gray.shape
            y0, y1 = int(frame_height * 0.05), int(frame_height * 0.95)
            x0, x1 = int(frame_width * 0.05), int(frame_width * 0.95)
            gray = cv2.resize(
                gray[y0:y1, x0:x1], MOTION_SIZE, interpolation=cv2.INTER_AREA
            ).astype(np.float32)
            images.append(gray)
            times.append(frame_time)

    if len(images) < repetitions + 1:
        raise ValueError(f"Video quá ngắn để tách {repetitions} lần lặp: {path}")
    array = np.stack(images)
    frame_diffs = np.mean(np.abs(array[1:] - array[:-1]), axis=(1, 2))
    signal = gaussian_filter1d(np.r_[frame_diffs[0], frame_diffs], sigma=1.5)
    return np.asarray(times), signal, source_fps, width, height, end_time


def _dynamic_boundaries(signal: np.ndarray, segment_count: int) -> list[int]:
    """Select low-motion boundaries with a duration regularizer.

    The source recordings are known to contain exactly 20 repetitions.  A
    constrained dynamic program is more stable than independently selecting
    local minima when one gesture has multiple movement peaks.
    """

    sample_count = len(signal)
    if sample_count < segment_count + 1:
        raise ValueError("Không đủ mẫu chuyển động để tìm boundaries")
    average_gap = (sample_count - 1) / segment_count
    min_gap = max(3, int(math.floor(average_gap * 0.45)))
    max_gap = max(min_gap + 1, int(math.ceil(average_gap * 1.75)))
    scaled_signal = (signal - float(signal.min())) / (float(np.ptp(signal)) + 1e-6)

    infinity = float("inf")
    costs = np.full((segment_count, sample_count), infinity, dtype=np.float64)
    back = np.full((segment_count, sample_count), -1, dtype=np.int64)
    costs[0, 0] = 0.0

    for boundary_number in range(1, segment_count):
        lower = boundary_number * min_gap
        upper = sample_count - 1 - (segment_count - boundary_number) * min_gap
        for current in range(lower, upper + 1):
            previous_lower = max((boundary_number - 1) * min_gap, current - max_gap)
            previous_upper = min((boundary_number - 1) * max_gap, current - min_gap)
            if previous_lower > previous_upper:
                continue
            previous = np.arange(previous_lower, previous_upper + 1)
            relative_gap = (current - previous) / average_gap
            candidates = costs[boundary_number - 1, previous] + 0.45 * (relative_gap - 1.0) ** 2
            selected = int(np.argmin(candidates))
            predecessor = int(previous[selected])
            costs[boundary_number, current] = float(candidates[selected]) + float(scaled_signal[current])
            back[boundary_number, current] = predecessor

    last_previous = np.arange(
        (segment_count - 1) * min_gap,
        min((segment_count - 1) * max_gap, sample_count - 2) + 1,
    )
    final_gap = (sample_count - 1 - last_previous) / average_gap
    final_costs = costs[segment_count - 1, last_previous] + 0.45 * (final_gap - 1.0) ** 2
    if not len(last_previous) or not np.isfinite(final_costs).any():
        raise ValueError("Không tìm được đủ boundaries hợp lệ")
    current = int(last_previous[int(np.argmin(final_costs))])
    boundaries = [sample_count - 1, current]
    for boundary_number in range(segment_count - 1, 0, -1):
        current = int(back[boundary_number, current])
        if current < 0:
            raise ValueError("Dynamic program không truy vết được boundaries")
        boundaries.append(current)
    boundaries = [0] + list(reversed(boundaries[:-1]))
    if len(boundaries) != segment_count + 1 or len(set(boundaries)) != len(boundaries):
        raise ValueError("Số boundaries không đúng")
    return boundaries


def find_segments(path: Path, repetitions: int = EXPECTED_REPETITIONS) -> tuple[list[Segment], dict[str, object]]:
    if repetitions <= 0:
        raise ValueError("Số lần lặp phải lớn hơn 0")
    times, signal, source_fps, width, height, end_time = decode_motion_signal(path, repetitions)
    boundaries = _dynamic_boundaries(signal, repetitions)
    segments = [
        Segment(
            repetition=index + 1,
            start=float(times[start_index]),
            end=end_time if end_index == len(times) - 1 else float(times[end_index]),
            start_sample=start_index,
            end_sample=end_index,
        )
        for index, (start_index, end_index) in enumerate(zip(boundaries[:-1], boundaries[1:]))
    ]
    durations = [segment.duration for segment in segments]
    diagnostics = {
        "source_fps": source_fps,
        "source_width": width,
        "source_height": height,
        "sample_count": len(times),
        "duration": end_time,
        "segment_count": len(segments),
        "min_segment_duration": min(durations),
        "max_segment_duration": max(durations),
        "mean_segment_duration": sum(durations) / len(durations),
        "boundaries": [float(times[index]) for index in boundaries[:-1]] + [end_time],
        "segmentation_version": SEGMENTATION_VERSION,
    }
    return segments, diagnostics


def encode_segment(
    source: Path, output: Path, segment: Segment, person: str, *, force: bool,
    ha_rotation: str = "ccw", use_metadata: bool = False, video_filter: str | None = None,
) -> None:
    reject_symlinks(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not force:
        raise FileExistsError(f"Clip đã tồn tại: {output}")
    duration = max(0.1, segment.duration)
    if video_filter is None:
        video_filter = source_orientation(source, person, ha_rotation=ha_rotation, use_metadata=use_metadata)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".mp4", delete=False) as handle:
        temporary = Path(handle.name)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-noautorotate",
        "-display_rotation",
        "0",
        "-ss",
        f"{segment.start:.6f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.6f}",
    ]
    if video_filter:
        command.extend(["-vf", video_filter])
    command.extend(
        [
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-metadata:s:v:0",
            "rotate=0",
            "-movflags",
            "+faststart",
            "-y",
            str(temporary),
        ]
    )
    try:
        subprocess.run(command, check=True)
        if output.exists() and not force:
            raise FileExistsError(f"Clip đã tồn tại: {output}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def probe_output(path: Path) -> dict[str, object]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,codec_name,pix_fmt:stream_side_data=rotation",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    payload = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
    stream = payload["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "codec": str(stream["codec_name"]),
        "pix_fmt": str(stream.get("pix_fmt") or ""),
        "duration": float(payload["format"]["duration"]),
        "rotation": next((item["rotation"] for item in stream.get("side_data_list", []) if "rotation" in item), 0),
    }


def write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: Sequence[str]) -> None:
    reject_symlinks(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", newline="", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(path)


def write_json(path: Path, payload: object) -> None:
    reject_symlinks(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(path)


def ensure_output_available(output_root: Path, *, force: bool) -> None:
    reject_symlinks(output_root)
    for path in output_root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Đầu ra chứa symlink: {path}")
    generated = [output_root / name for name in ("manifest.csv", "video_reports.json", "summary.json")]
    if not force and (any(path.exists() for path in generated) or any((output_root / "clips").glob("**/*.mp4"))):
        raise FileExistsError(f"Đầu ra đã có clip/báo cáo: {output_root}. Dùng thư mục mới hoặc --force.")


def process(
    source_root: Path,
    output_root: Path,
    *,
    limit: int | None,
    dry_run: bool,
    force: bool,
    people: set[str] | None = None,
    repetitions: int = EXPECTED_REPETITIONS,
    ha_rotation: str = "ccw",
    use_metadata: bool = False,
) -> dict[str, object]:
    if repetitions <= 0 or (limit is not None and limit <= 0):
        raise ValueError("Số lần lặp và limit phải lớn hơn 0")
    validate_roots(source_root, output_root)
    ensure_output_available(output_root, force=force)
    sources = iter_sources(source_root, people)
    audit_sources(sources, repetitions=repetitions, people=sorted(people) if people else ORIENTATION_FILTERS)
    if limit is not None:
        sources = sources[:limit]
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, object]] = []
    video_reports: list[dict[str, object]] = []

    for source in sources:
        person = normalized_person(source)
        label = normalized_label(source)
        video_filter = source_orientation(source, person, ha_rotation=ha_rotation, use_metadata=use_metadata)
        segments, diagnostics = find_segments(source, repetitions)
        source_hash = sha256_file(source)
        source_relative = source.relative_to(source_root).as_posix()
        report = {
            "person": person,
            "label": label,
            "source_video": source_relative,
            "source_sha256": source_hash,
            "orientation_filter": video_filter or "none",
            **diagnostics,
        }
        video_reports.append(report)

        for segment in segments:
            output_relative = Path("clips") / slug(label) / f"{slug(person)}_rep{segment.repetition:02d}.mp4"
            output_path = output_root / output_relative
            if not dry_run:
                encode_segment(
                    source, output_path, segment, person, force=force,
                    ha_rotation=ha_rotation, use_metadata=use_metadata, video_filter=video_filter,
                )
                media = probe_output(output_path)
            else:
                media = {
                    "width": "",
                    "height": "",
                    "codec": "",
                    "pix_fmt": "",
                    "duration": segment.duration,
                }
            output_hash = sha256_file(output_path) if not dry_run and output_path.exists() else ""
            manifest_rows.append(
                {
                    "person": person,
                    "label": label,
                    "repetition": segment.repetition,
                    "source_video": source_relative,
                    "source_sha256": source_hash,
                    "start_time": f"{segment.start:.6f}",
                    "end_time": f"{segment.end:.6f}",
                    "duration": f"{segment.duration:.6f}",
                    "output_path": output_relative.as_posix(),
                    "sha256": output_hash,
                    "width": media["width"],
                    "height": media["height"],
                    "codec": media["codec"],
                    "pix_fmt": media["pix_fmt"],
                    "encoded_duration": media["duration"],
                    "orientation_filter": video_filter or "none",
                    "segmentation_version": SEGMENTATION_VERSION,
                }
            )
        print(f"{person}/{label}: {len(segments)} clips; {diagnostics['min_segment_duration']:.2f}-{diagnostics['max_segment_duration']:.2f}s", flush=True)

    fields = [
        "person", "label", "repetition", "source_video", "source_sha256",
        "start_time", "end_time", "duration", "output_path", "sha256",
        "width", "height", "codec", "pix_fmt", "encoded_duration",
        "orientation_filter", "segmentation_version",
    ]
    write_csv(output_root / "manifest.csv", manifest_rows, fields)
    write_json(output_root / "video_reports.json", video_reports)
    summary = {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "source_video_count": len(sources),
        "clip_count": len(manifest_rows),
        "expected_clips": len(sources) * repetitions,
        "repetitions": repetitions,
        "ha_rotation": ha_rotation,
        "orientation_mode": "metadata" if use_metadata else "legacy",
        "dry_run": dry_run,
        "segmentation_version": SEGMENTATION_VERSION,
    }
    write_json(output_root / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--source-root", type=Path, help="Thư mục có các thư mục người quay")
    source_group.add_argument("--source-zip", type=Path, help="ZIP gồm 21 từ còn lại, không sửa ZIP gốc")
    parser.add_argument("--output-root", type=Path, help="ZIP mặc định dùng sales30_seated_remaining21")
    parser.add_argument("--limit", type=int, default=None, help="Chỉ xử lý N video đầu để kiểm tra")
    parser.add_argument("--person", action="append", choices=["HA", "Hoài Anh", "Nhi", "Như"], help="Chỉ xử lý người quay này; có thể lặp lại")
    parser.add_argument("--repetitions", type=int, default=EXPECTED_REPETITIONS)
    parser.add_argument("--ha-rotation", choices=["ccw", "cw"], default="ccw", help="Hoài Anh: ccw=90 độ ngược kim đồng hồ, cw=thuận")
    parser.add_argument("--orientation-mode", choices=["metadata", "legacy"], default=None, help="ZIP mặc định dùng metadata; source-root giữ cấu hình cũ")
    parser.add_argument("--audit-only", action="store_true", help="Chỉ giải nén/kiểm tra nhãn và báo cáo thiếu từ")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ tính timestamp, không encode clip")
    parser.add_argument("--force", action="store_true", help="Ghi đè clip đã tồn tại")
    args = parser.parse_args()
    if args.repetitions <= 0 or (args.limit is not None and args.limit <= 0):
        parser.error("--repetitions và --limit phải lớn hơn 0")
    if args.audit_only and (args.dry_run or args.limit):
        parser.error("--audit-only không dùng cùng --dry-run hoặc --limit")
    output_root = (args.output_root or (REMAINING_OUTPUT if args.source_zip else LEGACY_OUTPUT)).expanduser().absolute()
    try:
        reject_symlinks(output_root)
        output_root = output_root.resolve()
        run_root = output_root / "dry_run" if args.dry_run else output_root
        if args.source_zip:
            legacy = LEGACY_OUTPUT.resolve()
            if output_root == legacy or output_root.is_relative_to(legacy) or legacy.is_relative_to(output_root):
                raise ValueError("Không được xuất ZIP mới vào thư mục dữ liệu seated cũ")
        ensure_output_available(run_root, force=args.force)
        if args.source_zip:
            archive = args.source_zip.expanduser().resolve()
            # Cache is a sibling of the clip/report directory, so it cannot be overwritten by a run.
            source_root = extract_archive(archive, output_root.parent / f"{output_root.name}_sources")
        else:
            source_root = (args.source_root or Path("/Users/macbook/Downloads/video train")).expanduser().resolve()
        validate_roots(source_root, run_root)
        people = {normalized_person(Path(person) / "video.mp4") for person in args.person} if args.person else None
        sources = iter_sources(source_root, people)
        coverage = audit_sources(
            sources, expected_numbers=range(10, 31) if args.source_zip else range(1, 31),
            repetitions=args.repetitions, people=sorted(people) if people else ORIENTATION_FILTERS,
        )
        if args.source_zip:
            coverage["source_archive"] = str(archive)
            coverage["source_archive_sha256"] = sha256_file(archive)
        run_root.mkdir(parents=True, exist_ok=True)
        coverage_path = run_root / "coverage.json"
        if coverage_path.exists() and not args.force:
            existing = json.loads(coverage_path.read_text(encoding="utf-8"))
            if existing != coverage:
                raise FileExistsError("Coverage khác lần kiểm tra trước; dùng output-root mới hoặc --force")
        else:
            write_json(coverage_path, coverage)
        for missing in coverage["missing"]:
            print(f"Thiếu: {missing['person']} / {missing['number']} / {missing['label']}", flush=True)
        if args.audit_only:
            print(json.dumps(coverage, ensure_ascii=False, indent=2))
            return
        mode = args.orientation_mode or ("metadata" if args.source_zip else "legacy")
        summary = process(
            source_root, run_root, limit=args.limit, dry_run=args.dry_run, force=args.force,
            people=people, repetitions=args.repetitions, ha_rotation=args.ha_rotation,
            use_metadata=mode == "metadata",
        )
        if args.source_zip:
            summary["source_archive"] = str(archive)
            summary["source_archive_sha256"] = coverage["source_archive_sha256"]
            write_json(run_root / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False))
    except (ValueError, FileExistsError, zipfile.BadZipFile, OSError) as error:
        parser.exit(2, f"Lỗi: {error}\n")


if __name__ == "__main__":
    main()
