from __future__ import annotations

import json
import csv
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from ml.sales30_data import (
    MANIFEST_FIELDS,
    SALES30_DATASET_REF,
    SALES30_LICENSE,
    KaggleFile,
    Sales30SourceConfig,
    SourceAudit,
    SourceInventory,
    _default_kaggle_downloader,
    audit_sales30_manifest,
    audit_source,
    build_sales30_manifest,
    download_inventory,
    list_kaggle_files,
    load_source_config,
    normalize_label,
)


def source_config(tmp_path: Path, *, minimum_total_clips: int = 1) -> Sales30SourceConfig:
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            {
                "dataset_ref": SALES30_DATASET_REF,
                "version": 8,
                "license": SALES30_LICENSE,
                "canonical_prefix": "processed/processed/frame_splited/",
                "minimum_total_clips": minimum_total_clips,
            }
        ),
        encoding="utf-8",
    )
    return load_source_config(path)


def test_source_audit_requires_exact_nfc_label_coverage(tmp_path: Path) -> None:
    config = source_config(tmp_path)
    inventory = SourceInventory(
        dataset_ref=config.dataset_ref,
        version=8,
        license_name=SALES30_LICENSE,
        files=(
            KaggleFile(
                "processed/processed/frame_splited/train/Ca\u0300 phe\u0302/1.mp4",
                10,
            ),
            KaggleFile(
                "processed/processed/frame_splited/test/Cà phê/2.mp4",
                10,
            ),
        ),
    )

    audit = audit_source(config, ["Cà phê", "Laptop"], inventory)

    assert normalize_label(" Ca\u0300 phe ") == "Cà phe"
    assert audit.coverage["Cà phê"] == {"train": 1, "test": 1}
    assert audit.blockers == ("Thiếu label nguồn: Laptop",)


def test_source_audit_rejects_version_license_and_noncanonical_files(
    tmp_path: Path,
) -> None:
    config = source_config(tmp_path)
    inventory = SourceInventory(
        dataset_ref=config.dataset_ref,
        version=7,
        license_name="Unknown",
        files=(
            KaggleFile("raw/raw/train/Cà phê/1.mp4", 10),
            KaggleFile(
                "processed_augmented/processed_augmented/frame_splited/train/Cà phê/2.mp4",
                10,
            ),
        ),
    )

    audit = audit_source(config, ["Cà phê"], inventory)

    assert "Source version drift: expected 8, got 7" in audit.blockers
    assert "Source license drift" in audit.blockers
    assert "Thiếu label nguồn: Cà phê" in audit.blockers
    assert audit.selected_files == ()


def test_source_audit_enforces_minimum_total_clips(tmp_path: Path) -> None:
    config = source_config(tmp_path, minimum_total_clips=3)
    inventory = SourceInventory(
        dataset_ref=config.dataset_ref,
        version=8,
        license_name=config.license_name,
        files=(
            KaggleFile("processed/processed/frame_splited/train/Có/1.mp4", 10),
            KaggleFile("processed/processed/frame_splited/test/Có/2.mp4", 10),
        ),
    )

    audit = audit_source(config, ["Có"], inventory)

    assert audit.blockers == ("Label Có chỉ có 2 clip, cần tối thiểu 3",)


def test_kaggle_catalog_follows_pagination_and_filters_video_tree(
    tmp_path: Path,
) -> None:
    config = source_config(tmp_path)
    requested_urls: list[str] = []

    def fetch_json(url: str) -> dict[str, object]:
        requested_urls.append(url)
        parsed = urlparse(url)
        if "/view/" in parsed.path:
            return {
                "ref": config.dataset_ref,
                "currentVersionNumber": 8,
                "licenseName": config.license_name,
            }
        token = parse_qs(parsed.query).get("pageToken", [None])[0]
        if token is None:
            return {
                "datasetFiles": [
                    {
                        "name": "processed/processed/frame_splited/train/Có/1.mp4",
                        "totalBytes": 11,
                    },
                    {"name": "README.md", "totalBytes": 2},
                ],
                "nextPageToken": "page-two",
            }
        assert token == "page-two"
        return {
            "datasetFiles": [
                {
                    "name": "processed/processed/frame_splited/test/Có/2.mp4",
                    "totalBytes": 12,
                }
            ],
            "nextPageToken": "",
        }

    inventory = list_kaggle_files(config, fetch_json=fetch_json)

    assert [item.name for item in inventory.files] == [
        "processed/processed/frame_splited/test/Có/2.mp4",
        "processed/processed/frame_splited/train/Có/1.mp4",
    ]
    assert inventory.version == 8
    assert len(requested_urls) == 3
    assert "pageToken=page-two" in requested_urls[-1]


