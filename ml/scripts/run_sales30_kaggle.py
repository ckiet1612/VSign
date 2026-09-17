from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch
import yaml

from ml.sales30_data import (
    MANIFEST_FIELDS,
    SALES30_DATASET_REF,
    SALES30_LICENSE,
    SALES30_VERSION,
    KaggleFile,
    SourceInventory,
    audit_sales30_manifest,
    audit_source,
    build_sales30_manifest,
    list_kaggle_files,
    load_source_config,
    sha256_file,
)
from ml.scripts.evaluate_visignlanguage import main as evaluate_main
from ml.scripts.export_visignlanguage_onnx import main as export_main
from ml.scripts.train_visignlanguage import main as train_main
from ml.visignlanguage import load_labels, load_yaml


CANONICAL_SUFFIX = Path("processed/processed/frame_splited")


def _is_canonical_root(path: Path) -> bool:
    return (
        path.is_dir()
        and path.name == "frame_splited"
        and path.parent.name == "processed"
        and path.parent.parent.name == "processed"
        and (path / "train").is_dir()
        and (path / "test").is_dir()
    )


def find_attached_vsl472_root(input_root: Path) -> Path:
    matches = sorted(
        (path for path in input_root.rglob("frame_splited") if _is_canonical_root(path)),
        key=lambda path: path.as_posix(),
    )
    if not matches:
        raise FileNotFoundError(
            "Không tìm thấy VSL-472 canonical tree trong Kaggle input; "
            "attach dataset version 8 hoặc truyền --dataset-root"
        )
    if len(matches) > 1:
        raise ValueError(
            "Tìm thấy nhiều VSL-472 canonical tree; truyền --dataset-root để chọn rõ nguồn"
        )
    return matches[0]


def validate_attached_inventory(
    expected: SourceInventory, attached: SourceInventory
) -> None:
    if (
        expected.dataset_ref != SALES30_DATASET_REF
        or expected.version != SALES30_VERSION
        or expected.license_name != SALES30_LICENSE
    ):
        raise ValueError("Catalog công khai không đúng provenance VSL-472 version 8")
    expected_files = {
        item.name: item.total_bytes for item in expected.files
    }
    attached_files = {
        item.name: item.total_bytes for item in attached.files
    }
    if attached_files != expected_files:
        missing = len(set(expected_files) - set(attached_files))
        extra = len(set(attached_files) - set(expected_files))
        size_drift = sum(
            1
            for name in set(expected_files) & set(attached_files)
            if expected_files[name] != attached_files[name]
        )
        raise ValueError(
            "Attached dataset không khớp catalog version 8: "
            f"missing={missing}, extra={extra}, size_drift={size_drift}"
        )


