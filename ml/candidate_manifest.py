"""Candidate-only publication and read-only artifact guards; no runtime imports."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from contextlib import closing
from functools import wraps
from pathlib import Path
from typing import Sequence

from contracts.model_lifecycle_lock import lifecycle_lock


def candidate_training_guard(main):
    """Keep registration excluded from before preflight through the last write."""
    @wraps(main)
    def guarded(*args, **kwargs):
        database_url = os.environ.get("DATABASE_URL", "sqlite:///./data/vsign-platform.db")
        with lifecycle_lock(database_url, training=True):
            return main(*args, **kwargs)
    return guarded


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _plain_path(path: Path) -> Path:
    # Check the lexical path before resolving, including aliases before '..'.
    for part in (path, *path.parents):
        try:
            if stat.S_ISLNK(part.lstat().st_mode):
                raise ValueError("Paths must not use symlinks")
        except FileNotFoundError:
            continue
    return path.resolve()


def _configured_roots() -> list[Path]:
    """Explicit roots are absolute directories separated by os.pathsep."""
    configured = os.environ.get("MODEL_PROTECTED_ARTIFACT_ROOTS")
    if configured is None:
        return []
    try:
        roots = []
        for value in configured.split(os.pathsep):
            path = Path(value)
            if not value.strip() or not path.is_absolute() or "\x00" in value:
                raise ValueError
            root = _plain_path(path)
            if root.exists() and not root.is_dir():
                raise ValueError
            roots.append(root)
        return roots
    except (OSError, ValueError, RuntimeError):
        raise ValueError("Invalid MODEL_PROTECTED_ARTIFACT_ROOTS; use absolute roots without symlinks") from None


def _registered_roots(database: Path) -> list[Path]:
    try:
        database = _plain_path(database)
        try:
            mode = database.stat().st_mode
        except FileNotFoundError:
            return []
        if not stat.S_ISREG(mode):
            raise ValueError
        # mode=ro must not create a missing DB or bootstrap/migrate a legacy DB.
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            schema = connection.execute(
                "SELECT type FROM sqlite_master WHERE name = 'registered_models' COLLATE NOCASE",
            ).fetchone()
            if schema is None:
                return []
            if schema[0] != "table":
                raise ValueError
            rows = connection.execute(
                "SELECT artifact_path, labels_path, manifest_json, workspace_id FROM registered_models",
            )
            roots = []
            for artifact, labels, manifest, workspace in rows:
                if (not isinstance(workspace, str) or not workspace.strip()
                        or not isinstance(manifest, str) or not isinstance(json.loads(manifest), dict)):
                    raise ValueError
                for value in (artifact, labels):
                    if not isinstance(value, str) or not value.strip() or "\x00" in value:
                        raise ValueError
                    path = Path(value)
                    if not path.is_absolute():
                        raise ValueError
                    resolved = _plain_path(path)
                    if resolved.exists() and not (resolved.is_file() or (
                            value == artifact and resolved.suffix == ".mlpackage" and resolved.is_dir())):
                        raise ValueError
                    # A file and a .mlpackage both reserve their containing directory.
                    roots.append(resolved.parent)
            return roots
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error):
        raise ValueError("Cannot safely read registered model registry; refusing candidate output") from None


def protected_artifact_roots() -> list[Path]:
    """Read all workspaces, adding explicit roots; never mutate the registry.

    Non-file/unsupported database deployments must explicitly supply all immutable
    artifact roots via MODEL_PROTECTED_ARTIFACT_ROOTS (os.pathsep separated).
    """
    roots = _configured_roots()
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./data/vsign-platform.db")
    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        filename = database_url[len("sqlite:///"):]
        if not filename or any(char in filename for char in ("?", "#", "\x00")):
            raise ValueError("Invalid file database configuration for candidate output guard") from None
        roots.extend(_registered_roots(Path(filename).absolute()))
    elif not roots:
        raise ValueError("This database requires explicit MODEL_PROTECTED_ARTIFACT_ROOTS for safe training") from None
    return roots


def validate_candidate_output(output: Path) -> None:
    """Validate before creating, writing, or resuming anything beneath output."""
    try:
        resolved = _plain_path(output.absolute())
        if resolved.exists():
            if not resolved.is_dir():
                raise ValueError("Output must be a directory")

            def walk_error(error: OSError) -> None:
                raise error

            for directory, dirs, files in os.walk(resolved, onerror=walk_error, followlinks=False):
                for name in (*dirs, *files):
                    path = _plain_path(Path(directory) / name)
                    metadata = path.stat()
                    if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1:
                        raise ValueError("Output must not use hardlinks")
    except (OSError, RuntimeError):
        raise ValueError("Cannot safely inspect candidate output") from None
    for protected in protected_artifact_roots():
        if resolved == protected or resolved in protected.parents or protected in resolved.parents:
            raise ValueError("Output overlaps protected registered/configured model artifacts")


def publish_candidate_manifest(
    output: Path, *, labels: Sequence[str], model_version: str, source_run_id: str,
) -> Path:
    """Publish metadata only; there is intentionally no approval/deploy option."""
    validate_candidate_output(output)
    output = output.resolve()
    labels = list(labels)
    if (not labels or any(not isinstance(label, str) or not label for label in labels)
            or len(set(labels)) != len(labels) or not model_version or not source_run_id):
        raise ValueError("Candidate requires ordered unique labels, model version and source run")
    labels_path = output / "labels.json"
    if json.loads(labels_path.read_text(encoding="utf-8")) != labels:
        raise ValueError("Candidate labels file does not match checkpoint label order")
    manifest = {
        "model_version": model_version,
        "artifact_sha256": sha256_file(output / "best.pt"),
        "labels_sha256": hashlib.sha256(json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "labels_file_sha256": sha256_file(labels_path),
        "backend": "pytorch", "protocol_version": "1.0", "frame_count": 16, "frame_size": 224,
        "preprocessing_version": "rgb16-224-imagenet-v1",
        "confidence_threshold": .70, "margin_threshold": .15,
        "source_run_id": source_run_id, "status": "candidate", "development_only": True,
    }
    target = output / "model_manifest.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target
