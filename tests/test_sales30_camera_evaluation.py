from __future__ import annotations

import importlib
import json

import pytest

from tests.test_sales30_error_audit import make_video, write_csv


def tool():
    return importlib.import_module("ml.scripts.prepare_sales30_camera_evaluation")


LABELS = ["Mua", "Rẻ", "Không ký hiệu"]


def plan_and_records():
    plan = tool().build_plan(LABELS, repetitions=1)
    records = []
    for index, slot in enumerate(plan):
        records.append({**slot, "sample_id": f"clip-{index}", "signer_id": f"person-{slot['signer_slot']}",
                        "session_id": f"new-{slot['signer_slot']}-{slot['session_slot']}",
                        "video_sha256": f"{index + 1:064x}", "hand": "right", "decode_ok": True,
                        "frame_count": 20, "label_review": "approved", "segmentation_review": "approved",
                        "reviewed_by": "vsl-reviewer", "captured_at": 2000})
    deny = {"hashes": [], "sessions": ["old-session"], "signers": ["old-signer"],
            "signer_registry_complete": False}
    return plan, records, deny


def test_plan_covers_every_word_multiple_sessions_and_all_negative_actions():
    plan = tool().build_plan(LABELS, repetitions=5)
    positives = [row for row in plan if row["expected_label"] != "Không ký hiệu"]
    negatives = [row for row in plan if row["expected_label"] == "Không ký hiệu"]
    assert len(positives) == 40
    assert len(negatives) == 160
    assert {row["negative_action"] for row in negatives} == {
        "still", "hand_enter_exit", "adjust_hair_glasses", "touch_face", "turn_body",
        "random_motion", "overlap_hands", "other_sign"}
    assert len({row["eval_slot_id"] for row in plan}) == 200


def test_empty_capture_is_explicitly_blocked_not_a_successful_freeze():
    plan, _, deny = plan_and_records()
    report = tool().audit_capture(plan, [], deny, captured_after=1000)
    assert report["ready_to_freeze"] is False
    assert report["missing_slots"] == len(plan)


def test_new_session_gate_does_not_claim_unknown_training_signers_are_unseen():
    plan, records, deny = plan_and_records()
    report = tool().audit_capture(plan, records, deny, captured_after=1000)
    assert report["ready_to_freeze"] is True
    assert report["unseen_signer_verified"] is False
    assert report["independence_scope"] == "fresh_session_only"


@pytest.mark.parametrize("change,wanted", [
    ({"session_id": "old-session"}, "session_overlap"),
    ({"video_sha256": "f" * 64}, "hash_overlap"),
    ({"expected_label": "Rẻ"}, "plan_mismatch"),
    ({"label_review": "pending"}, "review_pending"),
    ({"segmentation_review": "pending"}, "review_pending"),
    ({"reviewed_by": ""}, "review_pending"),
    ({"decode_ok": False}, "decode_failure"),
    ({"frame_count": 5}, "insufficient_frames"),
    ({"captured_at": 999}, "not_fresh"),
    ({"captured_at": float("nan")}, "not_fresh"),
    ({"signer_id": "unknown"}, "missing_identity"),
])
def test_bad_capture_blocks_freeze(change, wanted):
    plan, records, deny = plan_and_records()
    deny["hashes"] = ["f" * 64]
    records[0].update(change)
    report = tool().audit_capture(plan, records, deny, captured_after=1000)
    assert report["ready_to_freeze"] is False
    assert wanted in report["blocker_counts"]


def test_duplicate_capture_cannot_fill_another_slot():
    plan, records, deny = plan_and_records()
    records[1]["video_sha256"] = records[0]["video_sha256"]
    report = tool().audit_capture(plan, records, deny, captured_after=1000)
    assert report["ready_to_freeze"] is False
    assert report["blocker_counts"]["duplicate_hash"] == 1


def test_same_session_for_two_days_is_not_two_independent_sessions():
    plan, records, deny = plan_and_records()
    for record in records:
        record["session_id"] = f"same-{record['signer_slot']}"
    report = tool().audit_capture(plan, records, deny, captured_after=1000)
    assert report["ready_to_freeze"] is False
    assert "session_reused" in report["blocker_counts"]


