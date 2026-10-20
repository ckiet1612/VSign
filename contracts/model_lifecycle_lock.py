"""Local POSIX coordination between candidate training and registration."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:
    fcntl = None


class LifecycleBusy(RuntimeError):
    """Another local lifecycle operation holds an incompatible lock."""


def _lock_key(database_url: str) -> str:
    prefix = "sqlite:///"
    if database_url.startswith(prefix) and database_url != "sqlite:///:memory:":
        filename = database_url[len(prefix):]
        if not filename or any(char in filename for char in ("?", "#", "\x00")):
            raise ValueError
        identity = "sqlite-file:" + str(Path(filename).resolve())
    else:
        identity = "database-url:" + database_url
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _open_lock_file(key: str) -> int:
    uid = os.geteuid()
    directory = Path(tempfile.gettempdir()).resolve() / f"vsign-model-lifecycle-{uid}"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    directory_fd = os.open(directory, flags)
    try:
        metadata = os.fstat(directory_fd)
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != uid
                or stat.S_IMODE(metadata.st_mode) != 0o700):
            raise ValueError
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(key + ".lock", flags, 0o600, dir_fd=directory_fd)
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != uid
                    or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_nlink != 1):
                raise ValueError
        except BaseException:
            os.close(fd)
            raise
        return fd
    finally:
        os.close(directory_fd)


@contextmanager
def lifecycle_lock(database_url: str, *, training: bool = False) -> Iterator[None]:
    """Hold SH for an entire training run, or EX for registration through commit.

    All callers must share the same user/temp storage on one local host. Lock
    files remain in place after release so contenders always lock the same inode.
    No database connection, database file, or database parent is created here.
    """
    if os.name != "posix" or fcntl is None or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeError("Model lifecycle locking is unavailable")
    try:
        fd = _open_lock_file(_lock_key(database_url))
    except (OSError, ValueError, TypeError, RuntimeError):
        raise RuntimeError("Model lifecycle locking is unavailable") from None
    try:
        try:
            fcntl.flock(fd, (fcntl.LOCK_SH if training else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise LifecycleBusy("Model lifecycle is busy; try again later") from None
            raise RuntimeError("Model lifecycle locking is unavailable") from None
        yield
    finally:
        os.close(fd)
