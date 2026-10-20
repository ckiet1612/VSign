from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Sequence


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts or "\\" in value
            or "\x00" in value or path.as_posix() != value or value == "."):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return path


def reject_symlinks(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"Refusing symlink: {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_inventory(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("dataset_version") != "seated-v3":
        raise ValueError("Bundle must be seated-v3")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Bundle inventory has no files")
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Invalid inventory entry")
        name = entry.get("path")
        if not isinstance(name, str):
            raise ValueError("Inventory path must be a string")
        relative_path(name)
        digest = entry.get("sha256")
        size = entry.get("bytes")
        if (name in seen or name == "bundle_inventory.json" or not isinstance(size, int)
                or isinstance(size, bool) or size < 0 or not isinstance(digest, str)
                or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError(f"Invalid or duplicate inventory entry: {name}")
        seen.add(name)
    return payload


def verify_bundle(root: Path) -> dict[str, Any]:
    reject_symlinks(root)
    inventory_path = root / "bundle_inventory.json"
    reject_symlinks(inventory_path)
    inventory = validate_inventory(json.loads(inventory_path.read_text(encoding="utf-8")))
    for entry in inventory["files"]:
        path = root / entry["path"]
        reject_symlinks(path)
        if not path.is_file() or path.stat().st_size != entry["bytes"]:
            raise ValueError(f"Missing file or bytes mismatch: {path}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"SHA256 mismatch: {path}")
    return inventory


def copy_verified(source: BinaryIO, destination: Path, entry: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with destination.open("xb") as handle:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            if size > entry["bytes"]:
                raise ValueError(f"bytes mismatch: {entry['path']}")
            digest.update(chunk)
            handle.write(chunk)
    if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
        raise ValueError(f"SHA256/bytes mismatch: {entry['path']}")


def install_bundle(source: Path, output_root: Path) -> Path:
    reject_symlinks(source)
    reject_symlinks(output_root)
    archive = None
    try:
        if source.is_dir():
            inventory = verify_bundle(source)
        else:
            archive = zipfile.ZipFile(source)
            inventory = validate_inventory(json.loads(archive.read("VSign/bundle_inventory.json")))
            declared = {f"VSign/{entry['path']}" for entry in inventory["files"]}
            declared.add("VSign/bundle_inventory.json")
            names = [entry.filename for entry in archive.infolist()]
            if len(names) != len(set(names)) or set(names) != declared:
                raise ValueError("ZIP contains duplicate, undeclared or unsafe members")
            for member in archive.infolist():
                relative_path(member.filename)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError(f"ZIP symlink: {member.filename}")
            for entry in inventory["files"]:
                if archive.getinfo(f"VSign/{entry['path']}").file_size != entry["bytes"]:
                    raise ValueError(f"ZIP bytes mismatch: {entry['path']}")

        if output_root.exists() and (not output_root.is_dir() or any(output_root.iterdir())):
            if not (output_root / "bundle_inventory.json").is_file():
                raise FileExistsError(f"Refusing to overwrite existing workspace: {output_root}")
            existing = verify_bundle(output_root)
            if existing != inventory:
                raise FileExistsError(f"Existing workspace belongs to another bundle: {output_root}")
            return output_root

        output_root.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
        try:
            for entry in inventory["files"]:
                if archive is not None:
                    with archive.open(f"VSign/{entry['path']}") as handle:
                        copy_verified(handle, staged / entry["path"], entry)
                else:
                    with (source / entry["path"]).open("rb") as handle:
                        copy_verified(handle, staged / entry["path"], entry)
            (staged / "bundle_inventory.json").write_text(
                json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            if output_root.exists():
                output_root.rmdir()
            staged.rename(output_root)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
        return output_root
    finally:
        if archive is not None:
            archive.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify/install the private seated-v3 Kaggle bundle")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("/kaggle/working/VSign-seated-v3"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_only:
        inventory = verify_bundle(args.output_root)
    else:
        if args.bundle is None:
            parser.error("--bundle is required unless --verify-only is used")
        install_bundle(args.bundle, args.output_root)
        inventory = verify_bundle(args.output_root)
    print(json.dumps({"event": "bundle_verified", "root": str(args.output_root),
                      "dataset_version": inventory["dataset_version"],
                      "verified_files": len(inventory["files"])}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
