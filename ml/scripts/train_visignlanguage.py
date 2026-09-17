from __future__ import annotations

import argparse
import csv
import json
import math
import random
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Sequence

import numpy as np
import torch
from torch import Tensor, nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader

from ml.sales30_data import (
    SALES30_DATASET_REF,
    SALES30_LICENSE,
    SALES30_VERSION,
    audit_sales30_manifest,
    sha256_file,
)
from ml.visignlanguage import (
    ViSignLanguageDataset,
    build_model,
    confusion_metrics,
    load_labels,
    load_yaml,
    topk_correct,
    update_confusion,
)


def resolve_device(requested: str) -> torch.device:
    if requested == "mps":
        raise RuntimeError(
            "MViTv2-S sales-30 không chạy full training trên MPS; "
            "hãy dùng CPU smoke hoặc CUDA full training"
        )
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Đã chọn CUDA nhưng môi trường không có GPU")
    return torch.device(requested)


def validate_training_config(config: Dict[str, Any], labels: Sequence[str]) -> None:
    model = config.get("model")
    source = config.get("source")
    label_config = config.get("labels")
    split = config.get("split")
    if not all(isinstance(section, dict) for section in (model, source, label_config, split)):
        raise ValueError("Config sales-30 thiếu model/source/labels/split")
    assert isinstance(model, dict)
    assert isinstance(source, dict)
    assert isinstance(label_config, dict)
    assert isinstance(split, dict)
    if int(model.get("num_classes") or 0) != len(labels):
        raise ValueError("model.num_classes phải khớp label map")
    is_sales30 = (
        label_config.get("source") == "contracts/v1/sales30.labels.json"
        or str(config.get("experiment", {}).get("name", "")).startswith("sales30")
    )
    if not is_sales30:
        return
    if len(labels) != 30:
        raise ValueError(f"sales-30 cần đúng 30 labels, nhận {len(labels)}")
    if source.get("repository") != SALES30_DATASET_REF:
        raise ValueError(f"sales-30 chỉ chấp nhận nguồn VSL-472 {SALES30_DATASET_REF}")
    if int(source.get("version") or 0) != SALES30_VERSION:
        raise ValueError("source.version phải là version 8 đã audit")
    if source.get("license") != SALES30_LICENSE:
        raise ValueError(f"source.license phải là {SALES30_LICENSE}")
    if label_config.get("source") != "contracts/v1/sales30.labels.json":
        raise ValueError("labels.source phải là contracts/v1/sales30.labels.json")
    if split.get("strength") != "development-only":
        raise ValueError("split.strength phải là development-only")
    data = config.get("data")
    if not isinstance(data, dict):
        raise ValueError("Config sales-30 thiếu data")
    for key in ("manifest", "download_index", "source_audit", "readiness"):
        if not data.get(key):
            raise ValueError(f"data.{key} là provenance bắt buộc cho sales-30")


