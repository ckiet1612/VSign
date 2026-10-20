from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import torch

from ml import personal_finetune as personal


def test_expansion_preserves_existing_classifier_rows() -> None:
    old = torch.nn.Linear(4, 30)
    expanded = personal.expand_head(old)
    assert expanded.out_features == 31
    assert torch.equal(expanded.weight[:30], old.weight)
    assert torch.equal(expanded.bias[:30], old.bias)
    assert torch.equal(expanded.weight[30], torch.zeros(4))
    assert expanded.bias[30] < old.bias.min()


def fixture_rows(tmp_path: Path, *, duplicate: bool = False):
    labels = [f"word-{index}" for index in range(30)]
    fields = ["path", "label_id", "label", "split", "source", "person", "group_id", "sha256"]
    rows = []
    for index, split in enumerate(["train", "validation", "test"]):
        path = tmp_path / f"{split}.mp4"
        path.write_bytes(split.encode())
        rows.append(dict(zip(fields, [path.name, "0", labels[0], split, "standing", "unknown", f"old:{split}", hashlib.sha256(path.read_bytes()).hexdigest()])))
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    batch = tmp_path / "batch"
    batch.mkdir()
    for index, label in enumerate([labels[0], personal.IDLE_LABEL]):
        video = batch / f"sample-{index}.mp4"
        video.write_bytes(b"test" if duplicate else f"personal-{index}".encode())
        video.with_suffix(".json").write_text(json.dumps({
            "sample_id": video.stem, "video_file": video.name,
            "expected_label": label, "session_id": "same-session", "hand": "right",
            "frame_count": 29, "width": 224, "height": 224, "duration_ms": 2100,
            "captured_at": index, "distance": "standard", "lighting": "normal",
            "negative_action": "still" if label == personal.IDLE_LABEL else None,
        }))
    return labels, manifest, batch, rows


def test_personal_samples_are_train_only_without_modifying_old_splits(tmp_path: Path) -> None:
    labels, manifest, batch, old = fixture_rows(tmp_path)
    rows, audit = personal.prepare_rows(tmp_path, manifest, batch, labels)
    assert rows[:3] == old
    assert {row["split"] for row in rows[3:]} == {"train"}
    assert {row["group_id"] for row in rows[3:]} == {"personal:same-session"}
    assert rows[-1]["label_id"] == 30
    assert audit["independent_negative_evaluation"] is False
    assert audit["personal_sessions"] == {"same-session": 2}


def test_rejects_duplicate_between_personal_train_and_old_test(tmp_path: Path) -> None:
    labels, manifest, batch, _ = fixture_rows(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="SHA256.*split"):
        personal.prepare_rows(tmp_path, manifest, batch, labels)


def test_rejects_unknown_label(tmp_path: Path) -> None:
    labels, manifest, batch, _ = fixture_rows(tmp_path)
    path = batch / "sample-0.json"
    data = json.loads(path.read_text())
    data["expected_label"] = "unknown"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="label"):
        personal.prepare_rows(tmp_path, manifest, batch, labels)


def test_features_report_negative_false_accepts_without_treating_idle_as_a_word() -> None:
    head = torch.nn.Linear(2, 3)
    with torch.no_grad():
        head.weight.copy_(torch.tensor([[4., 0.], [0., 4.], [-4., -4.]]))
        head.bias.zero_()
    features = torch.tensor([[1., 0.], [0., 1.], [-1., -1.]])
    result = personal.evaluate_features(head, features, torch.tensor([0, 1, 2]), ["a", "b", personal.IDLE_LABEL])
    assert result["accuracy"] == 1.0
    assert result["negative_false_accept_rate"] == 0.0
    assert result["negative_samples"] == 1


def test_gate_rejects_old_vocabulary_regression() -> None:
    baseline = {"accuracy": .9, "macro_f1": .8, "positive_correct_accept_rate": .85}
    assert personal.regression_gate(baseline, {"accuracy": .89, "macro_f1": .79, "positive_correct_accept_rate": .84})
    assert not personal.regression_gate(baseline, {"accuracy": .87, "macro_f1": .79, "positive_correct_accept_rate": .84})


def test_cache_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    cache = tmp_path / "cache.pt"
    torch.save({"identity": {"baseline": "old"}}, cache)
    with pytest.raises(ValueError, match="identity"):
        personal.load_feature_cache(cache, {"baseline": "new"}, 2, 4)


