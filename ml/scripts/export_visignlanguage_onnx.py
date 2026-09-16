from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import torch

from ml.visignlanguage import build_model, load_checkpoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Xuất checkpoint VSign sang ONNX")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--labels-output", type=Path)
    parser.add_argument("--opset", type=int, default=17)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checkpoint = load_checkpoint(args.checkpoint, torch.device("cpu"))
    labels = checkpoint.get("labels")
    input_shape = checkpoint.get("input_shape", [1, 3, 16, 224, 224])
    if not isinstance(labels, list) or not labels:
        raise ValueError("Checkpoint thiếu labels")
    if input_shape != [1, 3, 16, 224, 224]:
        raise ValueError(f"Input shape không tương thích backend web: {input_shape}")
    model = build_model(len(labels), pretrained=False).eval()
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    example = torch.zeros(tuple(input_shape), dtype=torch.float32)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        example,
        args.output,
        export_params=True,
        opset_version=args.opset,
        do_constant_folding=True,
        input_names=["frames"],
        output_names=["logits"],
        dynamic_axes={"frames": {0: "batch"}, "logits": {0: "batch"}},
    )
    labels_output = args.labels_output or args.output.with_name("labels.json")
    labels_output.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"ONNX: {args.output}")
    print(f"Labels: {labels_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
