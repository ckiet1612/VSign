from __future__ import annotations

import base64
import binascii
import io
import re
from typing import List, Sequence

from PIL import Image, UnidentifiedImageError

from app.backends.base import DecodedFrame


DATA_URL_RE = re.compile(
    r"^data:(image/(?:jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})$"
)
PIL_FORMAT_BY_MIME = {"image/jpeg": "JPEG", "image/webp": "WEBP"}
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 16_000_000


class FrameValidationError(ValueError):
    pass


def decode_frames(data_urls: Sequence[str], max_frame_bytes: int) -> List[DecodedFrame]:
    decoded_frames: List[DecodedFrame] = []
    try:
        for data_url in data_urls:
            match = DATA_URL_RE.fullmatch(data_url)
            if match is None:
                raise FrameValidationError("Frame phải là JPEG/WebP data URL hợp lệ")
            mime_type, encoded = match.groups()
            estimated_size = (len(encoded) * 3) // 4
            if estimated_size > max_frame_bytes:
                raise FrameValidationError("Frame vượt giới hạn kích thước")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise FrameValidationError("Base64 của frame không hợp lệ") from exc
            if not raw or len(raw) > max_frame_bytes:
                raise FrameValidationError("Frame rỗng hoặc vượt giới hạn kích thước")
            try:
                with Image.open(io.BytesIO(raw)) as source:
                    width, height = source.size
                    if (
                        width < 1
                        or height < 1
                        or width > MAX_IMAGE_DIMENSION
                        or height > MAX_IMAGE_DIMENSION
                        or width * height > MAX_IMAGE_PIXELS
                    ):
                        raise FrameValidationError("Kích thước ảnh không an toàn")
                    source.verify()
                with Image.open(io.BytesIO(raw)) as source:
                    if source.format != PIL_FORMAT_BY_MIME[mime_type]:
                        raise FrameValidationError("MIME không khớp nội dung ảnh")
                    image = source.convert("RGB")
                    image.load()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise FrameValidationError("Không thể decode frame") from exc
            decoded_frames.append(DecodedFrame(image=image, encoded_bytes=raw))
    except Exception:
        for frame in decoded_frames:
            frame.image.close()
        raise
    return decoded_frames


def close_frames(frames: Sequence[DecodedFrame]) -> None:
    for frame in frames:
        frame.image.close()
