from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from contracts.v1.inference import FRAME_COUNT, FRAME_SIZE, PROTOCOL_VERSION


class ModelManifestError(RuntimeError):
    """Raised when a model artifact is not compatible with the runtime contract."""


def labels_digest(labels: Sequence[str]) -> str:
    payload = json.dumps(list(labels), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelManifest:
    model_version: str
    artifact_sha256: str
    labels_sha256: str
    backend: str
    protocol_version: str
    frame_count: int
    frame_size: int
    preprocessing_version: str
    confidence_threshold: float
    margin_threshold: float
    source_run_id: str
    status: str

    @classmethod
    def from_path(cls, path: Path) -> "ModelManifest":
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ModelManifestError(f"Không tìm thấy model manifest: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelManifestError(f"Không đọc được model manifest: {path}") from exc
        if not isinstance(payload, dict):
            raise ModelManifestError("Model manifest phải là một object JSON")
        required = (
            "model_version", "artifact_sha256", "labels_sha256", "backend",
            "protocol_version", "frame_count", "frame_size", "preprocessing_version",
            "confidence_threshold", "margin_threshold", "source_run_id", "status",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ModelManifestError(f"Model manifest thiếu trường: {', '.join(missing)}")
        try:
            manifest = cls(
                model_version=str(payload["model_version"]),
                artifact_sha256=str(payload["artifact_sha256"]),
                labels_sha256=str(payload["labels_sha256"]),
                backend=str(payload["backend"]),
                protocol_version=str(payload["protocol_version"]),
                frame_count=int(payload["frame_count"]),
                frame_size=int(payload["frame_size"]),
                preprocessing_version=str(payload["preprocessing_version"]),
                confidence_threshold=float(payload["confidence_threshold"]),
                margin_threshold=float(payload["margin_threshold"]),
                source_run_id=str(payload["source_run_id"]),
                status=str(payload["status"]),
            )
        except (TypeError, ValueError) as exc:
            raise ModelManifestError("Model manifest có kiểu dữ liệu không hợp lệ") from exc
        if len(manifest.artifact_sha256) != 64 or len(manifest.labels_sha256) != 64:
            raise ModelManifestError("Model manifest cần SHA256 hợp lệ")
        if manifest.status not in {"candidate", "approved", "production", "retired"}:
            raise ModelManifestError(f"Trạng thái model không hợp lệ: {manifest.status}")
        return manifest

    def validate(
        self,
        *,
        app_environment: str,
        backend: str,
        model_version: str,
        labels: Sequence[str],
        confidence_threshold: float,
        margin_threshold: float,
    ) -> None:
        mismatches: list[str] = []
        if self.model_version != model_version:
            mismatches.append("model_version")
        if self.backend != backend:
            mismatches.append("backend")
        if self.protocol_version != PROTOCOL_VERSION:
            mismatches.append("protocol_version")
        if self.frame_count != FRAME_COUNT:
            mismatches.append("frame_count")
        if self.frame_size != FRAME_SIZE:
            mismatches.append("frame_size")
        if self.labels_sha256 != labels_digest(labels):
            mismatches.append("labels_sha256")
        if self.confidence_threshold != confidence_threshold:
            mismatches.append("confidence_threshold")
        if self.margin_threshold != margin_threshold:
            mismatches.append("margin_threshold")
        if app_environment == "production" and self.status != "production":
            mismatches.append("status=production")
        if mismatches:
            raise ModelManifestError(
                "Model manifest không khớp runtime: " + ", ".join(mismatches)
            )


def load_model_manifest(path: Path | None) -> ModelManifest | None:
    return ModelManifest.from_path(path) if path is not None else None
