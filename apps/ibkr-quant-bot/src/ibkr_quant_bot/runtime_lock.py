from __future__ import annotations

import fcntl
from pathlib import Path
from typing import TextIO


class RuntimeLockError(RuntimeError):
    pass


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
