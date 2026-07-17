from __future__ import annotations

import fcntl
import os
from pathlib import Path
from threading import Timer
from typing import TextIO


class RuntimeLockError(RuntimeError):
    pass


RUNTIME_TIMEOUT_EXIT_CODE = 124


class RuntimeLockDeadline:
    """Hard process deadline tied to a held runtime lock."""

    def __init__(
        self, lock_handle: TextIO, timeout_seconds: float, timer: Timer
    ) -> None:
        self.lock_handle = lock_handle
        self.timeout_seconds = timeout_seconds
        self._timer = timer

    def cancel(self) -> None:
        self._timer.cancel()


def _release_runtime_lock_and_exit(
    lock_handle: TextIO, timeout_seconds: float
) -> None:
    """Release the lock before hard-exiting a strategy process that is stuck."""
    try:
        if not lock_handle.closed:
            lock_handle.close()
    finally:
        message = (
            "intraday momentum timed out after "
            f"{timeout_seconds:g}s; runtime lock released\n"
        )
        try:
            os.write(2, message.encode("utf-8", errors="replace"))
        finally:
            os._exit(RUNTIME_TIMEOUT_EXIT_CODE)


def arm_runtime_lock_deadline(
    lock_handle: TextIO, timeout_seconds: float
) -> RuntimeLockDeadline:
    """Terminate the process and release its lock after a hard deadline."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    timer = Timer(
        timeout_seconds,
        _release_runtime_lock_and_exit,
        args=(lock_handle, timeout_seconds),
    )
    timer.daemon = True
    timer.start()
    return RuntimeLockDeadline(lock_handle, timeout_seconds, timer)


def acquire_runtime_lock(lock_path: str | Path) -> TextIO:
    """Hold one non-blocking advisory lock for the returned handle's lifetime."""
    lock_path = Path(lock_path).expanduser()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeLockError(
            f"another process already owns {lock_path}"
        ) from exc
    return handle


def acquire_cache_writer_lock(cache_path: str | Path) -> TextIO:
    """Hold one non-blocking writer lock for the lifetime of the returned file."""
    resolved = Path(cache_path).expanduser()
    return acquire_runtime_lock(resolved.with_name(f"{resolved.name}.lock"))
