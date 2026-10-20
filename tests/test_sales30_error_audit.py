from __future__ import annotations

import csv
import hashlib
import importlib

import av
import numpy as np
import pytest


def tool():
    return importlib.import_module("ml.scripts.audit_sales30_errors")


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_video(path, count=20, width=64, height=48):
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        for index in range(count):
            frame = av.VideoFrame.from_ndarray(np.full((height, width, 3), index * 4, np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_decode_audit_measures_actual_frames_and_geometry(tmp_path):
    video = tmp_path / "clip.mp4"
    make_video(video)
    stats = tool().inspect_video(video)
    assert stats["decoded_frames"] == 20
    assert stats["width"] == 64 and stats["height"] == 48
    assert stats["duration_seconds"] == pytest.approx(2.0, abs=.02)
    assert stats["unique_uniform16_frames"] == 16
    assert stats["center_square_retained_area"] == .75


def test_corrupt_video_is_a_technical_failure_not_a_semantic_diagnosis(tmp_path):
    video = tmp_path / "bad.mp4"
    video.write_bytes(b"not a video")
    stats = tool().inspect_video(video)
    assert stats["decode_ok"] is False
    assert stats["error"]
    assert "wrong_label" not in stats


@pytest.mark.parametrize("change,wanted", [
    ({"start_time": "-1"}, "invalid_interval"),
    ({"end_time": "1"}, "invalid_interval"),
    ({"duration": "9"}, "duration_mismatch"),
    ({"start_time": "nan"}, "invalid_interval"),
])
def test_boundary_audit_reports_invalid_intervals(change, wanted):
    row = {"start_time": "1", "end_time": "3", "duration": "2", "repetition": "1"}
    assert wanted in tool().interval_flags({**row, **change})


def test_source_sequence_detects_gap_overlap_and_missing_repetition():
    rows = [{"repetition": "1", "start_time": "0", "end_time": "2", "duration": "2"},
            {"repetition": "3", "start_time": "2.2", "end_time": "4", "duration": "1.8"},
            {"repetition": "4", "start_time": "3.9", "end_time": "6", "duration": "2.1"}]
    assert set(tool().sequence_flags(rows, expected=4)) == {"repetition_coverage", "boundary_gap", "boundary_overlap"}


def test_error_queue_keeps_uncertain_distinct_and_never_confirms_semantics(tmp_path):
    base = tmp_path / "seated"
    base.mkdir()
    clip = base / "clip.mp4"
    make_video(clip)
    digest = hashlib.sha256(clip.read_bytes()).hexdigest()
    source_row = {"output_path": "clip.mp4", "label": "Mua", "person": "Như", "sha256": digest,
                  "source_video": "Nhu/mua.mov", "source_sha256": "a" * 64,
                  "start_time": "1", "end_time": "3", "duration": "2", "repetition": "1"}
    write_csv(base / "manifest.csv", [source_row])
    sample = {"path": "seated/clip.mp4", "sha256": digest, "expected_label": "Mua", "source": "seated",
              "reply": {"status": "uncertain", "label": None},
              "diagnostic": {"raw_top1": "Gạo", "raw_confidence": .6}}
    queue = tool().build_review_queue([sample], [base / "manifest.csv"], tmp_path)
    assert len(queue) == 1
    assert queue[0]["error_kind"] == "uncertain"
    assert queue[0]["accepted_label"] is None
    assert queue[0]["raw_top1"] == "Gạo"
    assert queue[0]["start_time"] == "1"
    assert queue[0]["semantic_status"] == "pending"
    assert queue[0]["clip_sha256_verified"] is True


def test_trace_refuses_mismatched_labels_instead_of_inventing_root_cause(tmp_path):
    write_csv(tmp_path / "manifest.csv", [{"output_path": "clip.mp4", "label": "Mua", "sha256": "a" * 64}])
    sample = {"path": "clip.mp4", "sha256": "a" * 64, "expected_label": "Rẻ",
              "reply": {"status": "ok", "label": "Có"}, "diagnostic": {"raw_top1": "Có", "raw_confidence": .9}}
    with pytest.raises(ValueError, match="label"):
        tool().build_review_queue([sample], [tmp_path / "manifest.csv"], tmp_path)


def test_frontend_probe_selects_errors_not_training_or_correct_clips():
    from ml.scripts import probe_sales30_frontend

    rows = [{"path": "correct.mp4", "source": "seated", "expected_label": "Mua",
             "reply": {"status": "ok", "label": "Mua"}, "diagnostic": {"raw_confidence": .99}},
            {"path": "error.mp4", "source": "seated", "expected_label": "Mua",
             "reply": {"status": "ok", "label": "Gạo"}, "diagnostic": {"raw_confidence": .9}},
            {"path": "uncertain.mp4", "source": "seated", "expected_label": "Mua",
             "reply": {"status": "uncertain", "label": None}, "diagnostic": {"raw_confidence": .5}}]
    selected = probe_sales30_frontend.select_probe(rows, ["Mua"])
    assert [row["path"] for row in selected] == ["error.mp4"]


def test_frontend_probe_refuses_to_fill_a_missing_error_with_a_correct_sample():
    from ml.scripts import probe_sales30_frontend

    rows = [{"path": "correct.mp4", "source": "seated", "expected_label": "Mua",
             "reply": {"status": "ok", "label": "Mua"}, "diagnostic": {"raw_confidence": .99}}]
    with pytest.raises(ValueError, match="Missing"):
        probe_sales30_frontend.select_probe(rows, ["Mua"])


def test_signer_word_coverage_does_not_treat_repetitions_as_new_people():
    index = {"a": {"person": "HA", "label": "Mua"}, "b": {"person": "HA", "label": "Mua"},
             "c": {"person": "Như", "label": "Mua"}}
    missing = tool().missing_source_pairs(index, ["Mua", "Rẻ"], ["HA", "Như"])
    assert missing == [{"person": "HA", "label": "Rẻ"}, {"person": "Như", "label": "Rẻ"}]
