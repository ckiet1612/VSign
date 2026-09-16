from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import numpy as np


CLASS_ID_PATTERN = re.compile(r"_(\d+)\.mp4$", re.IGNORECASE)


def _sample_indices(frame_count: int, sample_count: int = 16) -> np.ndarray:
    if frame_count <= 0:
        raise ValueError("Video không có frame")
    return np.linspace(0, frame_count - 1, sample_count).round().astype(int)


def _decode_clip(path: Path) -> np.ndarray:
    try:
        import av
    except ImportError as exc:
        raise RuntimeError("Thiếu PyAV; cài dependencies trong ml/requirements.txt") from exc

    with av.open(str(path)) as container:
        frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
    if not frames:
        raise RuntimeError(f"Không decode được frame từ {path}")

    from PIL import Image

    arrays = []
    for index in _sample_indices(len(frames)):
        image = Image.fromarray(frames[int(index)]).resize(
            (224, 224), Image.Resampling.BILINEAR
        )
        arrays.append(np.asarray(image, dtype=np.float32) / 255.0)
    clip = np.stack(arrays)
    mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
    return np.transpose((clip - mean) / std, (3, 0, 1, 2))[None, ...]


def _class_id(path: Path) -> int:
    match = CLASS_ID_PATTERN.search(path.name)
    if not match:
        raise ValueError(f"Không đọc được class ID ở cuối filename: {path.name}")
    return int(match.group(1))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test checkpoint MViTv2-S trên video Multi-VSL có class ID trong tên file"
    )
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("videos", type=Path)
    parser.add_argument("--max-samples", type=int, default=10)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        import torch
        from torchvision.models.video import mvit_v2_s
    except ImportError as exc:
        raise RuntimeError("Thiếu torch/torchvision; cài ml/requirements.txt") from exc

    if args.max_samples <= 0:
        raise ValueError("--max-samples phải lớn hơn 0")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA không khả dụng")
    video_paths = sorted(args.videos.rglob("*.mp4"))[: args.max_samples]
    if not video_paths:
        raise RuntimeError(f"Không tìm thấy video .mp4 trong {args.videos}")

    state_dict = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model = mvit_v2_s(weights=None)
    model.head[-1] = torch.nn.Linear(model.head[-1].in_features, 1000)
    model.load_state_dict(state_dict, strict=True)
    model = model.to(args.device).eval()

    correct_top1 = 0
    correct_top5 = 0
    latencies_ms: list[float] = []
    samples = []
    for path in video_paths:
        truth = _class_id(path)
        tensor = torch.from_numpy(_decode_clip(path)).to(args.device)
        started = time.perf_counter()
        with torch.inference_mode():
            probabilities = torch.softmax(model(tensor), dim=1)[0]
        if args.device == "cuda":
            torch.cuda.synchronize()
        latency_ms = (time.perf_counter() - started) * 1000
        top5 = probabilities.topk(5).indices.detach().cpu().tolist()
        correct_top1 += int(top5[0] == truth)
        correct_top5 += int(truth in top5)
        latencies_ms.append(latency_ms)
        samples.append(
            {
                "file": path.name,
                "truth": truth,
                "top1": top5[0],
                "confidence": float(probabilities[top5[0]].detach().cpu()),
                "latency_ms": round(latency_ms, 1),
            }
        )

    result = {
        "checkpoint": str(args.checkpoint),
        "device": args.device,
        "sample_count": len(samples),
        "top1_accuracy": correct_top1 / len(samples),
        "top5_accuracy": correct_top5 / len(samples),
        "latency_ms_mean": sum(latencies_ms) / len(latencies_ms),
        "samples": samples,
        "note": "Class ID kỹ thuật; không suy diễn thành từ tiếng Việt.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if correct_top1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
