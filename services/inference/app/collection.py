from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Dict, Sequence
from uuid import UUID, uuid4

import numpy as np
from PIL import Image

from app.backends.base import DecodedFrame
from app.models import CollectionHand, CollectionHandCounts


def label_slug(label: str) -> str:
    normalized = unicodedata.normalize("NFD", label).replace("đ", "d").replace("Đ", "D")
    ascii_label = "".join(character for character in normalized if not unicodedata.combining(character))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_label.lower()).strip("-")
    if not slug:
        raise ValueError("Không thể tạo tên thư mục an toàn cho nhãn")
    return slug


def sample_counts(root: Path, labels: Sequence[str]) -> Dict[str, CollectionHandCounts]:
    counts: Dict[str, CollectionHandCounts] = {}
    for label in labels:
        label_dir = root / label_slug(label)
        counts[label] = CollectionHandCounts(
            right=sum(1 for _ in (label_dir / "right").glob("*.mp4")),
            left=sum(1 for _ in (label_dir / "left").glob("*.mp4")),
        )
    return counts


def _encode_video(path: Path, frames: Sequence[DecodedFrame], duration_ms: int) -> None:
    try:
        import av
    except ImportError as error:  # pragma: no cover - installation failure
        raise RuntimeError("Thiếu PyAV để lưu video thu thập") from error

    rate = Fraction(len(frames) * 1000, duration_ms).limit_denominator(1000)
    with av.open(str(path), mode="w", format="mp4") as container:
        stream = container.add_stream("libx264", rate=rate)
        stream.width = 224
        stream.height = 224
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "20", "preset": "medium"}
        for decoded in frames:
            image = decoded.image.convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)
            frame = av.VideoFrame.from_ndarray(np.asarray(image), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def save_collection_sample(
    root: Path,
    *,
    frames: Sequence[DecodedFrame],
    session_id: UUID,
    captured_at: int,
    duration_ms: int,
    expected_label: str,
    hand: CollectionHand,
    predicted_label: str | None,
    predicted_confidence: float | None,
    distance: str,
    lighting: str,
    negative_action: str | None,
    model_version: str,
) -> tuple[str, str, int]:
    hand_value = hand.value
    destination = root / label_slug(expected_label) / hand_value
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sample_id = f"{timestamp}-{uuid4().hex[:10]}"
    video_path = destination / f"{sample_id}.mp4"
    metadata_path = destination / f"{sample_id}.json"
    temporary_video = destination / f".{sample_id}.video.tmp"
    temporary_metadata = destination / f".{sample_id}.metadata.tmp"
    try:
        _encode_video(temporary_video, frames, duration_ms)
        metadata = {
            "schema_version": "1.0",
            "sample_id": sample_id,
            "video_file": video_path.name,
            "expected_label": expected_label,
            "hand": hand_value,
            "captured_at": captured_at,
            "duration_ms": duration_ms,
            "frame_count": len(frames),
            "width": 224,
            "height": 224,
            "session_id": str(session_id),
            "predicted_label": predicted_label,
            "predicted_confidence": predicted_confidence,
            "distance": distance,
            "lighting": lighting,
            "negative_action": negative_action,
            "model_version": model_version,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_video.replace(video_path)
        temporary_metadata.replace(metadata_path)
    except Exception:
        temporary_video.unlink(missing_ok=True)
        temporary_metadata.unlink(missing_ok=True)
        video_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        raise
    relative_path = video_path.relative_to(root).as_posix()
    count = sum(1 for _ in destination.glob("*.mp4"))
    return sample_id, relative_path, count