def test_kaggle_catalog_stops_after_canonical_prefix(tmp_path: Path) -> None:
    config = source_config(tmp_path)
    list_requests = 0

    def fetch_json(url: str) -> dict[str, object]:
        nonlocal list_requests
        parsed = urlparse(url)
        if "/view/" in parsed.path:
            return {
                "ref": config.dataset_ref,
                "currentVersionNumber": 8,
                "licenseName": config.license_name,
            }
        list_requests += 1
        if list_requests == 1:
            return {
                "datasetFiles": [
                    {
                        "name": "processed/processed/frame_splited/test/Có/1.mp4",
                        "totalBytes": 10,
                    }
                ],
                "nextPageToken": "page-two",
            }
        if list_requests == 2:
            return {
                "datasetFiles": [
                    {
                        "name": "processed/processed/frame_splited/train/Có/2.mp4",
                        "totalBytes": 10,
                    },
                    {
                        "name": "processed/processed/keypoints_splited/train/Có/2.npy",
                        "totalBytes": 10,
                    },
                ],
                "nextPageToken": "must-not-be-requested",
            }
        raise AssertionError("Client continued beyond canonical video prefix")

    inventory = list_kaggle_files(config, fetch_json=fetch_json)

    assert len(inventory.files) == 2
    assert list_requests == 2


def test_source_config_rejects_unpinned_or_unsafe_values(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "dataset_ref": "dataset-without-owner",
                "version": 0,
                "license": "",
                "canonical_prefix": "../raw/",
                "minimum_total_clips": 0,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="dataset_ref"):
        load_source_config(path)


def test_download_inventory_groups_directories_and_writes_checksums(
    tmp_path: Path,
) -> None:
    config = source_config(tmp_path)
    inventory = SourceInventory(
        dataset_ref=config.dataset_ref,
        version=8,
        license_name=config.license_name,
        files=(
            KaggleFile("processed/processed/frame_splited/train/Có/1.mp4", 5),
            KaggleFile("processed/processed/frame_splited/train/Có/2.mp4", 4),
            KaggleFile("processed/processed/frame_splited/test/Có/3.mp4", 5),
        ),
    )
    audit = audit_source(config, ["Có"], inventory)
    requested: list[str] = []

    def downloader(dataset_handle: str, remote_dir: str, output_dir: Path) -> Path:
        assert dataset_handle == f"{SALES30_DATASET_REF}/versions/8"
        requested.append(remote_dir)
        target = output_dir / Path(remote_dir).name
        target.mkdir(parents=True)
        if "/train/" in remote_dir:
            (target / "1.mp4").write_bytes(b"train")
            (target / "2.mp4").write_bytes(b"more")
        else:
            (target / "3.mp4").write_bytes(b"tests")
        return target

    result = download_inventory(audit, tmp_path / "output", downloader=downloader)

    assert requested == [
        "processed/processed/frame_splited/test/Có",
        "processed/processed/frame_splited/train/Có",
    ]
    assert result.downloaded == 3
    assert result.reused == 0
    assert (tmp_path / "output/media/train/Có/1.mp4").read_bytes() == b"train"
    index = json.loads((tmp_path / "output/download_index.json").read_text())
    assert len(index["files"]) == 3
    assert all(len(item["sha256"]) == 64 for item in index["files"])


def test_kagglehub_0313_downloader_uses_cache_without_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached = tmp_path / "cached.mp4"
    cached.write_bytes(b"video")
    calls: list[tuple[str, str]] = []

    def dataset_download(handle: str, *, path: str) -> str:
        calls.append((handle, path))
        return str(cached)

    monkeypatch.setitem(
        sys.modules,
        "kagglehub",
        SimpleNamespace(dataset_download=dataset_download),
    )

    result = _default_kaggle_downloader(
        f"{SALES30_DATASET_REF}/versions/8",
        "processed/processed/frame_splited/train/Có/1.mp4",
        tmp_path / "unused",
    )

    assert result == cached
    assert calls == [
        (
            f"{SALES30_DATASET_REF}/versions/8",
            "processed/processed/frame_splited/train/Có/1.mp4",
        )
    ]


