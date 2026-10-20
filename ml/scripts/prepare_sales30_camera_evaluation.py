"""Prepare and fail-closed freeze a new-session Sales30 camera evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

from ml.scripts.audit_sales30_errors import SOURCE_MANIFESTS, inspect_video, write_json
from ml.scripts.evaluate_personal_runtime import file_hash
from ml.scripts.smoke_personal_runtime import IDLE_LABEL


NEGATIVE_ACTIONS = ["still", "hand_enter_exit", "adjust_hair_glasses", "touch_face", "turn_body",
                    "random_motion", "overlap_hands", "other_sign"]
CONDITIONS = [("standard", "normal"), ("near", "normal"), ("far", "normal"),
              ("standard", "side"), ("standard", "low")]


def build_plan(labels: list[str], repetitions: int = 5) -> list[dict]:
    if repetitions < 1 or len(labels) != len(set(labels)) or IDLE_LABEL not in labels:
        raise ValueError("Invalid labels or repetitions")
    plan = []
    for signer in ("A", "B"):
        for session in ("1", "2"):
            for label in labels:
                actions = NEGATIVE_ACTIONS if label == IDLE_LABEL else [""]
                for action in actions:
                    for repetition in range(1, repetitions + 1):
                        distance, lighting = CONDITIONS[(repetition - 1) % len(CONDITIONS)]
                        plan.append({"eval_slot_id": f"slot-{len(plan) + 1:04d}", "signer_slot": signer,
                                     "session_slot": session, "expected_label": label, "negative_action": action,
                                     "repetition": repetition, "distance": distance, "lighting": lighting})
    return plan


def validate_protocol(protocol: dict, labels: list[str]) -> None:
    expected = {"plan": build_plan(labels), "confidence_threshold": .7, "margin_threshold": .15,
                "frame_count": 16, "never_train": True, "selection_role": "new_session_evaluation_only"}
    if any(protocol.get(key) != value for key, value in expected.items()):
        raise ValueError("Evaluation protocol coverage or safety gates changed")


def audit_capture(plan: list[dict], records: list[dict], denylist: dict, *, captured_after: float) -> dict:
    planned = {row["eval_slot_id"]: row for row in plan}
    blockers, occupied, hashes, identities, sessions, owners = Counter(), set(), set(), {}, {}, {}
    sample_ids = set()
    slot_fields = ("expected_label", "negative_action", "distance", "lighting", "signer_slot", "session_slot")
    for record in records:
        slot_id = record.get("eval_slot_id")
        slot = planned.get(slot_id)
        if slot is None:
            blockers["unexpected_slot"] += 1
            continue
        if slot_id in occupied:
            blockers["duplicate_slot"] += 1
        occupied.add(slot_id)
        sample_id = record.get("sample_id")
        if not sample_id or sample_id in sample_ids:
            blockers["duplicate_sample_id"] += 1
        sample_ids.add(sample_id)
        if any((record.get(key) or "") != (slot.get(key) or "") for key in slot_fields):
            blockers["plan_mismatch"] += 1
        digest = record.get("video_sha256", "")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            blockers["invalid_hash"] += 1
        if digest in hashes:
            blockers["duplicate_hash"] += 1
        hashes.add(digest)
        if digest in denylist["hashes"]:
            blockers["hash_overlap"] += 1
        if record.get("source_sha256") in denylist.get("source_hashes", []):
            blockers["source_overlap"] += 1
        signer, session = record.get("signer_id"), record.get("session_id")
        if any(not value or str(value).lower() in {"unknown", "pending", "a", "b"} for value in (signer, session)):
            blockers["missing_identity"] += 1
        if session in denylist["sessions"]:
            blockers["session_overlap"] += 1
        signer_slot = slot["signer_slot"]
        session_slot = (signer_slot, slot["session_slot"])
        if signer_slot in identities and identities[signer_slot] != signer:
            blockers["signer_inconsistent"] += 1
        if signer in identities.values() and identities.get(signer_slot) != signer:
            blockers["signer_reused"] += 1
        identities[signer_slot] = signer
        if session_slot in sessions and sessions[session_slot] != session:
            blockers["session_inconsistent"] += 1
        if session in owners and owners[session] != session_slot:
            blockers["session_reused"] += 1
        owners[session], sessions[session_slot] = session_slot, session
        if (record.get("label_review") != "approved" or record.get("segmentation_review") != "approved"
                or not str(record.get("reviewed_by") or "").strip()):
            blockers["review_pending"] += 1
        if record.get("decode_ok") is not True:
            blockers["decode_failure"] += 1
        try:
            frame_count = int(record.get("frame_count", 0))
        except (TypeError, ValueError):
            frame_count = 0
        if frame_count < 16:
            blockers["insufficient_frames"] += 1
        if record.get("hand") not in {"right", "left"}:
            blockers["invalid_hand"] += 1
        try:
            captured_at = float(record["captured_at"])
            fresh = math.isfinite(captured_at) and captured_at > captured_after
        except (KeyError, ValueError, TypeError):
            fresh = False
        if not fresh:
            blockers["not_fresh"] += 1
    missing = len(set(planned) - occupied)
    if missing:
        blockers["missing_slots"] = missing
    ready = bool(plan) and not blockers
    unseen = (ready and denylist.get("signer_registry_complete") is True
              and not set(identities.values()) & set(denylist["signers"]))
    return {"ready_to_freeze": ready, "planned_slots": len(plan), "recorded_slots": len(occupied),
            "missing_slots": missing, "blocker_counts": dict(blockers), "unseen_signer_verified": unseen,
            "independence_scope": "unseen_signer" if unseen else "fresh_session_only",
            "limits": "Freshness and signer identities require operator attestation. Byte hashes cannot detect all re-encodings."}


def build_denylist(root: Path, manifest: Path) -> dict:
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    source_hashes = set()
    for source_manifest in SOURCE_MANIFESTS:
        with (root / source_manifest).open(encoding="utf-8-sig", newline="") as handle:
            source_hashes.update(row["source_sha256"] for row in csv.DictReader(handle))
    sessions = set()
    for path in (root / "ml/data/collected/sales30").rglob("*.json"):
        item = json.loads(path.read_text())
        if item.get("session_id"):
            sessions.add(item["session_id"])
    return {"hashes": sorted({row["sha256"] for row in rows}), "source_hashes": sorted(source_hashes),
            "sessions": sorted(sessions), "signers": sorted({row["person"] for row in rows if row["person"] != "unknown"}),
            "signer_registry_complete": all(row["person"] != "unknown" for row in rows),
            "excluded_roles": ["train", "validation", "test", "personal"],
            "manifest_sha256": file_hash(manifest)}


def load_records(raw: Path, annotations: Path) -> list[dict]:
    with annotations.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    records, paired = [], set()
    for row in rows:
        if not row.get("video"):
            continue
        video = (raw / row["video"]).resolve()
        if (not video.is_relative_to(raw.resolve()) or Path(row["video"]).is_absolute()
                or any(path.is_symlink() for path in (raw / row["video"], *(raw / row["video"]).parents))):
            raise ValueError("Unsafe evaluation video path")
        metadata_path = video.with_suffix(".json")
        item = json.loads(metadata_path.read_text())
        if item.get("video_file") != video.name or item.get("sample_id") != video.stem:
            raise ValueError("Unpaired capture metadata")
        stats = inspect_video(video)
        valid = (stats["decode_ok"] and stats["timestamps_monotonic"]
                 and (stats["width"], stats["height"]) == (224, 224)
                 and (stats["decoded_frames"], stats["width"], stats["height"]) == (
                     item["frame_count"], item["width"], item["height"]))
        record = {**row, **{key: item.get(key) for key in ("expected_label", "negative_action", "distance", "lighting",
                                                          "session_id", "captured_at", "hand", "sample_id")},
                  "video": str(video), "video_sha256": file_hash(video), "metadata_sha256": file_hash(metadata_path),
                  "decode_ok": bool(valid), "frame_count": stats.get("decoded_frames", 0)}
        records.append(record)
        paired.add(video)
    if set(path.resolve() for path in raw.rglob("*.mp4")) != paired:
        raise ValueError("Unannotated evaluation videos; do not silently ignore recordings")
    if set(path.resolve() for path in raw.rglob("*.json")) != {path.with_suffix(".json") for path in paired}:
        raise ValueError("Unpaired evaluation metadata; do not silently ignore recordings")
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "audit", "freeze"))
    parser.add_argument("--directory", type=Path, default=Path("ml/data/evaluation/sales30_coreml_camera_v1"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    artifact = root / "ml/artifacts/sales30_personal_v1"
    directory = args.directory
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        raise ValueError("Evaluation directory must not use symlinks")
    if args.mode == "prepare":
        if directory.exists():
            raise FileExistsError("Use a fresh evaluation directory")
        labels = json.loads((artifact / "labels.json").read_text())
        plan = build_plan(labels)
        directory.mkdir(parents=True)
        (directory / "raw").mkdir()
        protocol = {"schema_version": "1.0", "prepared_at_ms": int(time.time() * 1000),
                    "model_version": json.loads((artifact / "summary.json").read_text())["model_version"],
                    "model_sha256": file_hash(artifact / "best.pt"), "labels_sha256": file_hash(artifact / "labels.json"),
                    "confidence_threshold": .70, "margin_threshold": .15, "frame_count": 16,
                    "selection_role": "new_session_evaluation_only", "never_train": True,
                    "plan": plan, "denylist": build_denylist(root, artifact / "manifest.csv")}
        write_json(directory / "protocol.json", protocol)
        fields = [*plan[0], "video", "signer_id", "label_review", "segmentation_review", "reviewed_by", "notes"]
        with (directory / "annotations.csv").open("x", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(plan)
        write_json(directory / "readiness.json", audit_capture(plan, [], protocol["denylist"], captured_after=protocol["prepared_at_ms"]))
        print(json.dumps({"planned": len(plan), "ready": False, "directory": str(directory)}))
        return 0
    protocol = json.loads((directory / "protocol.json").read_text())
    validate_protocol(protocol, json.loads((artifact / "labels.json").read_text()))
    if (file_hash(artifact / "best.pt") != protocol["model_sha256"]
            or file_hash(artifact / "labels.json") != protocol["labels_sha256"]):
        raise ValueError("Model changed after evaluation preparation")
    records = load_records(directory / "raw", directory / "annotations.csv")
    # Re-read exclusions so later training/collection cannot evade the prepared denylist.
    denylist = build_denylist(root, artifact / "manifest.csv")
    for key in ("hashes", "sessions", "signers", "source_hashes"):
        denylist[key] = sorted(set(denylist[key]) | set(protocol["denylist"][key]))
    report = audit_capture(protocol["plan"], records, denylist, captured_after=protocol["prepared_at_ms"])
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    if args.mode == "freeze":
        if not report["ready_to_freeze"]:
            return 2
        write_json(directory / "frozen_manifest.json", {"protocol_sha256": file_hash(directory / "protocol.json"),
                   "annotations_sha256": file_hash(directory / "annotations.csv"), "protocol": protocol,
                   "readiness": report, "samples": records})
    return 0 if report["ready_to_freeze"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
