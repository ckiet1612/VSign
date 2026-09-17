from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from ml.sales30_data import (
    KaggleFile,
    Sales30SourceConfig,
    SourceInventory,
    audit_source,
    list_kaggle_files,
    load_source_config,
    normalize_label,
)


def source_config(tmp_path: Path, *, minimum_total_clips: int = 1) -> Sales30SourceConfig:
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            {
                "dataset_ref": "owner/dataset",
                "version": 8,
                "license": "Attribution 4.0 International (CC BY 4.0)",
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
        license_name="Attribution 4.0 International (CC BY 4.0)",
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