def test_kagglehub_download_error_identifies_remote_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dataset_download(_handle: str, *, path: str) -> str:
        raise RuntimeError("404")

    monkeypatch.setitem(
        sys.modules,
        "kagglehub",
        SimpleNamespace(dataset_download=dataset_download),
    )

    with pytest.raises(RuntimeError, match="train/Có/1.mp4"):
        _default_kaggle_downloader(
            f"{SALES30_DATASET_REF}/versions/8",
            "processed/processed/frame_splited/train/Có/1.mp4",
            tmp_path / "unused",
        )


def test_kagglehub_downloader_retries_transient_404_but_not_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached = tmp_path / "cached.mp4"
    cached.write_bytes(b"video")

    class DownloadError(RuntimeError):
        def __init__(self, status_code: int) -> None:
            self.response = SimpleNamespace(status_code=status_code)
            super().__init__(str(status_code))

    transient_calls = 0

    def transient_download(_handle: str, *, path: str) -> str:
        nonlocal transient_calls
        transient_calls += 1
        if transient_calls == 1:
            raise DownloadError(404)
        return str(cached)

    monkeypatch.setitem(
        sys.modules,
        "kagglehub",
        SimpleNamespace(dataset_download=transient_download),
    )
    monkeypatch.setattr(
        "ml.sales30_data.time",
        SimpleNamespace(sleep=lambda _: None),
        raising=False,
    )

    result = _default_kaggle_downloader(
        f"{SALES30_DATASET_REF}/versions/8",
        "processed/processed/frame_splited/train/Có/1.mp4",
        tmp_path / "unused",
    )
    assert result == cached
    assert transient_calls == 2

    forbidden_calls = 0

    def forbidden_download(_handle: str, *, path: str) -> str:
        nonlocal forbidden_calls
        forbidden_calls += 1
        raise DownloadError(403)

    monkeypatch.setitem(
        sys.modules,
        "kagglehub",
        SimpleNamespace(dataset_download=forbidden_download),
    )
    with pytest.raises(RuntimeError, match="train/Có/1.mp4"):
        _default_kaggle_downloader(
            f"{SALES30_DATASET_REF}/versions/8",
            "processed/processed/frame_splited/train/Có/1.mp4",
            tmp_path / "unused",
        )
    assert forbidden_calls == 1


def test_download_inventory_reuses_indexed_files_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    config = source_config(tmp_path)
    inventory = SourceInventory(
        dataset_ref=config.dataset_ref,
        version=8,
        license_name=config.license_name,
        files=(
            KaggleFile("processed/processed/frame_splited/train/Có/1.mp4", 5),
            KaggleFile("processed/processed/frame_splited/test/Có/2.mp4", 5),
        ),
    )
    audit = audit_source(config, ["Có"], inventory)

    def downloader(_handle: str, remote_dir: str, output_dir: Path) -> Path:
        target = output_dir / Path(remote_dir).name
        target.mkdir(parents=True)
        content = b"train" if "/train/" in remote_dir else b"tests"
        name = "1.mp4" if "/train/" in remote_dir else "2.mp4"
        (target / name).write_bytes(content)
        return target

    first = download_inventory(audit, tmp_path / "output", downloader=downloader)
    assert first.downloaded == 2

    second = download_inventory(
        audit,
        tmp_path / "output",
        downloader=lambda *_: pytest.fail("Không được tải lại file hợp lệ"),
    )
    assert second.downloaded == 0
    assert second.reused == 2

    (tmp_path / "output/media/train/Có/1.mp4").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="checksum"):
        download_inventory(
            audit,
            tmp_path / "output",
            downloader=lambda *_: pytest.fail("Không được ghi đè file bị sửa"),
        )


def test_download_inventory_rejects_spoofed_source_identity(tmp_path: Path) -> None:
    audit = SourceAudit(
        dataset_ref="attacker/other-dataset",
        version=1,
        license_name="Unknown",
        coverage={"Có": {"train": 1, "test": 1}},
        selected_files=(
            KaggleFile("processed/processed/frame_splited/train/Có/1.mp4", 1),
            KaggleFile("processed/processed/frame_splited/test/Có/2.mp4", 1),
        ),
        blockers=(),
        warnings=(),
    )

    with pytest.raises(ValueError, match="dataset_ref"):
        download_inventory(
            audit,
            tmp_path / "output",
            downloader=lambda *_: pytest.fail("Không được tải source giả"),
        )


