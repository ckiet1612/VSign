from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from ml.scripts.setup_sales30_seated_v3_kaggle import relative_path, reject_symlinks, sha256_file
from tmp.train_sales30_seated import prepare_manifest, write_immutable


BUNDLE_CODE_FILES = (
    "ml/__init__.py", "ml/sales30_data.py", "ml/visignlanguage.py",
    "ml/scripts/__init__.py", "ml/scripts/train_visignlanguage.py",
    "ml/scripts/setup_sales30_seated_v3_kaggle.py",
    "tmp/train_sales30_seated.py", "contracts/v1/sales30.labels.json",
    "ml/configs/sales30_mvitv2_s.yaml",
    "ml/notebooks/sales30_seated_v3.ipynb",
)
INPUT_MANIFESTS = (
    "ml/data/raw/sales30/manifest.csv",
    "ml/data/collected/sales30_seated/manifest.csv",
    "ml/data/collected/sales30_seated_remaining21/manifest.csv",
)


def write_bundle(
    output: Path, files: Mapping[str, Path], metadata: dict[str, Any],
    *, expected_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    reject_symlinks(output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite ZIP: {output}")
    if not files:
        raise ValueError("No bundle files")
    for name, source in files.items():
        relative_path(name)
        reject_symlinks(source)
        if name == "bundle_inventory.json" or not source.is_file():
            raise ValueError(f"Invalid bundle file: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{output.name}-", dir=output.parent)
    os.close(descriptor)
    temporary = Path(name)
    inventory = {**metadata, "files": []}
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            for index, (relative, source) in enumerate(sorted(files.items()), start=1):
                digest = hashlib.sha256()
                size = 0
                info = zipfile.ZipInfo(f"VSign/{relative}", date_time=(2026, 10, 6, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED if source.suffix in {".mp4", ".pt"} else zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with source.open("rb") as handle, archive.open(info, "w", force_zip64=True) as target:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                        target.write(chunk)
                checksum = digest.hexdigest()
                if expected_hashes and relative in expected_hashes and checksum != expected_hashes[relative]:
                    raise ValueError(f"Source changed during packaging: {source}")
                inventory["files"].append({"path": relative, "bytes": size, "sha256": checksum})
                if index % 500 == 0:
                    print(json.dumps({"event": "packaging", "files": index, "total": len(files)}), flush=True)
            archive.writestr("VSign/bundle_inventory.json", json.dumps(inventory, ensure_ascii=False, indent=2) + "\n")
        # An exclusive hard link publishes the completed archive without replacing an existing file.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return inventory


def prepare_bundle(root: Path, output_dir: Path) -> dict[str, Any]:
    reject_symlinks(output_dir)
    archive = output_dir / "vsign_sales30_seated_v3.zip"
    if archive.exists():
        raise FileExistsError(f"Bundle already exists; select a new --output-dir: {archive}")
    manifest, labels, rows = prepare_manifest(root, "seated-v3")
    audit_path = manifest.parent / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    baseline_root = root / "ml/artifacts/sales30_seated_v2"
    baseline = baseline_root / "training/best.pt"
    source_artifact = json.loads((baseline_root / "artifact_manifest.json").read_text(encoding="utf-8"))
    declared = {entry["path"]: entry for entry in source_artifact["files"]}
    expected_baseline = declared["training/best.pt"]
    reject_symlinks(baseline)
    if sha256_file(baseline) != expected_baseline["sha256"] or baseline.stat().st_size != expected_baseline["bytes"]:
        raise ValueError("Baseline seated-v2 best.pt does not match its artifact manifest")
    baseline_labels = baseline_root / "labels.json"
    if (json.loads(baseline_labels.read_text(encoding="utf-8")) != labels
            or sha256_file(baseline_labels) != declared["labels.json"]["sha256"]):
        raise ValueError("Baseline labels do not match canonical Sales30 labels")
    initialization = {
        "model_version": source_artifact["model_version"], "architecture": "mvit_v2_s",
        "checkpoint": "baseline/training/best.pt", "sha256": expected_baseline["sha256"],
        "fine_tune_epoch": source_artifact["fine_tune_epoch"],
        "load_weights_only": True, "restore_optimizer": False, "restore_scheduler": False,
    }
    initialization_path = manifest.parent / "baseline_initialization.json"
    write_immutable(initialization_path, (json.dumps(initialization, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    files = {relative: root / relative for relative in BUNDLE_CODE_FILES + INPUT_MANIFESTS}
    for name in ("download_index.json", "source_audit.json", "readiness.json", "manifest_audit.json"):
        relative = f"ml/data/raw/sales30/{name}"
        files[relative] = root / relative
    files.update({str(row["path"]): root / str(row["path"]) for row in rows})
    files[manifest.relative_to(root).as_posix()] = manifest
    files[audit_path.relative_to(root).as_posix()] = audit_path
    files["baseline/training/best.pt"] = baseline
    files["baseline/initialization.json"] = initialization_path
    files["README_KAGGLE.md"] = root / "ml/notebooks/SALES30_SEATED_V3_KAGGLE.md"
    expected_hashes = {str(row["path"]): str(row["sha256"]) for row in rows}
    expected_hashes["baseline/training/best.pt"] = expected_baseline["sha256"]
    expected_hashes.update({entry["path"]: entry["sha256"] for entry in audit["input_manifests"]})
    inventory = write_bundle(archive, files, {
        "dataset_version": "seated-v3", "development_only": True,
        "data_audit": audit, "initialization": initialization,
    }, expected_hashes=expected_hashes)
    notebook = root / "ml/notebooks/sales30_seated_v3.ipynb"
    write_immutable(output_dir / notebook.name, notebook.read_bytes())
    guide = files["README_KAGGLE.md"]
    write_immutable(output_dir / "README_KAGGLE.md", guide.read_bytes())
    report = {
        "event": "bundle_ready", "dataset_version": "seated-v3", "development_only": True,
        "archive": archive.name, "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256_file(archive), "bundled_files": len(inventory["files"]),
        "row_count": audit["row_count"], "splits": audit["splits"], "sources": audit["sources"],
        "missing_seated_words": audit["missing_seated_words"], "initialization": initialization,
        "training_executed": False, "runtime_changed": False,
    }
    write_immutable(output_dir / "bundle_report.json", (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    write_immutable(output_dir / "SHA256SUMS.txt", f"{report['archive_sha256']}  {archive.name}\n".encode("ascii"))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the private seated-v3 Kaggle dataset; never train")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output_dir or root / "artifacts/sales30_seated_v3_kaggle"
    prepare_bundle(root, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
