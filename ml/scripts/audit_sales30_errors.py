"""Read-only technical audit of recorded errors; semantic review stays pending."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import av
import numpy as np

from contracts.v1.sales_vocabulary import SALES_30_LABELS
from ml.scripts.evaluate_personal_runtime import file_hash


PRIORITY = ["Mua", "Muốn", "Sử dụng", "Rẻ", "Chào", "Thử", "Nồi cơm điện", "Điện thoại", "Gạo", "Cung cấp"]
SOURCE_MANIFESTS = [Path("ml/data/collected/sales30_seated/manifest.csv"),
                    Path("ml/data/collected/sales30_seated_remaining21/manifest.csv")]


def inspect_video(path: Path) -> dict:
    previous, motion, times = None, [], []
    try:
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            fps = float(stream.average_rate or 0)
            if fps <= 0:
                raise ValueError("Missing positive frame rate")
            width, height = stream.width, stream.height
            end = 0.
            for index, frame in enumerate(container.decode(video=0)):
                timestamp = float(frame.time) if frame.time is not None else index / fps
                times.append(timestamp)
                frame_duration = getattr(frame, "duration", None)
                duration = float(frame_duration * frame.time_base) if frame_duration and frame.time_base else 1 / fps
                end = max(end, timestamp + duration)
                image = frame.reformat(width=64, height=64, format="gray").to_ndarray().astype(np.float32)
                if previous is not None:
                    motion.append(float(np.abs(image - previous).mean()))
                previous = image
            if not times:
                raise ValueError("Empty video")
        return {"decode_ok": True, "decoded_frames": len(times), "width": width, "height": height,
                "fps": fps, "duration_seconds": end - times[0],
                "timestamps_monotonic": all(b > a for a, b in zip(times, times[1:])),
                "unique_uniform16_frames": len(set(np.linspace(0, len(times) - 1, 16).astype(int))),
                "center_square_retained_area": min(width, height) ** 2 / (width * height),
                "motion_mean": float(np.mean(motion)) if motion else 0.,
                "start_motion": float(np.mean(motion[:3])) if motion else 0.,
                "end_motion": float(np.mean(motion[-3:])) if motion else 0.}
    except (av.error.FFmpegError, OSError, ValueError, IndexError) as error:
        return {"decode_ok": False, "error": str(error)}


def interval_flags(row: dict) -> list[str]:
    try:
        start, end, duration = (float(row[key]) for key in ("start_time", "end_time", "duration"))
    except (KeyError, ValueError, TypeError):
        return ["invalid_interval"]
    if not all(math.isfinite(value) for value in (start, end, duration)) or start < 0 or end <= start:
        return ["invalid_interval"]
    return ["duration_mismatch"] if abs(end - start - duration) > .002 else []


def sequence_flags(rows: list[dict], expected: int = 20) -> list[str]:
    ordered = sorted(rows, key=lambda row: int(row["repetition"]))
    flags = []
    if [int(row["repetition"]) for row in ordered] != list(range(1, expected + 1)):
        flags.append("repetition_coverage")
    for previous, current in zip(ordered, ordered[1:]):
        gap = float(current["start_time"]) - float(previous["end_time"])
        if gap > .01:
            flags.append("boundary_gap")
        elif gap < -.01:
            flags.append("boundary_overlap")
    return sorted(set(flags))


def source_index(manifests: list[Path]) -> tuple[dict, dict]:
    index, groups = {}, defaultdict(list)
    for manifest in manifests:
        summary_path = manifest.parent / "summary.json"
        summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
        source_root = Path(summary["source_root"]) if "source_root" in summary else None
        with manifest.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                path = (manifest.parent / row["output_path"]).resolve()
                if not path.is_relative_to(manifest.parent.resolve()) or path in index:
                    raise ValueError("Duplicate or unsafe source manifest path")
                source = (source_root / row.get("source_video", "")).resolve() if source_root else None
                if source and not source.is_relative_to(source_root.resolve()):
                    raise ValueError("Unsafe original source path")
                entry = {**row, "source_path": str(source) if source else None,
                         "segmentation_manifest": str(manifest.resolve())}
                index[path] = entry
                groups[(str(manifest), row.get("source_video"))].append(entry)
    return index, groups


def missing_source_pairs(index: dict, labels: list[str], people: list[str]) -> list[dict]:
    present = {(row["person"], row["label"]) for row in index.values()}
    return [{"person": person, "label": label} for person in people for label in labels if (person, label) not in present]


def build_review_queue(samples: list[dict], manifests: list[Path], root: Path) -> list[dict]:
    index, _ = source_index(manifests)
    queue = []
    for sample in samples:
        reply = sample["reply"]
        if reply["status"] == "ok" and reply["label"] == sample["expected_label"]:
            continue
        if reply["status"] not in {"ok", "uncertain"}:
            raise ValueError("Invalid recorded prediction status")
        clip = (root / sample["path"]).resolve()
        if not clip.is_relative_to(root.resolve()):
            raise ValueError("Unsafe recorded sample path")
        trace = index.get(clip, {})
        if trace and (trace["label"] != sample["expected_label"] or trace["sha256"] != sample["sha256"]):
            raise ValueError("Source trace label or checksum disagrees with evaluation")
        priority = PRIORITY.index(sample["expected_label"]) if sample["expected_label"] in PRIORITY else len(PRIORITY)
        queue.append({"priority": priority + 1, "path": str(clip), "expected_label": sample["expected_label"],
                      "error_kind": "wrong_accept" if reply["status"] == "ok" else "uncertain",
                      "accepted_label": reply["label"], "raw_top1": sample["diagnostic"]["raw_top1"],
                      "confidence": sample["diagnostic"]["raw_confidence"], "sha256": sample["sha256"],
                      "clip_sha256_verified": clip.is_file() and file_hash(clip) == sample["sha256"],
                      "source_trace_available": bool(trace), **trace,
                      "semantic_status": "pending", "label_review": "", "segment_review": "",
                      "crop_review": "", "reviewer": "", "review_notes": ""})
    return sorted(queue, key=lambda row: (row["priority"], row["error_kind"] != "wrong_accept", row["path"]))


def write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=Path("docs/reports/2026-10-10-word-accuracy-coreml/predictions.jsonl"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    if args.output_dir.exists() or args.output_dir.resolve().is_relative_to((root / "ml/data").resolve()):
        parser.error("Use a fresh output directory outside source data")
    samples = [json.loads(line) for line in args.predictions.read_text().splitlines() if line.strip()]
    protected = [root / "ml/artifacts/sales30_personal_v1/best.pt",
                 root / "ml/artifacts/sales30_seated_v3/training/best.pt",
                 root / "ml/artifacts/sales30_personal_v1/labels.json", args.predictions, *SOURCE_MANIFESTS]
    before = {str(path): file_hash(path) for path in protected}
    queue = build_review_queue(samples, SOURCE_MANIFESTS, root)
    index, groups = source_index(SOURCE_MANIFESTS)
    source_reports = []
    for (_, source_name), rows in groups.items():
        path = Path(rows[0]["source_path"])
        flags = sequence_flags(rows)
        flags += [flag for row in rows for flag in interval_flags(row)]
        exists = path.is_file()
        verified = exists and file_hash(path) == rows[0]["source_sha256"]
        if not verified:
            flags.append("source_missing" if not exists else "source_checksum_mismatch")
        hashes_ok = all(path.is_file() and file_hash(path) == row["sha256"]
                        for row in rows for path in [Path(row["segmentation_manifest"]).parent / row["output_path"]])
        if not hashes_ok:
            flags.append("clip_checksum_mismatch")
        source_reports.append({"source_video": source_name, "source_path": str(path), "label": rows[0]["label"],
                               "person": rows[0]["person"], "clips": len(rows), "flags": sorted(set(flags)),
                               "source_sha256_verified": verified, "all_clip_hashes_verified": hashes_ok})
    for number, row in enumerate(queue, 1):
        row["video_audit"] = inspect_video(Path(row["path"]))
        if number % 25 == 0:
            print(json.dumps({"decoded_errors": number, "total": len(queue)}), flush=True)
    unchanged = all(file_hash(Path(path)) == digest for path, digest in before.items())
    if not unchanged:
        raise RuntimeError("Protected inputs changed during audit")
    args.output_dir.mkdir(parents=True)
    report = {"queue_size": len(queue), "seated_manifest_clips": len(index), "source_videos": len(groups),
              "missing_source_pairs": missing_source_pairs(index, list(SALES_30_LABELS), ["HA", "Nhi", "Như"]),
              "duplicate_clip_hashes": {digest: count for digest, count in Counter(row["sha256"] for row in index.values()).items() if count > 1},
              "source_flags": dict(Counter(flag for row in source_reports for flag in row["flags"])),
              "trace_available": sum(row["source_trace_available"] for row in queue),
              "clip_hash_failures": sum(not row["clip_sha256_verified"] for row in queue),
              "decode_failures": sum(not row["video_audit"]["decode_ok"] for row in queue),
              "semantic_reviews_completed": 0, "protected_inputs_unchanged": unchanged,
              "protected_sha256": before, "sources": source_reports, "queue": queue,
              "limits": "Motion and geometric crop ratios do not prove incomplete gestures, missing hands or bad labels."}
    write_json(args.output_dir / "audit.json", report)
    fields = [key for key in queue[0] if key != "video_audit"]
    with (args.output_dir / "review_queue.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(queue)
    print(json.dumps({key: report[key] for key in ("queue_size", "trace_available", "decode_failures", "source_flags")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