def validate_training_data_bundle(
    config: Dict[str, Any], labels: Sequence[str]
) -> None:
    label_config = config.get("labels")
    if not isinstance(label_config, dict) or label_config.get("source") != (
        "contracts/v1/sales30.labels.json"
    ):
        return
    data = config.get("data")
    if not isinstance(data, dict):
        raise ValueError("data provenance sales-30 không hợp lệ")

    def load_json_object(key: str) -> Dict[str, Any]:
        path = Path(str(data.get(key) or ""))
        if not path.is_file():
            raise ValueError(f"Thiếu {key}: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{key} không phải JSON hợp lệ: {path}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"{key} phải là JSON object: {path}")
        return payload

    source_audit = load_json_object("source_audit")
    expected_identity = {
        "dataset_ref": SALES30_DATASET_REF,
        "version": SALES30_VERSION,
        "license": SALES30_LICENSE,
    }
    for key, expected in expected_identity.items():
        if source_audit.get(key) != expected:
            raise ValueError(f"source_audit.{key} không đúng nguồn VSL-472 đã duyệt")
    if source_audit.get("blockers") != []:
        raise ValueError("source_audit còn blocker")
    if source_audit.get("ready_for_baseline_training") is not True:
        raise ValueError("source_audit chưa sẵn sàng cho baseline training")
    if source_audit.get("split_strength") != "development-only":
        raise ValueError("source_audit.split_strength phải là development-only")

    download_index = load_json_object("download_index")
    for key, expected in expected_identity.items():
        if download_index.get(key) != expected:
            raise ValueError(f"download_index.{key} không đúng source_audit")

    def remote_sizes(
        raw_files: Any, *, path_key: str, bundle_name: str
    ) -> Dict[str, int]:
        if not isinstance(raw_files, list):
            raise ValueError(f"{bundle_name} thiếu danh sách files hợp lệ")
        parsed: Dict[str, int] = {}
        for raw_file in raw_files:
            if not isinstance(raw_file, dict):
                raise ValueError(f"{bundle_name} có file entry không hợp lệ")
            remote_path = raw_file.get(path_key)
            total_bytes = raw_file.get("total_bytes")
            if (
                not isinstance(remote_path, str)
                or not remote_path
                or not isinstance(total_bytes, int)
                or total_bytes <= 0
            ):
                raise ValueError(f"{bundle_name} có path/size không hợp lệ")
            if remote_path in parsed:
                raise ValueError(f"{bundle_name} trùng remote path: {remote_path}")
            parsed[remote_path] = total_bytes
        return parsed

    selected_sizes = remote_sizes(
        source_audit.get("selected_files"),
        path_key="name",
        bundle_name="source_audit.selected_files",
    )
    indexed_sizes = remote_sizes(
        download_index.get("files"),
        path_key="remote_path",
        bundle_name="download_index.files",
    )
    if selected_sizes != indexed_sizes:
        raise ValueError(
            "download_index files không khớp source_audit selected paths/sizes"
        )
    index_entries: Dict[str, Dict[str, Any]] = {}
    for raw_entry in download_index["files"]:
        remote_path = str(raw_entry["remote_path"])
        local_path = raw_entry.get("local_path")
        digest = raw_entry.get("sha256")
        if not isinstance(local_path, str) or not local_path:
            raise ValueError(f"download_index local_path không hợp lệ: {remote_path}")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"download_index sha256 không hợp lệ: {remote_path}")
        index_entries[remote_path] = raw_entry

    readiness = load_json_object("readiness")
    if readiness.get("blockers") != []:
        raise ValueError("readiness còn blocker")
    if readiness.get("ready_for_baseline_training") is not True:
        raise ValueError("readiness chưa sẵn sàng cho baseline training")
    if readiness.get("split_strength") != "development-only":
        raise ValueError("readiness.split_strength phải là development-only")

    manifest_path = Path(str(data.get("manifest") or ""))
    data_root = Path(str(data.get("root") or ""))
    if not manifest_path.is_file():
        raise ValueError(f"Thiếu manifest: {manifest_path}")
    manifest_audit = audit_sales30_manifest(manifest_path, data_root, labels)
    if manifest_audit.errors:
        raise ValueError(
            "manifest audit thất bại: " + "; ".join(manifest_audit.errors)
        )
    with manifest_path.open(encoding="utf-8", newline="") as handle:
        manifest_rows = list(csv.DictReader(handle))
    manifest_entries = {
        str(row.get("remote_path") or ""): row for row in manifest_rows
    }
    if set(manifest_entries) != set(index_entries):
        raise ValueError(
            "manifest và download_index phải có cùng remote paths"
        )
    for remote_path, row in manifest_entries.items():
        index_entry = index_entries[remote_path]
        if row.get("path") != index_entry["local_path"]:
            raise ValueError(
                f"manifest path không khớp download_index: {remote_path}"
            )
        if row.get("sha256") != index_entry["sha256"]:
            raise ValueError(
                f"manifest sha256 không khớp download_index: {remote_path}"
            )
        media_path = data_root / str(row["path"])
        if media_path.stat().st_size != index_entry["total_bytes"]:
            raise ValueError(
                f"media bytes không khớp download_index: {remote_path}"
            )
    if readiness.get("counts") != manifest_audit.counts:
        raise ValueError("readiness.counts không khớp manifest audit counts")


