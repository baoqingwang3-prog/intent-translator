"""Crash-safe JSON updates with a small cross-platform process lock."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


def _acquire(handle, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for the local data lock")
            time.sleep(0.05)


def _release(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _replace_with_retry(source: str, target: Path, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


@contextmanager
def exclusive_file_lock(path: Path, *, timeout: float = 10.0) -> Iterator[None]:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f".{target.name}.lock")
    with lock_path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        _acquire(handle, timeout)
        try:
            yield
        finally:
            _release(handle)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _replace_with_retry(temporary, target)
        if os.name != "nt":
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked_json_document(
    path: Path,
    default_factory: Callable[[], dict[str, Any]],
    *,
    timeout: float = 10.0,
) -> Iterator[dict[str, Any]]:
    target = Path(path).expanduser()
    with exclusive_file_lock(target, timeout=timeout):
        payload = json.loads(target.read_text(encoding="utf-8")) if target.exists() else default_factory()
        if not isinstance(payload, dict):
            raise ValueError("local JSON document must contain an object")
        yield payload
        atomic_write_json(target, payload)
