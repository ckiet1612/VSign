from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import av
import numpy as np
import torch
from PIL import Image, ImageEnhance
from torch import Tensor, nn
from torch.utils.data import Dataset
from torchvision.models.video import MViT_V2_S_Weights, mvit_v2_s


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
AV_ERROR = getattr(av, "AVError", getattr(av.error, "FFmpegError", OSError))


def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as error:  # pragma: no cover - actionable runtime message
        raise RuntimeError("Thiếu PyYAML. Chạy: pip install pyyaml") from error
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config không hợp lệ: {path}")
    return payload


def load_labels(path: Path) -> List[str]:
    labels = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(labels, list) or not labels or not all(
        isinstance(label, str) and label for label in labels
    ):
        raise ValueError(f"Label map phải là danh sách chuỗi không rỗng: {path}")
    if len(set(labels)) != len(labels):
        raise ValueError(f"Label map chứa nhãn trùng: {path}")
    return labels


def temporal_indices(frame_count: int, sample_count: int, training: bool) -> np.ndarray:
    if frame_count <= 0 or sample_count <= 0:
        raise ValueError("frame_count và sample_count phải lớn hơn 0")
    if frame_count == 1:
        return np.zeros(sample_count, dtype=np.int64)
    if not training:
        return np.rint(np.linspace(0, frame_count - 1, sample_count)).astype(np.int64)

    edges = np.linspace(0, frame_count, sample_count + 1)
    indices: List[int] = []
    for left, right in zip(edges[:-1], edges[1:]):
        low = min(frame_count - 1, int(np.floor(left)))
        high = min(frame_count, max(low + 1, int(np.ceil(right))))
        indices.append(random.randrange(low, high))
    return np.asarray(indices, dtype=np.int64)


def decode_video(path: Path) -> List[Image.Image]:
    frames: List[Image.Image] = []
    try:
        with av.open(str(path)) as container:
            for frame in container.decode(video=0):
                frames.append(frame.to_image().convert("RGB"))
    except (AV_ERROR, OSError, ValueError) as error:
        raise RuntimeError(f"Không đọc được video {path}: {error}") from error
    if not frames:
        raise RuntimeError(f"Video không có frame: {path}")
    return frames


def frames_to_tensor(
    frames: Sequence[Image.Image],
    *,
    frame_count: int,
    height: int,
    width: int,
    training: bool,
) -> Tensor:
    indices = temporal_indices(len(frames), frame_count, training)
    brightness = random.uniform(0.9, 1.1) if training else 1.0
    contrast = random.uniform(0.9, 1.1) if training else 1.0
    selected: List[np.ndarray] = []
    for index in indices:
        image = frames[int(index)].resize((width, height), Image.Resampling.BILINEAR)
        if training:
            image = ImageEnhance.Brightness(image).enhance(brightness)
            image = ImageEnhance.Contrast(image).enhance(contrast)
        selected.append(np.asarray(image, dtype=np.float32) / 255.0)
    array = np.stack(selected, axis=0)
    tensor = torch.from_numpy(array).permute(3, 0, 1, 2).contiguous()
    mean = torch.tensor(IMAGENET_MEAN, dtype=tensor.dtype).view(3, 1, 1, 1)
    std = torch.tensor(IMAGENET_STD, dtype=tensor.dtype).view(3, 1, 1, 1)
    return (tensor - mean) / std


@dataclass(frozen=True)
class ManifestItem:
    path: Path
    label_id: int
    label: str


class ViSignLanguageDataset(Dataset):
    def __init__(
        self,
        manifest_path: Path,
        data_root: Path,
        labels: Sequence[str],
        split: str,
        *,
        frame_count: int = 16,
        height: int = 224,
        width: int = 224,
        training: bool = False,
    ) -> None:
        self.frame_count = frame_count
        self.height = height
        self.width = width
        self.training = training
        self.items: List[ManifestItem] = []
        with manifest_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"path", "label_id", "label", "split"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Manifest thiếu cột: {', '.join(sorted(missing))}")
            for line_number, row in enumerate(reader, start=2):
                if row["split"] != split:
                    continue
                label_id = int(row["label_id"])
                if label_id < 0 or label_id >= len(labels):
                    raise ValueError(f"Manifest dòng {line_number}: label_id ngoài phạm vi")
                if row["label"] != labels[label_id]:
                    raise ValueError(f"Manifest dòng {line_number}: label không khớp label map")
                path = data_root / row["path"]
                if not path.is_file():
                    raise FileNotFoundError(f"Thiếu video: {path}")
                self.items.append(ManifestItem(path, label_id, row["label"]))
        if not self.items:
            raise ValueError(f"Split '{split}' không có video trong {manifest_path}")

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> tuple[Tensor, int]:
        item = self.items[index]
        frames = decode_video(item.path)
        tensor = frames_to_tensor(
            frames,
            frame_count=self.frame_count,
            height=self.height,
            width=self.width,
            training=self.training,
        )
        return tensor, item.label_id

    def class_counts(self, class_count: int) -> Tensor:
        counts = torch.zeros(class_count, dtype=torch.float32)
        for item in self.items:
            counts[item.label_id] += 1
        return counts


def build_model(class_count: int, *, pretrained: bool) -> nn.Module:
    weights = MViT_V2_S_Weights.KINETICS400_V1 if pretrained else None
    model = mvit_v2_s(weights=weights)
    input_features = model.head[-1].in_features
    model.head[-1] = nn.Linear(input_features, class_count)
    return model


def confusion_metrics(confusion: Tensor) -> Dict[str, float]:
    matrix = confusion.to(dtype=torch.float64)
    true_positive = matrix.diag()
    predicted = matrix.sum(dim=0)
    actual = matrix.sum(dim=1)
    precision = true_positive / predicted.clamp_min(1)
    recall = true_positive / actual.clamp_min(1)
    f1 = 2 * precision * recall / (precision + recall).clamp_min(1e-12)
    total = matrix.sum().item()
    return {
        "accuracy": float(true_positive.sum().item() / total) if total else 0.0,
        "macro_f1": float(f1.mean().item()),
        "macro_precision": float(precision.mean().item()),
        "macro_recall": float(recall.mean().item()),
    }


def update_confusion(confusion: Tensor, targets: Tensor, predictions: Tensor) -> None:
    class_count = confusion.shape[0]
    indices = targets.detach().cpu().long() * class_count + predictions.detach().cpu().long()
    confusion += torch.bincount(indices, minlength=class_count * class_count).reshape(
        class_count, class_count
    )


def topk_correct(logits: Tensor, targets: Tensor, top_k: Iterable[int]) -> Dict[int, int]:
    requested = sorted(set(top_k))
    maximum = min(max(requested), logits.shape[1])
    predictions = logits.topk(maximum, dim=1).indices
    return {
        k: int(predictions[:, : min(k, maximum)].eq(targets[:, None]).any(dim=1).sum().item())
        for k in requested
    }


def load_checkpoint(path: Path, device: torch.device) -> Dict[str, Any]:
    try:
        payload = torch.load(path, map_location=device, weights_only=False)
    except TypeError:  # torch 2.0
        payload = torch.load(path, map_location=device)
    if not isinstance(payload, dict) or "state_dict" not in payload:
        raise ValueError(f"Checkpoint không hợp lệ: {path}")
    return payload
