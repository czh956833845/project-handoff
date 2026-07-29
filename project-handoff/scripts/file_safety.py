#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, IO, Iterator


@dataclass(frozen=True)
class LockBackend:
    lock: Callable[[IO[str]], None]
    unlock: Callable[[IO[str]], None]
    would_block: tuple[type[BaseException], ...]


def _sync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write_bytes(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = destination.stat().st_mode & 0o7777 if destination.exists() else None
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            temporary_path.chmod(existing_mode)
        os.replace(temporary_path, destination)
        temporary_path = None
        _sync_directory(destination.parent)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_text(destination: Path, content: str) -> None:
    atomic_write_bytes(destination, content.encode("utf-8"))


def select_lock_backend(platform: str | None = None) -> LockBackend:
    platform_name = platform or sys.platform
    if platform_name == "win32":
        msvcrt = importlib.import_module("msvcrt")

        def lock(handle: IO[str]) -> None:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write("\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

        def unlock(handle: IO[str]) -> None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

        return LockBackend(lock=lock, unlock=unlock, would_block=(OSError,))

    fcntl = importlib.import_module("fcntl")

    def lock(handle: IO[str]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(handle: IO[str]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return LockBackend(lock=lock, unlock=unlock, would_block=(BlockingIOError,))


@contextmanager
def file_lock(
    lock_path: Path,
    timeout_seconds: float = 10.0,
    *,
    backend: LockBackend | None = None,
) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    selected_backend = backend or select_lock_backend()
    deadline = time.monotonic() + timeout_seconds
    with lock_path.open("a+") as handle:
        while True:
            try:
                selected_backend.lock(handle)
                break
            except selected_backend.would_block:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"timed out waiting for handoff lock after {timeout_seconds:g} seconds"
                    )
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        try:
            yield
        finally:
            selected_backend.unlock(handle)
