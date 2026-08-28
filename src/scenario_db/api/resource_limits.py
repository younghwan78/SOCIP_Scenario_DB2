from __future__ import annotations

from contextlib import contextmanager
from threading import BoundedSemaphore, Lock
from typing import Iterator

from fastapi import HTTPException
from pydantic import BaseModel

_registry_lock = Lock()
_semaphores: dict[tuple[str, int], BoundedSemaphore] = {}


@contextmanager
def admission_slot(operation: str, limit: int) -> Iterator[None]:
    """Acquire a non-blocking per-process execution slot."""

    key = (operation, limit)
    with _registry_lock:
        semaphore = _semaphores.setdefault(key, BoundedSemaphore(limit))
    if not semaphore.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail=f"{operation} concurrency limit reached",
            headers={"Retry-After": "1"},
        )
    try:
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