def test_download_inventory_resumes_after_interrupted_file_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = source_config(tmp_path)
    inventory = SourceInventory(
        dataset_ref=config.dataset_ref,
        version=config.version,
        license_name=config.license_name,
        files=(
            KaggleFile("processed/processed/frame_splited/train/Có/1.mp4", 5),
            KaggleFile("processed/processed/frame_splited/train/Có/2.mp4", 4),
            KaggleFile("processed/processed/frame_splited/test/Có/3.mp4", 5),
        ),
    )
    audit = audit_source(config, ["Có"], inventory)

    def downloader(_handle: str, remote_dir: str, output_dir: Path) -> Path:
        target = output_dir / Path(remote_dir).name
        target.mkdir(parents=True)
        if "/train/" in remote_dir:
            (target / "1.mp4").write_bytes(b"train")
            (target / "2.mp4").write_bytes(b"more")
        else:
            (target / "3.mp4").write_bytes(b"tests")
        return target

    real_replace = Path.replace
    replacements = 0

    def interrupt_second_media_replace(path: Path, target: Path) -> Path:
        nonlocal replacements
        if target.suffix == ".mp4":
            replacements += 1
            if replacements == 2:
                raise OSError("simulated interruption")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupt_second_media_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        download_inventory(audit, tmp_path / "output", downloader=downloader)
    monkeypatch.setattr(Path, "replace", real_replace)

    resumed = download_inventory(audit, tmp_path / "output", downloader=downloader)

    assert resumed.reused >= 1
    assert len(json.loads((tmp_path / "output/download_index.json").read_text())["files"]) == 3


def test_download_inventory_rejects_unsafe_remote_path(tmp_path: Path) -> None:
    config = source_config(tmp_path)
    audit = audit_source(
        config,
        ["Có"],
        SourceInventory(
            dataset_ref=config.dataset_ref,
            version=8,
            license_name=config.license_name,
            files=(KaggleFile("../Có/escape.mp4", 1),),
        ),
    )
    unsafe = audit.__class__(
        dataset_ref=audit.dataset_ref,
        version=audit.version,
        license_name=audit.license_name,
        coverage={"Có": {"train": 1, "test": 0}},
        selected_files=(KaggleFile("../Có/escape.mp4", 1),),
        blockers=(),
        warnings=audit.warnings,
    )

    with pytest.raises(ValueError, match="không an toàn"):
        download_inventory(
            unsafe,
            tmp_path / "output",
            downloader=lambda *_: tmp_path,
        )


def test_manifest_is_deterministic_and_preserves_source_test(tmp_path: Path) -> None:
    output_root = tmp_path / "sales30"
    media_root = output_root / "media"
    files = []
    index_files = []
    for source_split, count in (("train", 20), ("test", 3)):
        for number in range(count):
            name = f"{number:02d}.mp4"
            relative = Path(source_split) / "Có" / name
            local = media_root / relative
            local.parent.mkdir(parents=True, exist_ok=True)
            content = f"{source_split}-{number}".encode()
            local.write_bytes(content)
            remote = (
                "processed/processed/frame_splited/"
                f"{source_split}/Có/{name}"
            )
            files.append(KaggleFile(remote, len(content)))
            index_files.append(
                {
                    "remote_path": remote,
                    "local_path": relative.as_posix(),
                    "total_bytes": len(content),
                    "sha256": __import__("hashlib").sha256(content).hexdigest(),
                }
            )
    (output_root / "download_index.json").write_text(
        json.dumps(
            {
                "dataset_ref": SALES30_DATASET_REF,
                "version": 8,
                "license": SALES30_LICENSE,
                "files": index_files,
            }
        ),
        encoding="utf-8",
    )
    inventory = SourceInventory(
        dataset_ref=SALES30_DATASET_REF,
        version=8,
        license_name=SALES30_LICENSE,
        files=tuple(files),
    )

    first_rows, first_readiness = build_sales30_manifest(
        output_root, ["Có"], inventory, seed=7, minimum_total_clips=15
    )
    second_rows, second_readiness = build_sales30_manifest(
        output_root, ["Có"], inventory, seed=7, minimum_total_clips=15
    )

    assert first_rows == second_rows
    assert first_readiness == second_readiness
    assert first_readiness.blockers == ()
    assert first_readiness.counts["Có"] == {
        "train": 18,
        "validation": 2,
        "test": 3,
    }
    assert all(
        row.split == "test" for row in first_rows if row.source_split == "test"
    )
    assert list(first_rows[0].to_dict()) == list(MANIFEST_FIELDS)


