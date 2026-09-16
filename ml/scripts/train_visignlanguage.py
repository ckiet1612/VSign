from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path
from typing import Any, Dict, Sequence

import numpy as np
import torch
from torch import Tensor, nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader

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
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Đã chọn CUDA nhưng môi trường không có GPU")
    return torch.device(requested)


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
    parser = argparse.ArgumentParser(description="Train MViTv2-S cho VSign Common-20")
    parser.add_argument("--config", type=Path, default=Path("ml/configs/visignlanguage_video_mvitv2_s.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("runs/visignlanguage_common20"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
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
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"event": "complete", **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
