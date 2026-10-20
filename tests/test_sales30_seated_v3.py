from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from tmp import train_sales30_seated as trainer


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def manifests(tmp_path: Path) -> tuple[Path, Path, Path]:
    standing = write_csv(
        tmp_path / "standing.csv",
        [
            {"path": "train/Chao/a.mp4", "label_id": "0", "label": "Chào",
             "split": "train", "group_id": "unknown", "sha256": "1" * 64},
            {"path": "test/Chao/b.mp4", "label_id": "0", "label": "Chào",
             "split": "test", "group_id": "unknown", "sha256": "2" * 64},
        ],
    )
    old = write_csv(
        tmp_path / "old.csv",
        [{"person": "HA", "label": "Chào", "source_video": "HA/a.mov",
          "output_path": "clips/Chao/HA_rep01.mp4", "sha256": "3" * 64}],
    )
    new = write_csv(
        tmp_path / "new.csv",
        [
            {"person": "Nhi", "label": "Cần", "source_video": "Nhi/a.mov",
             "output_path": "clips/Can/Nhi_rep01.mp4", "sha256": "4" * 64},
            {"person": "Như", "label": "Cần", "source_video": "Nhu/a.mov",
             "output_path": "clips/Can/Nhu_rep01.mp4", "sha256": "5" * 64},
        ],
    )
    return standing, old, new


def test_v3_reads_both_seated_batches_without_changing_standing_splits(manifests):
    rows = trainer.build_combined_rows(
        *manifests[:2], ["Chào", "Cần"], additional_seated_manifest=manifests[2]
    )
    assert [row["split"] for row in rows] == ["train", "test", "train", "train", "validation"]
    assert rows[1]["path"] == "ml/data/raw/sales30/media/test/Chao/b.mp4"
    assert rows[2]["path"] == "ml/data/collected/sales30_seated/clips/Chao/HA_rep01.mp4"
    assert rows[3]["path"] == "ml/data/collected/sales30_seated_remaining21/clips/Can/Nhi_rep01.mp4"
    assert rows[4]["label_id"] == 1
    assert rows[4]["sha256"] == "5" * 64
    assert rows[0]["group_id"] != rows[1]["group_id"]


@pytest.mark.parametrize("column,value", [
    ("label", "Không có"), ("person", "người mới"),
    ("output_path", "../outside.mp4"), ("output_path", "/tmp/outside.mp4"),
    ("output_path", "clips\\outside.mp4"), ("sha256", "not-a-hash"),
])
def test_v3_rejects_bad_seated_rows(manifests, column, value):
    rows = list(csv.DictReader(manifests[2].open(encoding="utf-8")))
    rows[0][column] = value
    write_csv(manifests[2], rows)
    with pytest.raises(ValueError):
        trainer.build_combined_rows(
            *manifests[:2], ["Chào", "Cần"], additional_seated_manifest=manifests[2]
        )


def test_v3_rejects_duplicate_content_across_splits(manifests):
    rows = list(csv.DictReader(manifests[2].open(encoding="utf-8")))
    rows[1]["sha256"] = "1" * 64
    write_csv(manifests[2], rows)
    with pytest.raises(ValueError, match="(?i)hash|sha256|trùng"):
        trainer.build_combined_rows(
            *manifests[:2], ["Chào", "Cần"], additional_seated_manifest=manifests[2]
        )


def test_v3_rejects_duplicate_paths(manifests):
    rows = list(csv.DictReader(manifests[2].open(encoding="utf-8")))
    rows.append(dict(rows[0]))
    write_csv(manifests[2], rows)
    with pytest.raises(ValueError, match="(?i)path|trùng"):
        trainer.build_combined_rows(
            *manifests[:2], ["Chào", "Cần"], additional_seated_manifest=manifests[2]
        )


