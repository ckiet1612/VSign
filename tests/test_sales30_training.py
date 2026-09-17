from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ml.sales30_data import (
    MANIFEST_FIELDS,
    SALES30_DATASET_REF,
    SALES30_LICENSE,
    SALES30_VERSION,
)
from ml.scripts.train_visignlanguage import (
    build_checkpoint_metadata,
    build_data_provenance,
    resolve_device,
    validate_training_data_bundle,
    validate_training_config,
)
from ml.visignlanguage import load_labels, load_yaml


CONFIG_PATH = Path("ml/configs/sales30_mvitv2_s.yaml")
LABELS_PATH = Path("contracts/v1/sales30.labels.json")


def _valid_training_bundle(tmp_path: Path) -> tuple[dict[str, object], list[str]]:
    config = load_yaml(CONFIG_PATH)
    labels = ["Có"]
    media_root = tmp_path / "media"
    selected_files = []
    index_files = []
    manifest_rows = []
    counts = {"Có": {"train": 10, "validation": 2, "test": 3}}
    for index in range(15):
        source_split = "test" if index >= 12 else "train"
        split = "test" if index >= 12 else "validation" if index >= 10 else "train"
        filename = f"{index:06d}.mp4"
        local_path = f"{source_split}/Có/{filename}"
        remote_path = (
            "processed/processed/frame_splited/"
            f"{source_split}/Có/{filename}"
        )
        payload = f"clip-{index}".encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        media_path = media_root / local_path
        media_path.parent.mkdir(parents=True, exist_ok=True)
        media_path.write_bytes(payload)
        selected_files.append(
            {"name": remote_path, "total_bytes": len(payload)}
        )
        index_files.append(
            {
                "remote_path": remote_path,
                "local_path": local_path,
                "total_bytes": len(payload),
                "sha256": digest,
            }
        )
        manifest_rows.append(
            {
                "path": local_path,
                "label_id": 0,
                "label": "Có",
                "split": split,
                "source_id": SALES30_DATASET_REF,
                "source_revision": str(SALES30_VERSION),
                "source_label": "Có",
                "source_record_id": remote_path,
                "license": SALES30_LICENSE,
                "sha256": digest,
                "signer_id": "unknown",
                "group_id": "unknown",
                "view": "unknown",
                "take": "unknown",
                "source_split": source_split,
                "remote_path": remote_path,
                "split_strength": "development-only",
            }
        )

    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest_rows)

    source_audit = tmp_path / "source_audit.json"
    source_audit.write_text(
        json.dumps(
            {
                "dataset_ref": SALES30_DATASET_REF,
                "version": SALES30_VERSION,
                "license": SALES30_LICENSE,
                "coverage": {"Có": {"train": 12, "test": 3}},
                "selected_files": selected_files,
                "blockers": [],
                "warnings": [],
                "ready_for_baseline_training": True,
                "split_strength": "development-only",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    download_index = tmp_path / "download_index.json"
    download_index.write_text(
        json.dumps(
            {
                "dataset_ref": SALES30_DATASET_REF,
                "version": SALES30_VERSION,
                "license": SALES30_LICENSE,
                "files": index_files,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "counts": counts,
                "blockers": [],
                "warnings": [],
                "ready_for_baseline_training": True,
                "split_strength": "development-only",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config["data"] = {
        "manifest": str(manifest),
        "root": str(media_root),
        "download_index": str(download_index),
        "source_audit": str(source_audit),
        "readiness": str(readiness),
    }
    return config, labels


def test_sales30_config_matches_training_contract() -> None:
    config = load_yaml(CONFIG_PATH)
    labels = load_labels(LABELS_PATH)

    validate_training_config(config, labels)

    assert config["model"]["num_classes"] == 30
    assert config["input"]["frames"] == 16
    assert config["training"]["batch_size"] == 2
    assert config["training"]["gradient_accumulation_steps"] == 4
    assert config["training"]["epochs"] == 12
    assert config["augmentation"]["horizontal_flip"] is False


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    (
        ("model", "num_classes", 29, "num_classes"),
        ("source", "version", 7, "version 8"),
        ("labels", "source", "wrong.json", "sales30.labels.json"),
        ("split", "strength", "signer-independent", "development-only"),
    ),
)
def test_training_config_rejects_contract_drift(
    section: str, key: str, value: object, message: str
) -> None:
    config = load_yaml(CONFIG_PATH)
    labels = load_labels(LABELS_PATH)
    drifted = deepcopy(config)
    drifted[section][key] = value

    with pytest.raises(ValueError, match=message):
        validate_training_config(drifted, labels)


def test_checkpoint_metadata_marks_sales30_as_development_only() -> None:
    config = load_yaml(CONFIG_PATH)

    metadata = build_checkpoint_metadata(config, git_commit="abc123")

    assert metadata == {
        "source": "nguyenanfms/vsl-vietnamese-sign-language-v2",
        "source_version": 8,
        "split_strength": "development-only",
        "git_commit": "abc123",
        "development_only": True,
    }


def test_mvitv2_training_rejects_mps_with_actionable_message() -> None:
    with pytest.raises(RuntimeError, match="CPU smoke hoặc CUDA"):
        resolve_device("mps")


def test_legacy_common20_config_remains_supported() -> None:
    config = load_yaml(Path("ml/configs/visignlanguage_video_mvitv2_s.yaml"))
    labels = [f"label-{index}" for index in range(20)]

    validate_training_config(config, labels)
    metadata = build_checkpoint_metadata(config, git_commit="legacy")

    assert metadata["source"] == "star092304/ViSignLanguage-Video"
    assert metadata["source_version"] == config["source"]["revision"]
    assert metadata["split_strength"] == "development-only"
    assert metadata["development_only"] is True


def test_sales30_rejects_repository_drift_to_multivsl() -> None:
    config = load_yaml(CONFIG_PATH)
    labels = load_labels(LABELS_PATH)
    drifted = deepcopy(config)
    drifted["source"]["repository"] = "legacy/Multi-VSL"

    with pytest.raises(ValueError, match="VSL-472"):
        validate_training_config(drifted, labels)


def test_data_provenance_hashes_exact_training_inputs(tmp_path: Path) -> None:
    config = load_yaml(CONFIG_PATH)
    data = deepcopy(config["data"])
    for key in ("manifest", "download_index", "source_audit", "readiness"):
        path = tmp_path / f"{key}.txt"
        path.write_text(key, encoding="utf-8")
        data[key] = str(path)
    config["data"] = data

    provenance = build_data_provenance(config)

    assert set(provenance) == {
        "manifest_sha256",
        "download_index_sha256",
        "source_audit_sha256",
        "readiness_sha256",
    }
    assert all(len(value) == 64 for value in provenance.values())


def test_training_rejects_present_but_unapproved_provenance_bundle(
    tmp_path: Path,
) -> None:
    config = load_yaml(CONFIG_PATH)
    labels = load_labels(LABELS_PATH)
    data = deepcopy(config["data"])
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,label_id,label,split,source_id,source_revision,source_label,"
        "source_record_id,license,sha256,signer_id,group_id,view,take,"
        "source_split,remote_path,split_strength\n",
        encoding="utf-8",
    )
    source_audit = tmp_path / "source_audit.json"
    source_audit.write_text(
        '{"dataset_ref":"legacy/Multi-VSL","version":8,'
        '"license":"Attribution 4.0 International (CC BY 4.0)",'
        '"selected_files":[],"blockers":[],"warnings":[],'
        '"ready_for_baseline_training":true,"split_strength":"development-only"}',
        encoding="utf-8",
    )
    download_index = tmp_path / "download_index.json"
    download_index.write_text(
        '{"dataset_ref":"legacy/Multi-VSL","version":8,'
        '"license":"Attribution 4.0 International (CC BY 4.0)","files":[]}',
        encoding="utf-8",
    )
    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        '{"counts":{},"blockers":[],"warnings":[],'
        '"ready_for_baseline_training":true,"split_strength":"development-only"}',
        encoding="utf-8",
    )
    data.update(
        {
            "manifest": str(manifest),
            "root": str(tmp_path / "media"),
            "download_index": str(download_index),
            "source_audit": str(source_audit),
            "readiness": str(readiness),
        }
    )
    config["data"] = data

    with pytest.raises(ValueError, match="source_audit"):
        validate_training_data_bundle(config, labels)


def test_training_accepts_audited_provenance_bundle(tmp_path: Path) -> None:
    config, labels = _valid_training_bundle(tmp_path)

    validate_training_data_bundle(config, labels)


def test_training_rejects_readiness_counts_that_disagree_with_manifest(
    tmp_path: Path,
) -> None:
    config, labels = _valid_training_bundle(tmp_path)
    readiness_path = Path(str(config["data"]["readiness"]))
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["counts"]["Có"]["train"] = 9
    readiness_path.write_text(
        json.dumps(readiness, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="readiness.counts"):
        validate_training_data_bundle(config, labels)


@pytest.mark.parametrize("field", ("sha256", "local_path"))
def test_training_binds_manifest_rows_to_download_index(
    tmp_path: Path, field: str
) -> None:
    config, labels = _valid_training_bundle(tmp_path)
    index_path = Path(str(config["data"]["download_index"]))
    download_index = json.loads(index_path.read_text(encoding="utf-8"))
    download_index["files"][0][field] = (
        "0" * 64 if field == "sha256" else "train/Có/substituted.mp4"
    )
    index_path.write_text(
        json.dumps(download_index, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="download_index"):
        validate_training_data_bundle(config, labels)


def test_training_requires_identical_manifest_and_index_remote_paths(
    tmp_path: Path,
) -> None:
    config, labels = _valid_training_bundle(tmp_path)
    source_audit_path = Path(str(config["data"]["source_audit"]))
    index_path = Path(str(config["data"]["download_index"]))
    source_audit = json.loads(source_audit_path.read_text(encoding="utf-8"))
    download_index = json.loads(index_path.read_text(encoding="utf-8"))
    remote_path = "processed/processed/frame_splited/train/Có/extra.mp4"
    source_audit["selected_files"].append(
        {"name": remote_path, "total_bytes": 5}
    )
    download_index["files"].append(
        {
            "remote_path": remote_path,
            "local_path": "train/Có/extra.mp4",
            "total_bytes": 5,
            "sha256": hashlib.sha256(b"extra").hexdigest(),
        }
    )
    source_audit_path.write_text(
        json.dumps(source_audit, ensure_ascii=False), encoding="utf-8"
    )
    index_path.write_text(
        json.dumps(download_index, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="remote paths"):
        validate_training_data_bundle(config, labels)
