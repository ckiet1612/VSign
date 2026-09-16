from __future__ import annotations

from pathlib import Path

from ml.scripts.audit_manifest import audit_manifest
from ml.scripts.validate_gloss_map import validate_gloss_map


FIXTURES = Path(__file__).parent / "fixtures"


def test_valid_gloss_map() -> None:
    assert validate_gloss_map(FIXTURES / "gloss_map_valid.csv") == []


def test_gloss_map_detects_duplicate_and_missing_values(tmp_path: Path) -> None:
    path = tmp_path / "gloss.csv"
    path.write_text(
        "source_class_id,gloss_vi,display_text,region,source\n"
        "a,g,Từ A,x,official\n"
        "a,g,,x,\n",
        encoding="utf-8",
    )
    errors = validate_gloss_map(path)
    assert any("trùng" in error for error in errors)
    assert any("display_text" in error for error in errors)
    assert any("source bị trống" in error for error in errors)


def test_manifest_detects_signer_leakage_and_missing_files() -> None:
    audit = audit_manifest(FIXTURES / "manifest_leakage.csv")
    assert audit.row_count == 2
    assert any("Signer leakage" in error for error in audit.errors)
    assert sum("không tìm thấy file" in error for error in audit.errors) == 2


def test_manifest_accepts_signer_independent_splits(tmp_path: Path) -> None:
    (tmp_path / "a.synthetic").touch()
    (tmp_path / "b.synthetic").touch()
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,source_class_id,signer_id,view,take,split\n"
        "a.synthetic,class-a,signer-a,front,1,train\n"
        "b.synthetic,class-a,signer-b,front,1,test\n",
        encoding="utf-8",
    )
    audit = audit_manifest(manifest)
    assert audit.errors == []
    assert audit.distribution[("class-a", "signer-a", "front")] == 1
