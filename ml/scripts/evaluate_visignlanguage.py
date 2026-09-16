from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import torch
from torch import nn

from ml.scripts.train_visignlanguage import create_loader, resolve_device, run_epoch
from ml.visignlanguage import ViSignLanguageDataset, build_model, load_checkpoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Đánh giá checkpoint VSign Common-20")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    device = resolve_device(args.device)
    checkpoint = load_checkpoint(args.checkpoint, device)
    labels = checkpoint.get("labels")
    config = checkpoint.get("config")
    if not isinstance(labels, list) or not labels or not isinstance(config, dict):
        raise ValueError("Checkpoint thiếu labels hoặc config")
    input_config = config["input"]
    dataset = ViSignLanguageDataset(
        Path(config["data"]["manifest"]),
        Path(config["data"]["root"]),
        labels,
        args.split,
        frame_count=int(input_config["frames"]),
        height=int(input_config["height"]),
        width=int(input_config["width"]),
        training=False,
    )
    loader = create_loader(
        dataset,
        batch_size=args.batch_size,
        workers=args.num_workers,
        shuffle=False,
        device=device,
    )
    model = build_model(len(labels), pretrained=False).to(device)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    metrics = run_epoch(
        model,
        loader,
        nn.CrossEntropyLoss(),
        device,
        len(labels),
        max_batches=args.max_batches,
    )
    result = {
        "checkpoint": str(args.checkpoint),
        "checkpoint_epoch": checkpoint.get("epoch"),
        "split": args.split,
        "video_count": len(dataset),
        "device": str(device),
        "metrics": metrics,
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(payload, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