def test_output_cannot_overwrite_baseline_or_source_data(tmp_path: Path) -> None:
    baseline = tmp_path / "ml/artifacts/v3/best.pt"
    batch = tmp_path / "ml/data/batch"
    for output in [baseline.parent, batch, batch / "new", tmp_path]:
        with pytest.raises(ValueError, match="Output"):
            personal.validate_output(output, baseline, batch)


def test_launcher_rejects_an_altered_label_order(tmp_path: Path) -> None:
    labels = json.loads(Path("contracts/v1/sales30.labels.json").read_text())
    labels[0], labels[1] = labels[1], labels[0]
    (tmp_path / "best.pt").write_bytes(b"not-a-model")
    (tmp_path / "labels.json").write_text(json.dumps(labels + [personal.IDLE_LABEL]))
    (tmp_path / "summary.json").write_text(json.dumps({
        "deployment_gate_passed": True, "best_sha256": personal.sha256_file(tmp_path / "best.pt"),
        "model_version": "test",
    }))
    import os
    result = subprocess.run(
        ["bash", "scripts/run_personal_local.sh"],
        env={**os.environ, "PERSONAL_MODEL_DIR": str(tmp_path)},
        text=True, capture_output=True, timeout=20,
    )
    assert result.returncode != 0
    assert "Label map" in result.stderr


def test_real_head_training_learns_idle_and_keeps_old_validation(tmp_path: Path) -> None:
    from ml.scripts.finetune_sales30_personal import train_head

    torch.set_num_threads(2)
    torch.manual_seed(9)
    labels = [f"word-{index}" for index in range(30)] + [personal.IDLE_LABEL]
    head = torch.nn.Linear(31, 30)
    with torch.no_grad():
        head.weight.zero_()
        head.weight[:, :30].copy_(torch.eye(30) * 14)
        head.bias.zero_()
    features, rows = [], []
    for split in ["train", "validation", "test"]:
        for index in range(30):
            features.append(torch.eye(31)[index])
            rows.append({"label_id": index, "source": "standing", "split": split})
    for index in [0, 30]:
        features.append(torch.eye(31)[index])
        rows.append({"label_id": index, "source": "personal", "split": "train"})
    trained, epoch, _, comparison = train_head(
        torch.stack(features), rows, head, labels, 50, .2, tmp_path,
    )
    assert epoch >= 1
    assert not torch.equal(trained.weight[:30], head.weight)
    assert comparison["deployment_gate_passed"]
    assert comparison["personal_training_only"]["candidate"]["negative_recognition_rate"] == 1.


@pytest.mark.parametrize("container_format", ["mp4", "mpegts"])
def test_selective_decode_matches_original_tensor_exactly(tmp_path: Path, container_format: str) -> None:
    import av
    import numpy as np
    from ml.visignlanguage import decode_video, frames_to_tensor

    video = tmp_path / f"sample.{container_format}"
    with av.open(str(video), mode="w", format=container_format) as container:
        stream = container.add_stream("libx264", rate=12)
        stream.width = stream.height = 32
        stream.pix_fmt = "yuv420p"
        for index in range(25):
            pixels = np.full((32, 32, 3), index * 9, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    original = frames_to_tensor(decode_video(video), frame_count=16, height=224, width=224, training=False)
    frames = personal.decode_uniform_frames(video)
    assert len(frames) == 16
    selective = frames_to_tensor(frames, frame_count=16, height=224, width=224, training=False)
    assert torch.equal(selective, original)


def baseline_manifest_fixture(tmp_path: Path):
    manifest = tmp_path / "accepted.csv"
    rows = []
    for source, split, count in [("standing", "train", 1265), ("standing", "validation", 144),
                                 ("standing", "test", 351), ("seated", "train", 1160),
                                 ("seated", "validation", 600)]:
        for index in range(count):
            group = f"{source}:{split}:{index}"
            rows.append({"path": f"{group}.mp4", "label_id": 0, "label": "word-0", "split": split,
                         "source": source, "person": "unknown", "group_id": group, "sha256": "f" * 64})
    with manifest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=personal.MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    checkpoint = {"dataset_version": "seated-v3", "combined_manifest_sha256": personal.sha256_file(manifest)}
    return manifest, rows, checkpoint


def test_baseline_split_reassignment_cannot_create_a_new_accepted_identity(tmp_path: Path) -> None:
    manifest, rows, checkpoint = baseline_manifest_fixture(tmp_path)
    personal.verify_baseline_manifest(manifest, checkpoint)
    train = next(row for row in rows if row["split"] == "train")
    test = next(row for row in rows if row["split"] == "test")
    train["split"], test["split"] = test["split"], train["split"]
    with manifest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=personal.MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="baseline.*manifest"):
        personal.verify_baseline_manifest(manifest, checkpoint)


