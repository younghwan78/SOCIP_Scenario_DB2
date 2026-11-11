"""Exploration runs as durable jobs: progress, cancellation, resume, and leaving the page.

A job row lives in the What-if job table (``explore-job-*`` ids, same lease / heartbeat /
token fencing). The worker runs :func:`arch_exploration.run_exploration` with
``parallel=True`` and a progress callback; the run itself is stored exactly as the
synchronous POST stores it, and the job result points at it. Resume restarts the run:
with parallel variants a run takes seconds, so partial results are not checkpointed.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from scenario_db.api.resource_limits import admission_slot, enforce_request_size, enforce_timeline_frame_limit
from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest
from scenario_db.api.services import arch_exploration as svc
from scenario_db.api.services.compute_session import REQUEST_OWNED
from scenario_db.api.services.whatif_jobs import _check_capacity, _expired, _now, _queue_lock
from scenario_db.config import get_settings
from scenario_db.db.models.whatif import WhatIfJob
from scenario_db.exceptions import ConflictError, NotFoundError, UnprocessableError

PREFIX = "explore-job-"
_pool: ThreadPoolExecutor | None = None
_lock = Lock()
_shutdown = Event()
_log = logging.getLogger(__name__)


def validate(request: ArchExplorationRunRequest) -> None:
    """The synchronous POST's request checks, before anything is queued."""
    settings = get_settings()
    if request.apply_options:
        raise UnprocessableError("apply_options is reserved for IQ-reviewed lever registration")
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.spec.timing.frames, settings.simulation_max_timeline_frames)


def _total_variants(db, request: ArchExplorationRunRequest) -> int:
    scenarios = svc._scenarios(db, request)
    total = sum(len(svc._variant_ids(db, s.id, request)) for s in scenarios)
    if not total:
        raise NotFoundError("exploration scope has no variants")
    if total > request.max_variants:
        raise UnprocessableError(f"exploration scope has {total} variants > max_variants {request.max_variants}")
    return total


def record(row: WhatIfJob) -> dict:
    stale = _expired(row)
    result = row.result or {}
    return {"id": row.id, "status": "interrupted" if stale else row.status,
            "completed_variants": row.completed_cases, "total_variants": row.total_cases,
            "current_variant": result.get("current_variant"), "failed_variants": result.get("failed_variants", 0),
            "run_id": result.get("run_id"), "summary": result.get("summary"),
            "cancel_requested": row.cancel_requested, "error": row.error,
            "resumable": stale or row.status in ("cancelled", "interrupted", "failed"),
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def _owned(db, job_id: str, subject: str, *, lock: bool = False) -> WhatIfJob:
    if not job_id.startswith(PREFIX):
        raise NotFoundError("Exploration job not found")
    query = db.query(WhatIfJob).filter_by(id=job_id, created_by=subject)
    if lock:
        query = query.with_for_update()
    row = query.one_or_none()
    if row is None:
        raise NotFoundError("Exploration job not found")
    return row


def _launch(factory, job_id: str, token: str) -> None:
    global _pool
    with _lock:
        if _pool is None:
            _shutdown.clear()
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="explore-job")
        _pool.submit(_run, factory, job_id, token)


def submit(db, request: ArchExplorationRunRequest, subject: str) -> dict:
    validate(request)
    total = _total_variants(db, request)
    scenarios = svc._scenarios(db, request)
    _queue_lock(db)
    _check_capacity(db)
    token = uuid4().hex
    # exclude_unset: run_exploration distinguishes an omitted spec field from an explicit default
    row = WhatIfJob(id=PREFIX + uuid4().hex, project_ref=request.project_ref or scenarios[0].project_ref,
                    created_by=subject, status="queued",
                    request={"kind": "exploration", "request": request.model_dump(mode="json", exclude_unset=True)},
                    completed_cases=0, total_cases=total, cancel_requested=False, worker_token=token,
                    heartbeat_at=_now(), updated_at=_now())
    db.add(row)
    db.commit()
    db.refresh(row)
    result = record(row)
    _launch(sessionmaker(bind=db.get_bind(), expire_on_commit=False), row.id, token)
    return result


def get(db, job_id: str, subject: str) -> dict:
    return record(_owned(db, job_id, subject))


def cancel(db, job_id: str, subject: str) -> dict:
    row = _owned(db, job_id, subject, lock=True)
    if row.status in ("queued", "running"):
        row.cancel_requested = True
        if row.status == "queued" or _expired(row):
            row.status = "cancelled"
            row.worker_token = None
        row.updated_at = _now()
        db.commit()
    return record(row)


