from __future__ import annotations

import importlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


def locks():
    try:
        return importlib.import_module("contracts.model_lifecycle_lock")
    except ModuleNotFoundError:
        pytest.fail("Shared model lifecycle lock is not implemented")


@pytest.fixture(autouse=True)
def private_lock_storage(tmp_path, monkeypatch):
    import tempfile

    storage = tmp_path / "temp"
    storage.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(storage))
    monkeypatch.setenv("TMPDIR", str(storage))
    return storage


def child_lock(url, training=False, *, cwd=None):
    code = """
import sys
from contracts.model_lifecycle_lock import LifecycleBusy, lifecycle_lock
try:
    with lifecycle_lock(sys.argv[1], training=sys.argv[2] == 'true'):
        print('acquired')
except LifecycleBusy:
    print('busy')
"""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-c", code, url, str(training).lower()],
                            cwd=cwd, env={**os.environ, "PYTHONPATH": str(root)},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_training_allows_other_training_but_denies_registration(tmp_path):
    helper = locks()
    url = f"sqlite:///{tmp_path / 'missing/platform.db'}"
    with helper.lifecycle_lock(url, training=True):
        with helper.lifecycle_lock(url, training=True):
            assert child_lock(url, training=True) == "acquired"
            assert child_lock(url) == "busy"
        with pytest.raises(helper.LifecycleBusy, match="busy"):
            with helper.lifecycle_lock(url):
                pytest.fail("Registration must not overlap training")
    assert child_lock(url) == "acquired"
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("training", [False, True])
def test_exclusive_registration_denies_all_contenders(tmp_path, training):
    helper = locks()
    url = f"sqlite:///{tmp_path / 'platform.db'}"
    with helper.lifecycle_lock(url):
        assert child_lock(url, training=training) == "busy"
    assert child_lock(url, training=training) == "acquired"


@pytest.mark.parametrize("alias", ["relative", "dotdot", "symlink"])
def test_sqlite_canonical_path_is_same_lock_across_processes(tmp_path, monkeypatch, alias):
    helper = locks()
    monkeypatch.chdir(tmp_path)
    database = tmp_path / "data/platform.db"
    url = f"sqlite:///{database}"
    if alias == "relative":
        other = "sqlite:///./data/platform.db"
    elif alias == "dotdot":
        (tmp_path / "other").mkdir()
        other = "sqlite:///other/../data/platform.db"
    else:
        database.parent.mkdir()
        (tmp_path / "alias").symlink_to(database.parent, target_is_directory=True)
        other = "sqlite:///alias/platform.db"
    with helper.lifecycle_lock(url, training=True):
        assert child_lock(other, cwd=tmp_path) == "busy"
    assert not database.exists()


@pytest.mark.parametrize("training", [False, True])
def test_lock_released_when_body_raises_and_preserves_original_error(tmp_path, training):
    helper = locks()
    url = f"sqlite:///{tmp_path / 'platform.db'}"
    with pytest.raises(ValueError, match="original body error"):
        with helper.lifecycle_lock(url, training=training):
            raise ValueError("original body error")
    assert child_lock(url) == "acquired"


def test_independent_databases_do_not_block_each_other(tmp_path):
    helper = locks()
    with helper.lifecycle_lock(f"sqlite:///{tmp_path / 'first.db'}"):
        assert child_lock(f"sqlite:///{tmp_path / 'second.db'}") == "acquired"


def test_nonfile_urls_key_full_string_without_exposing_credentials(private_lock_storage):
    helper = locks()
    url = "postgresql://user:top-secret-password@host/database"
    other = "postgresql://user:different-secret@host/database"
    with helper.lifecycle_lock(url, training=True):
        assert child_lock(url) == "busy"
        assert child_lock(other) == "acquired"
        with pytest.raises(helper.LifecycleBusy) as caught:
            with helper.lifecycle_lock(url):
                pytest.fail("Lock should be busy")
    assert "secret" not in str(caught.value)
    assert url not in str(caught.value)
    assert isinstance(caught.value, RuntimeError)
    assert not any("secret" in str(path) for path in private_lock_storage.rglob("*"))