def test_manifest_rejects_download_index_source_drift(tmp_path: Path) -> None:
    output_root = tmp_path / "sales30"
    output_root.mkdir()
    (output_root / "download_index.json").write_text(
        json.dumps(
            {
                "dataset_ref": "attacker/other-dataset",
                "version": 7,
                "license": "Unknown",
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    inventory = SourceInventory(
        dataset_ref=SALES30_DATASET_REF,
        version=8,
        license_name=SALES30_LICENSE,
        files=(),
    )

    with pytest.raises(ValueError, match="Download index source drift"):
        build_sales30_manifest(output_root, ["Có"], inventory, seed=7)


def test_manifest_audit_rejects_duplicate_checksum_across_splits(
    tmp_path: Path,
) -> None:
    media = tmp_path / "media"
    (media / "train/Có").mkdir(parents=True)
    (media / "test/Có").mkdir(parents=True)
    (media / "train/Có/a.mp4").write_bytes(b"same")
    (media / "test/Có/b.mp4").write_bytes(b"same")
    digest = __import__("hashlib").sha256(b"same").hexdigest()
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=MANIFEST_FIELDS,
        )
        writer.writeheader()
        writer.writerows(
            (
                {
                    "path": "train/Có/a.mp4",
                    "label_id": "0",
                    "label": "Có",
                    "split": "train",
                    "source_split": "train",
                    "remote_path": "processed/processed/frame_splited/train/Có/a.mp4",
                    "sha256": digest,
                    "source_id": SALES30_DATASET_REF,
                    "source_revision": "8",
                    "source_label": "Có",
                    "source_record_id": "processed/processed/frame_splited/train/Có/a.mp4",
                    "license": SALES30_LICENSE,
                    "signer_id": "unknown",
                    "group_id": "unknown",
                    "view": "unknown",
                    "take": "unknown",
                    "split_strength": "development-only",
                },
                {
                    "path": "test/Có/b.mp4",
                    "label_id": "0",
                    "label": "Có",
                    "split": "test",
                    "source_split": "test",
                    "remote_path": "processed/processed/frame_splited/test/Có/b.mp4",
                    "sha256": digest,
                    "source_id": SALES30_DATASET_REF,
                    "source_revision": "8",
                    "source_label": "Có",
                    "source_record_id": "processed/processed/frame_splited/test/Có/b.mp4",
                    "license": SALES30_LICENSE,
                    "signer_id": "unknown",
                    "group_id": "unknown",
                    "view": "unknown",
                    "take": "unknown",
                    "split_strength": "development-only",
                },
            )
        )

    audit = audit_sales30_manifest(manifest, media, ["Có"])

    assert any("checksum xuất hiện ở nhiều split" in error for error in audit.errors)


def test_manifest_audit_derives_source_test_from_remote_path(tmp_path: Path) -> None:
    media = tmp_path / "media"
    local = media / "train/Có/forged.mp4"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"video")
    digest = __import__("hashlib").sha256(b"video").hexdigest()
    remote = "processed/processed/frame_splited/test/Có/forged.mp4"
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "path": "train/Có/forged.mp4",
                "label_id": "0",
                "label": "Có",
                "split": "train",
                "source_id": SALES30_DATASET_REF,
                "source_revision": "8",
                "source_label": "Có",
                "source_record_id": remote,
                "license": SALES30_LICENSE,
                "sha256": digest,
                "signer_id": "unknown",
                "group_id": "unknown",
                "view": "unknown",
                "take": "unknown",
                "source_split": "train",
                "remote_path": remote,
                "split_strength": "development-only",
            }
        )

    audit = audit_sales30_manifest(
        manifest, media, ["Có"], minimum_total_clips=1
    )

    assert any("remote_path thuộc source test" in error for error in audit.errors)