def resume(db, job_id: str, subject: str) -> dict:
    _queue_lock(db)
    row = _owned(db, job_id, subject, lock=True)
    if not record(row)["resumable"]:
        raise ConflictError("Only cancelled, interrupted or failed jobs can be resumed")
    _check_capacity(db)
    validate(ArchExplorationRunRequest.model_validate(row.request["request"]))
    token = uuid4().hex
    row.status, row.worker_token, row.cancel_requested, row.error = "queued", token, False, None
    row.completed_cases, row.result = 0, None
    row.heartbeat_at = row.updated_at = _now()
    db.commit()
    result = record(row)
    _launch(sessionmaker(bind=db.get_bind(), expire_on_commit=False), row.id, token)
    return result


def _finish(factory, job_id: str, token: str, **fields) -> None:
    with factory() as db:
        row = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token).with_for_update().one_or_none()
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = _now()
        db.commit()


def _run(factory, job_id: str, token: str) -> None:
    stopped = Event()

    def heartbeat() -> None:
        while not stopped.wait(10):
            try:
                with factory() as db:
                    updated = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token, status="running").update(
                        {"heartbeat_at": _now(), "updated_at": _now()})
                    db.commit()
                    if not updated:
                        return
            except Exception:
                _log.exception("Exploration job heartbeat failed")
                return
    thread = None
    try:
        with factory() as db:
            row = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token, status="queued").with_for_update().one_or_none()
            if row is None:
                return
            request = ArchExplorationRunRequest.model_validate(row.request["request"])
            subject = row.created_by
            row.status, row.heartbeat_at, row.updated_at = "running", _now(), _now()
            db.commit()
        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        settings = get_settings()
        last_write = [float("-inf")]

        def progress(done: int, total: int, variant_id: str | None) -> bool:
            # always checks cancellation; rewrites the progress row at most every checkpoint interval
            with factory() as db:
                current = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token).with_for_update().one_or_none()
                if current is None:
                    return False
                if done == total or monotonic() - last_write[0] >= settings.whatif_job_checkpoint_seconds:
                    current.completed_cases = done
                    current.result = {"current_variant": variant_id}
                    last_write[0] = monotonic()
                current.heartbeat_at = current.updated_at = _now()
                keep_going = not current.cancel_requested and not _shutdown.is_set()
                db.commit()
                return keep_going
        slot = None
        while slot is None:
            with factory() as db:
                current = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token).with_for_update().one_or_none()
                if current is None:
                    return
                if current.cancel_requested or _shutdown.is_set():
                    current.status = "interrupted" if _shutdown.is_set() else "cancelled"
                    current.updated_at = _now()
                    db.commit()
                    return
            # the same admission as the synchronous POST
            candidate = admission_slot("simulation", settings.simulation_max_concurrent_runs)
            try:
                candidate.__enter__()
                slot = candidate
            except HTTPException as exc:
                if exc.status_code != 429:
                    raise
                _shutdown.wait(0.25)
        try:
            with factory() as db:
                db.info[REQUEST_OWNED] = True
                run = svc.run_exploration(db, request, subject, release_connection=True,
                                          progress=progress, parallel=True)
        except svc.ExplorationCancelled:
            _finish(factory, job_id, token, status="interrupted" if _shutdown.is_set() else "cancelled")
            return
        finally:
            slot.__exit__(None, None, None)
        summary = run.get("summary") or {}
        _finish(factory, job_id, token, status="completed", completed_cases=summary.get("variants", 0)
                + summary.get("errors", 0), result={"run_id": run["id"], "summary": summary,
                                                     "failed_variants": summary.get("errors", 0)})
    except Exception as exc:
        _log.exception("Exploration job failed")
        # user-facing domain errors are useful; never return DB / driver details
        message = (str(exc)[:1000] if isinstance(exc, (ValueError, ConflictError, NotFoundError, UnprocessableError))
                   else "탐색 실패 — 입력과 서버 상태를 확인하고 다시 시도하세요.")
        _finish(factory, job_id, token, status="failed", error=message)
    finally:
        stopped.set()
        if thread:
            thread.join(timeout=2)


def shutdown_exploration_jobs() -> None:
    global _pool
    with _lock:
        pool, _pool = _pool, None
        _shutdown.set()
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=True)