def test_v3_rejects_standing_label_id_mismatch(manifests):
    rows = list(csv.DictReader(manifests[0].open(encoding="utf-8")))
    rows[0]["label_id"] = "1"
    write_csv(manifests[0], rows)
    with pytest.raises(ValueError, match="label_id"):
        trainer.build_combined_rows(
            *manifests[:2], ["Chào", "Cần"], additional_seated_manifest=manifests[2]
        )


def test_v3_manifest_writes_are_idempotent_not_overwriting(tmp_path):
    path = tmp_path / "manifest.csv"
    trainer.write_immutable(path, b"original")
    trainer.write_immutable(path, b"original")
    with pytest.raises(FileExistsError):
        trainer.write_immutable(path, b"different")
    assert path.read_bytes() == b"original"


def test_v3_manifest_refuses_symlink_outputs(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        trainer.write_immutable(link / "manifest.csv", b"data")
    assert not (outside / "manifest.csv").exists()


def test_fresh_v3_run_does_not_reuse_existing_last_checkpoint(tmp_path):
    output = tmp_path / "run"
    output.mkdir()
    (output / "last.pt").write_bytes(b"old-run")
    with pytest.raises(FileExistsError, match="resume"):
        trainer.validate_v3_output(tmp_path, output, output, None)
    assert (output / "last.pt").read_bytes() == b"old-run"


def test_v3_output_cannot_overwrite_baseline_or_data(tmp_path):
    for relative in ("baseline/training", "ml/artifacts/sales30_seated_v2", "ml/data/collected"):
        output = tmp_path / relative
        with pytest.raises(ValueError):
            trainer.validate_v3_output(tmp_path, output, output, None)
        assert not output.exists()


def test_v3_resume_requires_current_dataset_and_manifest(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_bytes(b"new-data")
    baseline = tmp_path / "best.pt"
    baseline.write_bytes(b"v2-weights")
    payload = {
        "labels": ["Chào"], "dataset_version": "seated-v3",
        "combined_manifest_sha256": hashlib.sha256(b"new-data").hexdigest(),
        "fine_tuned_from_sha256": hashlib.sha256(b"v2-weights").hexdigest(),
        "config": {"training": {"epochs": 6, "learning_rate": 2e-5}},
    }
    trainer.validate_v3_resume(payload, ["Chào"], manifest, baseline, 6, 2e-5)
    for field, bad in (("dataset_version", "seated-v2"),
                       ("combined_manifest_sha256", "wrong"),
                       ("fine_tuned_from_sha256", "wrong"),
                       ("labels", ["Cần"])):
        with pytest.raises(ValueError):
            trainer.validate_v3_resume({**payload, field: bad}, ["Chào"], manifest, baseline, 6, 2e-5)


def test_v3_resume_rejects_changed_schedule(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_bytes(b"data")
    baseline = tmp_path / "best.pt"
    baseline.write_bytes(b"weights")
    payload = {"labels": ["Chào"], "dataset_version": "seated-v3",
               "combined_manifest_sha256": hashlib.sha256(b"data").hexdigest(),
               "fine_tuned_from_sha256": hashlib.sha256(b"weights").hexdigest(),
               "config": {"training": {"epochs": 6, "learning_rate": 2e-5}}}
    with pytest.raises(ValueError, match="(?i)epochs|learning_rate|schedule"):
        trainer.validate_v3_resume(payload, ["Chào"], manifest, baseline, 8, 2e-5)


def test_parser_accepts_explicit_v3_and_resume_path():
    args = trainer.build_parser().parse_args(["--dataset-version", "seated-v3", "--resume", "/run/last.pt"])
    assert args.dataset_version == "seated-v3"
    assert args.resume == Path("/run/last.pt")


@pytest.fixture
def full_dataset(tmp_path):
    labels = [f"word-{index:02d}" for index in range(1, 31)]
    label_path = tmp_path / "contracts/v1/sales30.labels.json"
    label_path.parent.mkdir(parents=True)
    label_path.write_text(json.dumps(labels), encoding="utf-8")
    standing = []
    for split, count in (("train", 1265), ("validation", 144), ("test", 351)):
        for index in range(count):
            label_id = index % 30
            relative = f"{split}/{labels[label_id]}/{index}.mp4"
            content = relative.encode("ascii")
            path = tmp_path / "ml/data/raw/sales30/media" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            standing.append({"path": relative, "label_id": str(label_id), "label": labels[label_id],
                             "split": split, "group_id": "unknown", "sha256": hashlib.sha256(content).hexdigest()})
    write_csv(tmp_path / "ml/data/raw/sales30/manifest.csv", standing)
    for batch, indices in (("sales30_seated", range(9)), ("sales30_seated_remaining21", range(9, 30))):
        seated = []
        for person in ("HA", "Nhi", "Như"):
            for index in indices:
                if person == "Nhi" and index in {26, 27}:
                    continue
                for repetition in range(1, 21):
                    relative = f"clips/{labels[index]}/{person}_{repetition}.mp4"
                    content = f"{batch}/{relative}".encode("utf-8")
                    path = tmp_path / "ml/data/collected" / batch / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                    seated.append({"person": person, "label": labels[index],
                                   "source_video": f"{person}/{labels[index]}.mov", "output_path": relative,
                                   "sha256": hashlib.sha256(content).hexdigest()})
        write_csv(tmp_path / "ml/data/collected" / batch / "manifest.csv", seated)
    old = tmp_path / "ml/data/combined/sales30_seated_v2/manifest.csv"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"untouched-v2-manifest")
    return tmp_path


def test_full_v3_preparation_reports_counts_and_preserves_old_manifest(full_dataset):
    manifest, labels, rows = trainer.prepare_manifest(full_dataset, "seated-v3")
    assert manifest == full_dataset / "ml/data/combined/sales30_seated_v3/manifest.csv"
    assert len(labels) == 30
    assert len(rows) == 3520
    assert dict(Counter(row["split"] for row in rows)) == {"train": 2425, "validation": 744, "test": 351}
    audit = json.loads((manifest.parent / "audit.json").read_text(encoding="utf-8"))
    assert audit["seated_people"] == {"HA": 600, "Nhi": 560, "Như": 600}
    assert audit["missing_seated_words"] == [
        {"person": "Nhi", "number": 27, "label": "word-27"},
        {"person": "Nhi", "number": 28, "label": "word-28"},
    ]
    assert (full_dataset / "ml/data/combined/sales30_seated_v2/manifest.csv").read_bytes() == b"untouched-v2-manifest"
    original = manifest.read_bytes()
    trainer.prepare_manifest(full_dataset, "seated-v3")
    assert manifest.read_bytes() == original


def test_full_preparation_rejects_media_hash_drift_before_writing_manifest(full_dataset):
    clip = full_dataset / "ml/data/raw/sales30/media/train/word-01/0.mp4"
    clip.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA256"):
        trainer.prepare_manifest(full_dataset, "seated-v3")
    assert not (full_dataset / "ml/data/combined/sales30_seated_v3/manifest.csv").exists()


def test_prepare_only_does_not_require_gpu_or_start_training(full_dataset, monkeypatch):
    def forbid_training(*args, **kwargs):
        raise AssertionError("prepare-only must not train")
    monkeypatch.setattr(trainer, "train", forbid_training)
    assert trainer.main(["--root", str(full_dataset), "--dataset-version", "seated-v3", "--prepare-only"]) == 0
    assert not (full_dataset / "runs").exists()


def test_resume_does_not_authorize_overwriting_unrelated_nonempty_output(tmp_path):
    source = tmp_path / "source-run"
    source.mkdir()
    resume = source / "last.pt"
    resume.write_bytes(b"checkpoint")
    unrelated = tmp_path / "unrelated-run"
    unrelated.mkdir()
    (unrelated / "best.pt").write_bytes(b"keep")
    with pytest.raises((FileExistsError, ValueError)):
        trainer.validate_v3_output(tmp_path, unrelated, unrelated, resume)
    assert (unrelated / "best.pt").read_bytes() == b"keep"


def test_resume_only_accepts_outputs_with_the_same_run_identity(tmp_path):
    source = tmp_path / "source-run"
    source.mkdir()
    identity = {"run_id": "approved-run", "dataset_version": "seated-v3"}
    (source / "run_identity.json").write_text(json.dumps(identity), encoding="utf-8")
    resume = source / "last.pt"
    resume.write_bytes(b"checkpoint")
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "run_identity.json").write_text(json.dumps(identity), encoding="utf-8")
    trainer.validate_v3_output(tmp_path, destination, source, resume)
    (destination / "run_identity.json").write_text(json.dumps({**identity, "run_id": "different-run"}), encoding="utf-8")
    with pytest.raises((FileExistsError, ValueError)):
        trainer.validate_v3_output(tmp_path, destination, source, resume)


@pytest.mark.parametrize("target", ["labels.json", "labels.json.tmp", "best.pt", "best.pt.tmp"])
def test_resume_rejects_child_symlinks_before_any_output_write(tmp_path, target):
    output = tmp_path / "run"
    output.mkdir()
    (output / "run_identity.json").write_text(
        json.dumps({"run_id": "approved-run", "dataset_version": "seated-v3"}), encoding="utf-8")
    resume = output / "last.pt"
    resume.write_bytes(b"checkpoint")
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    (output / target).symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        trainer.validate_v3_output(tmp_path, output, output, resume)
    assert outside.read_bytes() == b"keep"


def test_resume_pair_rejects_stale_best_checkpoint():
    last = {"run_id": "one-run", "epoch": 4, "best_validation_macro_f1": 0.8,
            "history": [{"epoch": 2, "validation": {"macro_f1": 0.7}},
                        {"epoch": 3, "validation": {"macro_f1": 0.8}},
                        {"epoch": 4, "validation": {"macro_f1": 0.75}}]}
    stale = {"run_id": "one-run", "epoch": 2, "best_validation_macro_f1": 0.7,
             "metrics": {"validation": {"macro_f1": 0.7}}}
    with pytest.raises(ValueError, match="best"):
        trainer.validate_v3_resume_pair(last, stale)
    current = {"run_id": "one-run", "epoch": 3, "best_validation_macro_f1": 0.8,
               "metrics": {"validation": {"macro_f1": 0.8}}}
    trainer.validate_v3_resume_pair(last, current)
    with pytest.raises(ValueError, match="run"):
        trainer.validate_v3_resume_pair(last, {**current, "run_id": "other-run"})


def test_resume_restores_validated_best_to_local_and_persistent_output(tmp_path):
    source = tmp_path / "saved-run/best.pt"
    source.parent.mkdir()
    source.write_bytes(b"validated-best")
    local = tmp_path / "local"
    persistent = tmp_path / "persistent"
    trainer.restore_resume_best(source, local, persistent)
    assert (local / "best.pt").read_bytes() == b"validated-best"
    assert (persistent / "best.pt").read_bytes() == b"validated-best"
    (local / "last.pt").write_bytes(b"later-epoch-without-improvement")
    trainer.sync_run(local, persistent, include_best=False)
    assert (persistent / "last.pt").read_bytes() == b"later-epoch-without-improvement"
    assert (persistent / "best.pt").read_bytes() == b"validated-best"


def test_resume_restores_stale_persistent_best_and_handles_same_output(tmp_path):
    local = tmp_path / "local"
    persistent = tmp_path / "persistent"
    local.mkdir()
    persistent.mkdir()
    source = local / "best.pt"
    source.write_bytes(b"current-best")
    (persistent / "best.pt").write_bytes(b"stale-best")
    trainer.restore_resume_best(source, local, persistent)
    assert source.read_bytes() == b"current-best"
    assert (persistent / "best.pt").read_bytes() == b"current-best"
    trainer.restore_resume_best(source, local, local)
    assert source.read_bytes() == b"current-best"
