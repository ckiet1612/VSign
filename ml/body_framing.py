"""``trim-bodycrop-v1``: keep only the signing span and frame the clip around the signer.

This module is the reference implementation. ``apps/web/src/lib/bodyFraming.ts`` must
produce the same span and box; both are checked against ``contracts/v1/framing_golden.json``.

Observations use MediaPipe's normalized, unmirrored image coordinates. Each frame is
``{"t": ms, "pose": [[x, y, visibility] for POSE_INDICES] | None,
"hands": [[wrist_x, wrist_y, min_x, min_y, max_x, max_y], ...]}``.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Optional, Sequence

import numpy as np
from PIL import Image

PREPROCESSING_VERSION = "trim-bodycrop-v1"
# MediaPipe pose: nose, left/right shoulder, left/right elbow, left/right wrist.
POSE_INDICES = (0, 11, 12, 13, 14, 15, 16)
NOSE, LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_WRIST, RIGHT_WRIST = 0, 1, 2, 5, 6

VISIBLE = 0.5
MIN_SHOULDER_FRAMES = 3
# Distances below are in shoulder widths, measured from the shoulder midpoint.
REST_LINE = 1.1
BOX_SIDE = 2.6
BOX_CENTER_DROP = -0.15  # negative: centre above the shoulder line
MIN_BOX_FRACTION = 0.25
SPAN_PAD_MS = 100.0

Frame = dict[str, Any]


def _shoulders(frame: Frame, width: float, height: float) -> Optional[tuple[float, float, float]]:
    pose = frame.get("pose")
    if not pose:
        return None
    left, right = pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]
    if left[2] <= VISIBLE or right[2] <= VISIBLE:
        return None
    lx, ly, rx, ry = left[0] * width, left[1] * height, right[0] * width, right[1] * height
    span = math.hypot(lx - rx, ly - ry)
    if span <= 0:
        return None
    return (lx + rx) / 2, (ly + ry) / 2, span


def body_anchor(frames: Sequence[Frame], width: float, height: float) -> Optional[tuple[float, float, float]]:
    """Median shoulder midpoint and shoulder width in pixels, or None without a stable body."""
    found = [value for frame in frames if (value := _shoulders(frame, width, height))]
    if len(found) < MIN_SHOULDER_FRAMES:
        return None
    return (median(value[0] for value in found), median(value[1] for value in found),
            median(value[2] for value in found))


def _active(frame: Frame, rest_y: Optional[float], height: float) -> bool:
    for hand in frame.get("hands") or ():
        if rest_y is None or hand[1] * height < rest_y:
            return True
    pose = frame.get("pose")
    if rest_y is not None and pose:
        for index in (LEFT_WRIST, RIGHT_WRIST):
            x, y, visibility = pose[index]
            if visibility > VISIBLE and y * height < rest_y:
                return True
    return False


def trim_span(frames: Sequence[Frame], width: float, height: float) -> tuple[int, int]:
    """Inclusive frame range from the first to the last raised hand, padded by SPAN_PAD_MS."""
    if not frames:
        raise ValueError("No frames to trim")
    anchor = body_anchor(frames, width, height)
    rest_y = anchor[1] + REST_LINE * anchor[2] if anchor else None
    active = [index for index, frame in enumerate(frames) if _active(frame, rest_y, height)]
    if len(active) < 2:
        return 0, len(frames) - 1
    first_time = frames[active[0]]["t"] - SPAN_PAD_MS
    last_time = frames[active[-1]]["t"] + SPAN_PAD_MS
    start = next(index for index, frame in enumerate(frames) if frame["t"] >= first_time)
    end = max(index for index, frame in enumerate(frames) if frame["t"] <= last_time)
    return start, end


def body_box(frames: Sequence[Frame], width: float, height: float) -> Optional[dict[str, float]]:
    """Normalized square crop around the signer; it may extend past the image edges."""
    anchor = body_anchor(frames, width, height)
    if anchor is None:
        return None
    center_x, shoulder_y, shoulder_width = anchor
    side = max(BOX_SIDE * shoulder_width, MIN_BOX_FRACTION * min(width, height))
    center_y = shoulder_y + BOX_CENTER_DROP * shoulder_width
    return {"x": (center_x - side / 2) / width, "y": (center_y - side / 2) / height,
            "width": side / width, "height": side / height}


def center_square(width: float, height: float) -> dict[str, float]:
    side = min(width, height)
    return {"x": (width - side) / 2 / width, "y": (height - side) / 2 / height,
            "width": side / width, "height": side / height}


def _round(value: float) -> int:
    # Math.round in the browser rounds halves up; Python's round() would round to even.
    return math.floor(value + 0.5)


def draw_plan(box: dict[str, float], width: int, height: int, size: int) -> Optional[tuple[tuple[float, float, float, float], tuple[int, int, int, int]]]:
    """Source rectangle (inside the image) and integer destination rectangle for a padded crop."""
    left, top = box["x"] * width, box["y"] * height
    crop_width, crop_height = box["width"] * width, box["height"] * height
    source_left, source_top = max(0.0, left), max(0.0, top)
    source_right, source_bottom = min(float(width), left + crop_width), min(float(height), top + crop_height)
    if source_right <= source_left or source_bottom <= source_top:
        return None
    scale_x, scale_y = size / crop_width, size / crop_height
    destination_left = _round((source_left - left) * scale_x)
    destination_top = _round((source_top - top) * scale_y)
    destination_right = _round((source_right - left) * scale_x)
    destination_bottom = _round((source_bottom - top) * scale_y)
    if destination_right <= destination_left or destination_bottom <= destination_top:
        return None
    return ((source_left, source_top, source_right - source_left, source_bottom - source_top),
            (destination_left, destination_top, destination_right - destination_left, destination_bottom - destination_top))


def load_observations(directory: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for shard in sorted(directory.glob("observations_*.jsonl")):
        for line in shard.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            records[record["path"]] = record
    return records


def observations_digest(records: dict[str, dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for path in sorted(records):
        digest.update(json.dumps(records[path], sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def frame_clip(images: Sequence[Image.Image], record: dict[str, Any], sample_count: int = 16,
               size: int = 224) -> list[Image.Image]:
    """Trim decoded frames to the signing span, sample uniformly, and crop around the body."""
    frames = record["frames"]
    if len(images) != len(frames):
        raise ValueError(f"Decoded {len(images)} frames but observed {len(frames)}: {record['path']}")
    width, height = record["width"], record["height"]
    start, end = trim_span(frames, width, height)
    box = body_box(frames, width, height) or center_square(width, height)
    indices = np.rint(np.linspace(start, end, sample_count)).astype(np.int64)
    return [apply_box(images[int(index)], box, size) for index in indices]


def apply_box(image: Image.Image, box: dict[str, float], size: int = 224) -> Image.Image:
    """Crop ``image`` to ``box`` on a black canvas, resized to ``size`` x ``size``."""
    canvas = Image.new("RGB", (size, size), (0, 0, 0))
    plan = draw_plan(box, image.width, image.height, size)
    if plan is None:
        return canvas
    (sx, sy, sw, sh), (dx, dy, dw, dh) = plan
    region = image.convert("RGB").resize((dw, dh), Image.Resampling.BILINEAR, box=(sx, sy, sx + sw, sy + sh))
    canvas.paste(region, (dx, dy))
    return canvas