def test_same_person_cannot_count_as_two_signers():
    plan, records, deny = plan_and_records()
    for record in records:
        record["signer_id"] = "same-person"
    report = tool().audit_capture(plan, records, deny, captured_after=1000)
    assert report["ready_to_freeze"] is False
    assert "signer_reused" in report["blocker_counts"]


def test_source_recording_overlap_blocks_reencoded_training_clip():
    plan, records, deny = plan_and_records()
    deny["source_hashes"] = ["e" * 64]
    records[0]["source_sha256"] = "e" * 64
    report = tool().audit_capture(plan, records, deny, captured_after=1000)
    assert report["ready_to_freeze"] is False
    assert "source_overlap" in report["blocker_counts"]


def test_orphan_metadata_is_not_silently_ignored_in_independent_set(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "orphan.json").write_text("{}")
    write_csv(tmp_path / "annotations.csv", [{"eval_slot_id": "slot-0001", "video": ""}])
    with pytest.raises(ValueError, match="Unannotated|Unpaired"):
        tool().load_records(raw, tmp_path / "annotations.csv")


def test_decode_geometry_cannot_be_forged_by_matching_metadata(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    video = raw / "small.mp4"
    make_video(video)
    item = {"video_file": "small.mp4", "sample_id": "small", "frame_count": 20, "width": 64, "height": 48}
    video.with_suffix(".json").write_text(json.dumps(item))
    write_csv(tmp_path / "annotations.csv", [{"eval_slot_id": "slot-0001", "video": "small.mp4"}])
    records = tool().load_records(raw, tmp_path / "annotations.csv")
    assert records[0]["decode_ok"] is False


def test_valid_actual_capture_is_decoded_and_hashed_without_mutating_source(tmp_path):
    import hashlib

    raw = tmp_path / "raw"
    raw.mkdir()
    video = raw / "valid.mp4"
    make_video(video, width=224, height=224)
    before = video.read_bytes()
    item = {"video_file": "valid.mp4", "sample_id": "valid", "frame_count": 20, "width": 224, "height": 224,
            "expected_label": "Mua", "hand": "right", "captured_at": 2000, "session_id": "new-session"}
    video.with_suffix(".json").write_text(json.dumps(item))
    write_csv(tmp_path / "annotations.csv", [{"eval_slot_id": "slot-0001", "video": "valid.mp4"}])
    records = tool().load_records(raw, tmp_path / "annotations.csv")
    assert records[0]["decode_ok"] is True
    assert records[0]["frame_count"] == 20
    assert records[0]["video_sha256"] == hashlib.sha256(before).hexdigest()
    assert video.read_bytes() == before


def test_slot_ids_and_samples_must_not_be_duplicated():
    plan, records, deny = plan_and_records()
    records[1]["sample_id"] = records[0]["sample_id"]
    report = tool().audit_capture(plan, records, deny, captured_after=1000)
    assert report["ready_to_freeze"] is False
    assert "duplicate_sample_id" in report["blocker_counts"]


def test_invalid_frame_count_blocks_audit_instead_of_crashing():
    plan, records, deny = plan_and_records()
    records[0]["frame_count"] = None
    report = tool().audit_capture(plan, records, deny, captured_after=1000)
    assert report["ready_to_freeze"] is False
    assert "insufficient_frames" in report["blocker_counts"]


@pytest.mark.parametrize("change", [{"plan": []}, {"confidence_threshold": .5}, {"never_train": False}])
def test_protocol_cannot_lower_coverage_or_safety_gates_after_preparation(change):
    protocol = {"plan": tool().build_plan(LABELS), "confidence_threshold": .7, "margin_threshold": .15,
                "frame_count": 16, "never_train": True, "selection_role": "new_session_evaluation_only"}
    with pytest.raises(ValueError, match="protocol"):
        tool().validate_protocol({**protocol, **change}, LABELS)