def _resolve_dataset_root(value: Path | None, input_root: Path) -> Path:
    if value is None:
        return find_attached_vsl472_root(input_root)
    candidate = value.resolve()
    if _is_canonical_root(candidate):
        return candidate
    nested = candidate / CANONICAL_SUFFIX
    if _is_canonical_root(nested):
        return nested
    raise ValueError(
        f"--dataset-root không chứa canonical tree {CANONICAL_SUFFIX}: {value}"
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_manifest(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    temporary.replace(path)


def _prepare_attached_dataset(
    canonical_root: Path,
    output_root: Path,
    labels: Sequence[str],
    *,
    seed: int,
) -> tuple[Path, Path]:
    source_config = load_source_config(Path("ml/configs/sales30_sources.json"))
    files = []
    index_rows = []
    target_labels = set(labels)
    for source_split in ("train", "test"):
        for label in labels:
            label_root = canonical_root / source_split / label
            if not label_root.is_dir():
                continue
            for media_path in sorted(label_root.glob("*.mp4")):
                if label not in target_labels or media_path.is_symlink():
                    continue
                remote_path = (
                    f"{source_config.canonical_prefix}{source_split}/"
                    f"{label}/{media_path.name}"
                )
                relative_path = Path(source_split, label, media_path.name).as_posix()
                digest = sha256_file(media_path)
                files.append(KaggleFile(remote_path, media_path.stat().st_size))
                index_rows.append(
                    {
                        "remote_path": remote_path,
                        "local_path": relative_path,
                        "total_bytes": media_path.stat().st_size,
                        "sha256": digest,
                    }
                )
    inventory = SourceInventory(
        dataset_ref=source_config.dataset_ref,
        version=source_config.version,
        license_name=source_config.license_name,
        files=tuple(files),
    )
    public_inventory = list_kaggle_files(source_config)
    source_audit = audit_source(source_config, labels, public_inventory)
    if source_audit.blockers:
        raise RuntimeError(
            f"Public VSL-472 catalog không đạt source gate: {source_audit.blockers}"
        )
    expected_inventory = SourceInventory(
        dataset_ref=source_audit.dataset_ref,
        version=source_audit.version,
        license_name=source_audit.license_name,
        files=source_audit.selected_files,
    )
    validate_attached_inventory(expected_inventory, inventory)

    data_root = output_root / "data"
    media_link = data_root / "media"
    data_root.mkdir(parents=True, exist_ok=True)
    if media_link.is_symlink():
        if media_link.resolve() != canonical_root.resolve():
            raise ValueError(f"Media symlink đang trỏ sai nguồn: {media_link}")
    elif media_link.exists():
        raise ValueError(f"Media path đã tồn tại và không phải symlink: {media_link}")
    else:
        media_link.symlink_to(canonical_root.resolve(), target_is_directory=True)

    _write_json(
        data_root / "download_index.json",
        {
            "dataset_ref": inventory.dataset_ref,
            "version": inventory.version,
            "license": inventory.license_name,
            "files": index_rows,
        },
    )
    _write_json(data_root / "source_audit.json", source_audit.to_dict())
    rows, readiness = build_sales30_manifest(
        data_root,
        labels,
        inventory,
        seed=seed,
        minimum_total_clips=source_config.minimum_total_clips,
    )
    _write_manifest(data_root / "manifest.csv", [row.to_dict() for row in rows])
    _write_json(data_root / "readiness.json", readiness.to_dict())
    manifest_audit = audit_sales30_manifest(
        data_root / "manifest.csv",
        media_link,
        labels,
        minimum_total_clips=source_config.minimum_total_clips,
    )
    _write_json(data_root / "manifest_audit.json", manifest_audit.to_dict())
    if readiness.blockers or manifest_audit.errors:
        raise RuntimeError(
            "Attached VSL-472 không đạt manifest gate: "
            f"{readiness.blockers or manifest_audit.errors}"
        )
    return data_root / "manifest.csv", media_link


def _write_runtime_config(
    output: Path, manifest: Path, data_root: Path
) -> dict[str, Any]:
    config = deepcopy(load_yaml(Path("ml/configs/sales30_mvitv2_s.yaml")))
    config["data"]["manifest"] = str(manifest)
    config["data"]["root"] = str(data_root)
    config["data"]["download_index"] = str(manifest.parent / "download_index.json")
    config["data"]["source_audit"] = str(manifest.parent / "source_audit.json")
    config["data"]["readiness"] = str(manifest.parent / "readiness.json")
    output.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train, test và export sales-30 trên Kaggle CUDA"
    )
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--input-root", type=Path, default=Path("/kaggle/input"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/kaggle/working/vsign-sales30-artifacts"),
    )
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--num-workers", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not torch.cuda.is_available():
        raise RuntimeError("Full sales-30 training yêu cầu Kaggle CUDA GPU")
    canonical_root = _resolve_dataset_root(args.dataset_root, args.input_root)
    labels = load_labels(Path("contracts/v1/sales30.labels.json"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest, data_root = _prepare_attached_dataset(
        canonical_root,
        args.output_dir,
        labels,
        seed=20260918,
    )
    runtime_config = args.output_dir / "sales30_mvitv2_s.runtime.yaml"
    _write_runtime_config(runtime_config, manifest, data_root)
    training_dir = args.output_dir / "training"
    train_main(
        [
            "--config",
            str(runtime_config),
            "--output-dir",
            str(training_dir),
            "--device",
            "cuda",
            "--epochs",
            str(args.epochs),
            "--batch-size",
            str(args.batch_size),
            "--num-workers",
            str(args.num_workers),
        ]
    )
    best_checkpoint = training_dir / "best.pt"
    test_metrics = args.output_dir / "test_metrics.json"
    evaluate_main(
        [
            "--checkpoint",
            str(best_checkpoint),
            "--split",
            "test",
            "--device",
            "cuda",
            "--batch-size",
            str(args.batch_size),
            "--num-workers",
            str(args.num_workers),
            "--output",
            str(test_metrics),
        ]
    )
    model_path = args.output_dir / "model.onnx"
    labels_path = args.output_dir / "labels.json"
    export_main(
        [
            "--checkpoint",
            str(best_checkpoint),
            "--output",
            str(model_path),
            "--labels-output",
            str(labels_path),
        ]
    )
    artifacts = (
        best_checkpoint,
        training_dir / "summary.json",
        runtime_config,
        test_metrics,
        model_path,
        labels_path,
        args.output_dir / "data/readiness.json",
        args.output_dir / "data/manifest_audit.json",
        args.output_dir / "data/manifest.csv",
        args.output_dir / "data/download_index.json",
        args.output_dir / "data/source_audit.json",
    )
    _write_json(
        args.output_dir / "artifact_manifest.json",
        {
            "source": "nguyenanfms/vsl-vietnamese-sign-language-v2",
            "source_version": 8,
            "device": torch.cuda.get_device_name(0),
            "development_only": True,
            "files": [
                {
                    "path": os.path.relpath(path, args.output_dir),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in artifacts
            ],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