def test_baseline_manifest_must_also_match_approved_counts(tmp_path: Path) -> None:
    manifest, rows, checkpoint = baseline_manifest_fixture(tmp_path)
    rows.pop()
    with manifest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=personal.MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    checkpoint["combined_manifest_sha256"] = personal.sha256_file(manifest)
    with pytest.raises(ValueError, match="counts"):
        personal.verify_baseline_manifest(manifest, checkpoint)


@pytest.mark.parametrize("corruption", ["finite_feature", "false_completion"])
def test_cache_integrity_rejects_finite_corruption(tmp_path: Path, corruption: str) -> None:
    path = tmp_path / "features.pt"
    identity = {"baseline": "accepted"}
    cache = personal.load_feature_cache(path, identity, 2, 4)
    cache["features"][0] = torch.arange(4)
    cache["completed"][0] = True
    personal.save_cache(path, cache)
    saved = torch.load(path, weights_only=True)
    if corruption == "finite_feature":
        saved["features"][0, 0] += 1
    else:
        saved["completed"][1] = True
    torch.save(saved, path)
    with pytest.raises(ValueError, match="integrity"):
        personal.load_feature_cache(path, identity, 2, 4)


@pytest.mark.parametrize("threshold_overrides", [{}, {"CONFIDENCE_THRESHOLD": "0.30", "MARGIN_THRESHOLD": "0.01"}])
def test_launcher_exports_the_same_absolute_model_path_it_verifies(tmp_path: Path, threshold_overrides) -> None:
    import os

    project = tmp_path / "project"
    caller = tmp_path / "caller"
    model = caller / "models"
    for directory in [project / "scripts", project / ".venv/bin", project / "contracts/v1", model]:
        directory.mkdir(parents=True)
    labels_content = Path("contracts/v1/sales30.labels.json").read_text()
    (project / "contracts/v1/sales30.labels.json").write_text(labels_content)
    script = project / "scripts/run_personal_local.sh"
    script.write_text(Path("scripts/run_personal_local.sh").read_text())
    (project / ".venv/bin/python").symlink_to(Path(sys.executable).resolve())
    uvicorn = project / ".venv/bin/uvicorn"
    uvicorn.write_text('#!/bin/sh\nprintf "%s\\n" "$PYTORCH_MODEL_PATH" "$LABEL_MAP_PATH" "$MODEL_VERSION" "$CONFIDENCE_THRESHOLD" "$MARGIN_THRESHOLD"\n')
    uvicorn.chmod(0o755)
    (model / "best.pt").write_bytes(b"verified-model")
    (model / "labels.json").write_text(json.dumps(json.loads(labels_content) + [personal.IDLE_LABEL]))
    (model / "summary.json").write_text(json.dumps({"deployment_gate_passed": True,
        "best_sha256": personal.sha256_file(model / "best.pt"), "model_version": "verified-version"}))
    result = subprocess.run(["bash", str(script)], cwd=caller,
        env={**os.environ, "PERSONAL_MODEL_DIR": "models", **threshold_overrides}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(model / "best.pt"), str(model / "labels.json"), "verified-version", "0.70", "0.15"]


def test_gate_rejects_lost_runtime_acceptance_even_when_argmax_is_unchanged() -> None:
    baseline_head = torch.nn.Linear(1, 2)
    candidate_head = torch.nn.Linear(1, 3)
    with torch.no_grad():
        baseline_head.weight.zero_()
        candidate_head.weight.zero_()
        baseline_head.bias.copy_(torch.tensor([.9, .1]).log())
        candidate_head.bias.copy_(torch.tensor([.55, .05, .4]).log())
    features, targets = torch.zeros(1, 1), torch.tensor([0])
    baseline = personal.evaluate_features(baseline_head, features, targets, ["a", "b"])
    candidate = personal.evaluate_features(candidate_head, features, targets, ["a", "b", personal.IDLE_LABEL], positive_class_count=2)
    assert baseline["accuracy"] == candidate["accuracy"] == 1.
    assert baseline["macro_f1"] == candidate["macro_f1"]
    assert baseline["positive_correct_accept_rate"] == 1.
    assert candidate["positive_correct_accept_rate"] == 0.
    assert not personal.regression_gate(baseline, candidate)


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_gate_fails_closed_on_missing_or_nonfinite_acceptance(value) -> None:
    baseline = {"accuracy": .9, "macro_f1": .8, "positive_correct_accept_rate": .85}
    assert not personal.regression_gate(baseline, {**baseline, "positive_correct_accept_rate": value})
