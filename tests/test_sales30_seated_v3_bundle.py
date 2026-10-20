from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest


def modules():
    from ml.scripts import prepare_sales30_seated_v3 as packer
    from ml.scripts import setup_sales30_seated_v3_kaggle as setup
    return packer, setup


def bundle_fixture(tmp_path):
    packer, _ = modules()
    source = tmp_path / "source"
    source.mkdir()
    media = source / "sample.mp4"
    media.write_bytes(b"video-fixture")
    code = source / "script.py"
    code.write_bytes(b"print('fixture')\n")
    archive = tmp_path / "vsign_sales30_seated_v3.zip"
    packer.write_bundle(
        archive,
        {"ml/data/collected/clips/Chào/HA_01.mp4": media, "tmp/script.py": code},
        {"dataset_version": "seated-v3", "development_only": True},
    )
    return archive


def test_zip_contains_only_declared_files_and_hash_inventory(tmp_path):
    archive = bundle_fixture(tmp_path)
    with zipfile.ZipFile(archive) as handle:
        assert set(handle.namelist()) == {
            "VSign/ml/data/collected/clips/Chào/HA_01.mp4",
            "VSign/tmp/script.py", "VSign/bundle_inventory.json",
        }
        inventory = json.loads(handle.read("VSign/bundle_inventory.json"))
        files = {entry["path"]: entry for entry in inventory["files"]}
        assert files["ml/data/collected/clips/Chào/HA_01.mp4"]["sha256"] == hashlib.sha256(b"video-fixture").hexdigest()
        assert files["tmp/script.py"]["bytes"] == 17


def test_packaging_refuses_to_overwrite_existing_archive(tmp_path):
    archive = bundle_fixture(tmp_path)
    original = archive.read_bytes()
    packer, _ = modules()
    with pytest.raises(FileExistsError):
        packer.write_bundle(archive, {}, {"dataset_version": "seated-v3"})
    assert archive.read_bytes() == original


@pytest.mark.parametrize("name", ["../outside.py", "/outside.py", "a\\b.py"])
def test_bundle_writer_rejects_unsafe_member_paths(tmp_path, name):
    packer, _ = modules()
    source = tmp_path / "sample"
    source.write_bytes(b"sample")
    with pytest.raises(ValueError):
        packer.write_bundle(tmp_path / "bad.zip", {name: source}, {"dataset_version": "seated-v3"})
    assert not (tmp_path / "bad.zip").exists()


def test_install_zip_verifies_and_is_idempotent(tmp_path):
    archive = bundle_fixture(tmp_path)
    _, setup = modules()
    output = tmp_path / "working" / "VSign-seated-v3"
    setup.install_bundle(archive, output)
    assert (output / "ml/data/collected/clips/Chào/HA_01.mp4").read_bytes() == b"video-fixture"
    setup.install_bundle(archive, output)
    report = setup.verify_bundle(output)
    assert report["dataset_version"] == "seated-v3"
    assert len(report["files"]) == 2


def test_install_supports_kaggle_automatically_unpacked_directory(tmp_path):
    archive = bundle_fixture(tmp_path)
    _, setup = modules()
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(tmp_path / "attached")
    output = tmp_path / "working"
    setup.install_bundle(tmp_path / "attached/VSign", output)
    assert (output / "tmp/script.py").read_bytes() == b"print('fixture')\n"


def test_install_refuses_unrelated_existing_workspace(tmp_path):
    archive = bundle_fixture(tmp_path)
    _, setup = modules()
    output = tmp_path / "working"
    output.mkdir()
    (output / "my_file").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        setup.install_bundle(archive, output)
    assert (output / "my_file").read_bytes() == b"keep"


def test_verify_detects_tampered_clip_and_refuses_reinstall(tmp_path):
    archive = bundle_fixture(tmp_path)
    _, setup = modules()
    output = tmp_path / "working"
    setup.install_bundle(archive, output)
    media = output / "ml/data/collected/clips/Chào/HA_01.mp4"
    media.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA256|bytes"):
        setup.verify_bundle(output)
    with pytest.raises(ValueError):
        setup.install_bundle(archive, output)
    assert media.read_bytes() == b"tampered"