def _current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def build_checkpoint_metadata(
    config: Dict[str, Any], *, git_commit: str | None = None
) -> Dict[str, Any]:
    source = config["source"]
    split_config = config["split"]
    split_strength = str(
        split_config.get("strength")
        or (
            "signer-independent"
            if split_config.get("signer_independent") is True
            else "development-only"
        )
    )
    return {
        "source": str(source["repository"]),
        "source_version": source.get("version", source.get("revision", "unknown")),
        "split_strength": split_strength,
        "git_commit": git_commit or _current_git_commit(),
        "development_only": split_strength == "development-only",
    }


def build_data_provenance(config: Dict[str, Any]) -> Dict[str, str]:
    data = config.get("data")
    if not isinstance(data, dict):
        return {}
    provenance: Dict[str, str] = {}
    for key in ("manifest", "download_index", "source_audit", "readiness"):
        raw_path = data.get(key)
        if not raw_path:
            continue
        path = Path(str(raw_path))
        if not path.is_file():
            raise FileNotFoundError(f"Thiếu data provenance {key}: {path}")
        provenance[f"{key}_sha256"] = sha256_file(path)
    return provenance


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def create_loader(
    dataset: ViSignLanguageDataset,
    *,
    batch_size: int,
    workers: int,
    shuffle: bool,
    device: torch.device,
) -> DataLoader:
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=workers,
        pin_memory=device.type == "cuda",
        persistent_workers=workers > 0,
    )


