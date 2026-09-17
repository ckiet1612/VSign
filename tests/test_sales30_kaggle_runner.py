from __future__ import annotations

from pathlib import Path

import pytest

from ml.sales30_data import KaggleFile, SourceInventory
from ml.scripts.run_sales30_kaggle import (
    find_attached_vsl472_root,
    validate_attached_inventory,
)


def canonical_root(parent: Path) -> Path:
    root = parent / "processed/processed/frame_splited"
    (root / "train").mkdir(parents=True)
    (root / "test").mkdir(parents=True)
    return root


def test_find_attached_vsl472_root_accepts_one_canonical_tree(
    tmp_path: Path,
) -> None:
    expected = canonical_root(tmp_path / "attached-vsl472")

    assert find_attached_vsl472_root(tmp_path) == expected


def test_find_attached_vsl472_root_reports_missing_dataset(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="--dataset-root"):
        find_attached_vsl472_root(tmp_path)


def test_find_attached_vsl472_root_requires_override_for_multiple_matches(
    tmp_path: Path,
) -> None:
    canonical_root(tmp_path / "first")
    canonical_root(tmp_path / "second")

    with pytest.raises(ValueError, match="--dataset-root"):
        find_attached_vsl472_root(tmp_path)


def test_attached_inventory_must_match_audited_version8_catalog() -> None:
    expected = SourceInventory(
        dataset_ref="nguyenanfms/vsl-vietnamese-sign-language-v2",
        version=8,
        license_name="Attribution 4.0 International (CC BY 4.0)",
        files=(
            KaggleFile("processed/processed/frame_splited/train/Có/1.mp4", 10),
        ),
    )
    attached = SourceInventory(
        dataset_ref=expected.dataset_ref,
        version=8,
        license_name=expected.license_name,
        files=(
            KaggleFile("processed/processed/frame_splited/train/Có/1.mp4", 11),
        ),
    )

    with pytest.raises(ValueError, match="không khớp catalog version 8"):
        validate_attached_inventory(expected, attached)
