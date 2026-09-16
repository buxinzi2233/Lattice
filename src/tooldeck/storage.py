"""Small, crash-safe file primitives shared by persistence adapters."""

from __future__ import annotations

import errno
import os
import time
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class FileLockTimeout(TimeoutError):
    """A persisted resource stayed locked beyond its deadline."""


class FileLockCancelled(OSError):
    """Shutdown cancelled an outstanding lock request."""


@contextmanager
def exclusive_file_lock(path: Path, timeout: float, cancelled: Event | None) -> Iterator[None]:
    """Acquire a bounded, cancellable cross-process lock."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            if cancelled is not None and cancelled.is_set():
                raise FileLockCancelled(f"锁等待已取消：{lock_path}")
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise FileLockTimeout(f"操作锁等待超过 {timeout:g} 秒：{lock_path}") from exc
                time.sleep(0.025)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _temporary_payload(destination: Path, payload: bytes) -> Iterator[str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        yield temporary
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_write_bytes(path: Path, payload: bytes) -> Path:
    """Replace a file with its complete, durable payload."""
    with _temporary_payload(path, payload) as temporary:
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    return path


def atomic_create_text(path: Path, payload: str) -> Path:
    """Create a complete file without replacing any concurrent writer."""
    with _temporary_payload(path, payload.encode("utf-8")) as temporary:
        os.link(temporary, path)
        _fsync_directory(path.parent)
    return path


def atomic_write_text(path: Path, payload: str) -> Path:
    return atomic_write_bytes(path, payload.encode("utf-8"))


def read_bytes(path: Path) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


def restore_bytes(path: Path, payload: bytes | None) -> None:
    """Restore a captured file, or remove it when the capture was absent."""

    destination = Path(path)
    if payload is None:
        try:
            destination.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(destination.parent)
        return
    atomic_write_bytes(destination, payload)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
