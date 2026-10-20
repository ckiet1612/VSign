from __future__ import annotations

import hashlib
from pathlib import Path


def package_hash(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Package must be a directory, not a symlink")
    entries = sorted(root.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise ValueError("Package contains a symlink")
    files = [path for path in entries if path.is_file()]
    if not files:
        raise ValueError("Package is empty")
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            file_digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                file_digest.update(chunk)
        digest.update(file_digest.digest())
    return digest.hexdigest()