def test_zip_tampering_never_creates_final_output(tmp_path):
    archive = bundle_fixture(tmp_path)
    _, setup = modules()
    corrupted = tmp_path / "corrupted.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(corrupted, "w") as target:
        for name in source.namelist():
            target.writestr(name, b"tampered" if name.endswith(".mp4") else source.read(name))
    with pytest.raises(ValueError):
        setup.install_bundle(corrupted, tmp_path / "output")
    assert not (tmp_path / "output").exists()
    assert not list(tmp_path.glob(".output-*/"))


@pytest.mark.parametrize("bad_name", ["../outside", "VSign/../outside", "/outside", "VSign/extra.py"])
def test_install_rejects_undeclared_or_traversal_members(tmp_path, bad_name):
    archive = bundle_fixture(tmp_path)
    _, setup = modules()
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr(bad_name, b"bad")
    with pytest.raises(ValueError):
        setup.install_bundle(archive, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_install_rejects_archive_symlinks(tmp_path):
    archive = bundle_fixture(tmp_path)
    _, setup = modules()
    bad = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(bad, "w") as target:
        for name in source.namelist():
            info = zipfile.ZipInfo(name)
            if name.endswith("script.py"):
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            target.writestr(info, source.read(name))
    with pytest.raises(ValueError, match="symlink"):
        setup.install_bundle(bad, tmp_path / "output")


def test_verify_rejects_symlink_to_outside_even_with_matching_hash(tmp_path):
    archive = bundle_fixture(tmp_path)
    _, setup = modules()
    output = tmp_path / "working"
    setup.install_bundle(archive, output)
    code = output / "tmp/script.py"
    outside = tmp_path / "outside.py"
    outside.write_bytes(code.read_bytes())
    code.unlink()
    code.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        setup.verify_bundle(output)


@pytest.mark.parametrize("unpacked", [False, True])
def test_notebook_setup_cell_runs_on_zip_and_unpacked_kaggle_layout(tmp_path, monkeypatch, unpacked):
    packer, setup = modules()
    repository = Path(__file__).resolve().parents[1]
    source_root = tmp_path / "kaggle/input/datasets/owner/private-dataset/1"
    source_root.mkdir(parents=True)
    archive = source_root / "vsign_sales30_seated_v3.zip"
    helper_name = "ml/scripts/setup_sales30_seated_v3_kaggle.py"
    packer.write_bundle(archive, {helper_name: repository / helper_name},
                        {"dataset_version": "seated-v3", "development_only": True})
    if unpacked:
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(source_root)
        archive.unlink()
    monkeypatch.setenv("VSIGN_INPUT_ROOT", str(tmp_path / "kaggle/input"))
    monkeypatch.setenv("VSIGN_WORKING_ROOT", str(tmp_path / "kaggle/working"))
    notebook = json.loads((repository / "ml/notebooks/sales30_seated_v3.ipynb").read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), "notebook", "exec")
    setup_cell = next(cell for cell in notebook["cells"] if cell["id"] == "setup")
    namespace = {}
    exec(compile("".join(setup_cell["source"]), "notebook-setup", "exec"), namespace)
    expected_root = tmp_path / "kaggle/working/VSign-seated-v3"
    assert namespace["ROOT"] == expected_root
    assert setup.verify_bundle(expected_root)["files"][0]["path"] == helper_name


def test_packaging_checks_expected_hash_during_streaming(tmp_path):
    packer, _ = modules()
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"tampered-since-manifest")
    with pytest.raises(ValueError, match="changed"):
        packer.write_bundle(tmp_path / "output.zip", {"clip.mp4": source},
                            {"dataset_version": "seated-v3"},
                            expected_hashes={"clip.mp4": "a" * 64})
    assert not (tmp_path / "output.zip").exists()
    assert not list(tmp_path.glob(".output.zip-*"))