def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    class_count: int,
    *,
    optimizer: AdamW | None = None,
    scaler: torch.cuda.amp.GradScaler | None = None,
    accumulation_steps: int = 1,
    max_batches: int | None = None,
) -> Dict[str, float]:
    training = optimizer is not None
    model.train(training)
    confusion = torch.zeros((class_count, class_count), dtype=torch.int64)
    total_loss = 0.0
    total_samples = 0
    top3 = 0
    if training:
        optimizer.zero_grad(set_to_none=True)
    processed_batches = 0

    context = torch.enable_grad if training else torch.no_grad
    with context():
        for batch_index, (clips, targets) in enumerate(loader):
            if max_batches is not None and batch_index >= max_batches:
                break
            clips = clips.to(device, non_blocking=True)
            targets = targets.to(device, non_blocking=True)
            amp_enabled = device.type == "cuda"
            with torch.cuda.amp.autocast(enabled=amp_enabled):
                logits = model(clips)
                loss = criterion(logits, targets)
                scaled_loss = loss / accumulation_steps
            if training:
                assert optimizer is not None and scaler is not None
                scaler.scale(scaled_loss).backward()
                should_step = (batch_index + 1) % accumulation_steps == 0
                if should_step:
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad(set_to_none=True)

            predictions = logits.argmax(dim=1)
            update_confusion(confusion, targets, predictions)
            top3 += topk_correct(logits, targets, (3,))[3]
            batch_size = targets.shape[0]
            total_loss += float(loss.detach().item()) * batch_size
            total_samples += batch_size
            processed_batches += 1

    if training and processed_batches % accumulation_steps:
        assert optimizer is not None and scaler is not None
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad(set_to_none=True)
    metrics = confusion_metrics(confusion)
    metrics.update(
        {
            "loss": total_loss / max(total_samples, 1),
            "top3_accuracy": top3 / max(total_samples, 1),
            "samples": float(total_samples),
        }
    )
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train MViTv2-S cho VSign")
    parser.add_argument("--config", type=Path, default=Path("ml/configs/visignlanguage_video_mvitv2_s.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("runs/visignlanguage_common20"))
    parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda", "mps"), default="auto"
    )
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--num-workers", type=int)
    parser.add_argument("--max-train-batches", type=int)
    parser.add_argument("--max-val-batches", type=int)
    parser.add_argument("--no-pretrained", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_yaml(args.config)
    seed = int(config["experiment"]["seed"])
    seed_everything(seed)
    device = resolve_device(args.device)
    training = config["training"]
    epochs = args.epochs or int(training["epochs"])
    batch_size = args.batch_size or int(training["batch_size"])
    workers = args.num_workers if args.num_workers is not None else int(training["num_workers"])
    accumulation_steps = int(training.get("gradient_accumulation_steps", 1))
    manifest_path = Path(config["data"]["manifest"])
    data_root = Path(config["data"]["root"])
    label_path = Path(config["labels"]["source"])
    labels = load_labels(label_path)
    validate_training_config(config, labels)
    validate_training_data_bundle(config, labels)
    checkpoint_metadata = build_checkpoint_metadata(config)
    checkpoint_metadata.update(build_data_provenance(config))
    input_config = config["input"]

    train_dataset = ViSignLanguageDataset(
        manifest_path,
        data_root,
        labels,
        "train",
        frame_count=int(input_config["frames"]),
        height=int(input_config["height"]),
        width=int(input_config["width"]),
        training=True,
    )
    validation_dataset = ViSignLanguageDataset(
        manifest_path,
        data_root,
        labels,
        "validation",
        frame_count=int(input_config["frames"]),
        height=int(input_config["height"]),
        width=int(input_config["width"]),
        training=False,
    )
    train_loader = create_loader(
        train_dataset, batch_size=batch_size, workers=workers, shuffle=True, device=device
    )
    validation_loader = create_loader(
        validation_dataset, batch_size=batch_size, workers=workers, shuffle=False, device=device
    )

    model = build_model(len(labels), pretrained=not args.no_pretrained).to(device)
    counts = train_dataset.class_counts(len(labels))
    class_weights = counts.sum() / (len(labels) * counts.clamp_min(1))
    criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
    optimizer = AdamW(
        model.parameters(),
        lr=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )
    scheduler = CosineAnnealingLR(optimizer, T_max=max(epochs, 1), eta_min=float(training["min_learning_rate"]))
    scaler = torch.cuda.amp.GradScaler(enabled=device.type == "cuda")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps({
        "event": "start",
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "train_videos": len(train_dataset),
        "validation_videos": len(validation_dataset),
        "classes": len(labels),
        "epochs": epochs,
        "batch_size": batch_size,
    }, ensure_ascii=False))
    best_f1 = -math.inf
    history = []
    started = time.time()
    for epoch in range(1, epochs + 1):
        train_metrics = run_epoch(
            model,
            train_loader,
            criterion,
            device,
            len(labels),
            optimizer=optimizer,
            scaler=scaler,
            accumulation_steps=accumulation_steps,
            max_batches=args.max_train_batches,
        )
        validation_metrics = run_epoch(
            model,
            validation_loader,
            criterion,
            device,
            len(labels),
            max_batches=args.max_val_batches,
        )
        scheduler.step()
        record = {
            "epoch": epoch,
            "learning_rate": optimizer.param_groups[0]["lr"],
            "train": train_metrics,
            "validation": validation_metrics,
        }
        history.append(record)
        print(json.dumps(record, ensure_ascii=False))
        checkpoint: Dict[str, Any] = {
            "architecture": "mvit_v2_s",
            "state_dict": model.state_dict(),
            "labels": labels,
            "epoch": epoch,
            "metrics": record,
            "config": config,
            "input_shape": [1, 3, int(input_config["frames"]), int(input_config["height"]), int(input_config["width"])],
            **checkpoint_metadata,
        }
        torch.save(checkpoint, args.output_dir / "last.pt")
        if validation_metrics["macro_f1"] > best_f1:
            best_f1 = validation_metrics["macro_f1"]
            torch.save(checkpoint, args.output_dir / "best.pt")

    summary = {
        "best_validation_macro_f1": best_f1,
        "elapsed_seconds": time.time() - started,
        "history": history,
        "best_checkpoint": str(args.output_dir / "best.pt"),
        **checkpoint_metadata,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"event": "complete", **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
