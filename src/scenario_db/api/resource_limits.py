from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import os
import sys
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import BinaryIO, Iterator

from fastapi import HTTPException
from pydantic import BaseModel

from scenario_db.config import get_settings

_registry_lock = Lock()
_semaphores: dict[tuple[str, int], BoundedSemaphore] = {}


def _at_capacity(operation: str) -> HTTPException:
    return HTTPException(status_code=429, detail=f"{operation} concurrency limit reached",
                         headers={"Retry-After": "1"})


def _lock_file(handle: BinaryIO) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            return False
        raise


@contextmanager
def _shared_slot(directory: str, operation: str, limit: int) -> Iterator[None]:
    """One-host slots, released by closing the descriptor (also on process exit).

    Slot files are never unlinked: deleting a locked inode could create a second
    independent budget. Every API process must use the same directory and limit.
    """
    root = Path(directory)
    namespace = hashlib.sha256(operation.encode("utf-8")).hexdigest()[:20]
    held: BinaryIO | None = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        for index in range(limit):
            handle = (root / f"{namespace}-{index}.lock").open("a+b")
            try:
                # Windows byte-range locks need a byte to lock. Concurrent initial
                # creators may append extra bytes; all lock exactly byte zero.
                if handle.seek(0, os.SEEK_END) == 0:
                    handle.write(b"\0")
                    handle.flush()
                if _lock_file(handle):
                    held = handle
                    break
            finally:
                if handle is not held:
                    handle.close()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="execution budget unavailable",
                            headers={"Retry-After": "1"}) from exc
    if held is None:
        raise _at_capacity(operation)
    try:
        yield
    finally:
        held.close()


@contextmanager
def _deployment_slot(operation: str) -> Iterator[None]:
    if operation not in {"simulation", "exploration"}:
        yield
        return
    settings = get_settings()
    limit = {"simulation": settings.simulation_global_max_concurrent_runs,
             "exploration": settings.exploration_global_max_concurrent_requests}.get(operation, 0)
    if limit and settings.execution_budget_dir:
        with _shared_slot(settings.execution_budget_dir, operation, limit):
            yield
    else:
        yield


@contextmanager
def admission_slot(operation: str, limit: int) -> Iterator[None]:
    """Acquire the original per-process slot and any explicitly configured host budget."""

    key = (operation, limit)
    with _registry_lock:
        semaphore = _semaphores.setdefault(key, BoundedSemaphore(limit))
    if not semaphore.acquire(blocking=False):
        raise _at_capacity(operation)
    try:
        with _deployment_slot(operation):
            yield
    finally:
        semaphore.release()


def enforce_request_size(request: BaseModel, max_bytes: int) -> None:
    size = len(request.model_dump_json().encode("utf-8"))
    if size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Exploration request exceeds {max_bytes} bytes",
        )


def enforce_timeline_frame_limit(frame_count: int, max_frames: int) -> None:
    if frame_count > max_frames:
        raise HTTPException(
            status_code=422,
            detail=f"timeline_frame_count exceeds configured maximum {max_frames}",
        )