def test_lock_storage_is_private_and_lock_inode_stays_stable(tmp_path, private_lock_storage):
    helper = locks()
    url = f"sqlite:///{tmp_path / 'platform.db'}"
    with helper.lifecycle_lock(url):
        directories = list(private_lock_storage.iterdir())
        assert len(directories) == 1
        directory = directories[0]
        assert directory.stat().st_mode & 0o777 == 0o700
        files = list(directory.iterdir())
        assert len(files) == 1
        lock = files[0]
        metadata = lock.stat()
        assert stat.S_ISREG(metadata.st_mode)
        assert metadata.st_mode & 0o777 == 0o600
        assert metadata.st_uid == os.getuid()
    assert lock.exists()
    with helper.lifecycle_lock(url):
        assert lock.stat().st_ino == metadata.st_ino


@pytest.mark.parametrize("unsafe", ["symlink-file", "hardlink-file", "public-file", "symlink-dir", "public-dir"])
def test_unsafe_lock_storage_fails_closed(tmp_path, private_lock_storage, unsafe):
    helper = locks()
    url = f"sqlite:///{tmp_path / 'platform.db'}"
    with helper.lifecycle_lock(url):
        directory = next(private_lock_storage.iterdir())
        lock = next(directory.iterdir())
    target = tmp_path / "do-not-touch"
    target.write_bytes(b"protected")
    if unsafe == "symlink-file":
        lock.unlink()
        lock.symlink_to(target)
    elif unsafe == "hardlink-file":
        lock.unlink()
        os.link(target, lock)
    elif unsafe == "public-file":
        lock.chmod(0o666)
    elif unsafe == "public-dir":
        directory.chmod(0o777)
    else:
        lock.unlink()
        directory.rmdir()
        directory.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError) as caught:
        with helper.lifecycle_lock(url):
            pytest.fail("Unsafe storage must not be used")
    assert str(tmp_path) not in str(caught.value)
    assert target.read_bytes() == b"protected"


def test_non_posix_fails_closed_without_creating_storage(monkeypatch, private_lock_storage):
    helper = locks()
    monkeypatch.setattr(helper.os, "name", "nt")
    with pytest.raises(RuntimeError):
        with helper.lifecycle_lock("postgresql://user:secret@host/db"):
            pytest.fail("Non-POSIX must not silently skip locking")
    assert list(private_lock_storage.iterdir()) == []


def test_missing_fcntl_fails_closed(monkeypatch, private_lock_storage):
    helper = locks()
    monkeypatch.setattr(helper, "fcntl", None)
    with pytest.raises(RuntimeError):
        with helper.lifecycle_lock("postgresql://user:secret@host/db"):
            pytest.fail("Missing fcntl must not silently skip locking")
    assert list(private_lock_storage.iterdir()) == []


def test_low_level_lock_error_is_sanitized_and_descriptor_closed(tmp_path, monkeypatch):
    helper = locks()
    url = f"sqlite:///{tmp_path / 'platform.db'}"
    flock = helper.fcntl.flock
    opened = []

    def denied(fd, operation):
        import errno

        opened.append(fd)
        raise OSError(errno.EIO, "secret-database-password")

    monkeypatch.setattr(helper.fcntl, "flock", denied)
    with pytest.raises(RuntimeError) as caught:
        with helper.lifecycle_lock(url):
            pytest.fail("Lock failure must abort lifecycle operations")
    assert "secret-database-password" not in str(caught.value)
    assert caught.value.__suppress_context__
    with pytest.raises(OSError):
        os.fstat(opened[0])
    monkeypatch.setattr(helper.fcntl, "flock", flock)
    assert child_lock(url) == "acquired"
