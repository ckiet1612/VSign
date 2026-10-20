from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.backends.coreml_artifact import package_hash
from app.backends.labels import load_labels
from app.model_manifest import labels_digest

PREPROCESSING_VERSION = "rgb16-224-imagenet-v1"


class RegistryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    model_version: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    labels_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    backend: Literal["coreml", "onnx", "pytorch"]
    protocol_version: Literal["1.0"]
    frame_count: Literal[16]
    frame_size: Literal[224]
    preprocessing_version: Literal["rgb16-224-imagenet-v1"]
    confidence_threshold: float = Field(ge=0, le=1)
    margin_threshold: float = Field(ge=0, le=1)
    source_run_id: str = Field(min_length=1, max_length=160)
    status: Literal["candidate", "production"]
    labels_file_sha256: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    development_only: Optional[bool] = None


def checked_local_path(value: str | Path, roots: tuple[Path, ...]) -> Path:
    path = Path(value).expanduser().absolute()
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Đường dẫn không được chứa symlink hoặc '..'")
    resolved = path.resolve(strict=True)
    if not roots or not any(resolved.is_relative_to(root.expanduser().resolve()) for root in roots):
        raise ValueError("Đường dẫn nằm ngoài thư mục được cho phép")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, max_bytes: int = 1024 * 1024):
    with path.open("rb") as stream:
        payload = stream.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("Tệp JSON vượt giới hạn kích thước")
    return json.loads(payload)


def artifact_digest(path: Path, backend: str) -> str:
    if backend == "coreml":
        if path.suffix != ".mlpackage":
            raise ValueError("Core ML cần artifact .mlpackage")
        return package_hash(path)
    suffixes = {"onnx": {".onnx"}, "pytorch": {".pt", ".pth"}}
    if not path.is_file() or path.suffix not in suffixes.get(backend, set()):
        raise ValueError("Loại artifact không khớp backend")
    return sha256_file(path)


def verify_artifacts(manifest: RegistryManifest, artifact: Path, labels_path: Path) -> list[str]:
    if labels_path.stat().st_size > 1024 * 1024:
        raise ValueError("Label map vượt giới hạn kích thước")
    labels = load_labels(labels_path)
    if manifest.labels_file_sha256 is not None and sha256_file(labels_path) != manifest.labels_file_sha256:
        raise ValueError("SHA256 tệp bộ nhãn không khớp manifest")
    if (artifact_digest(artifact, manifest.backend) != manifest.artifact_sha256
            or labels_digest(labels) != manifest.labels_sha256):
        raise ValueError("SHA256 artifact hoặc bộ nhãn không khớp manifest")
    return labels
