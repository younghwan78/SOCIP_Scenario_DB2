"""Small durable sweep jobs with actor isolation, cooperative cancellation and checkpoints.

Only pure case calculation runs in workers. Each DB write uses a fresh short session.
An expired worker lease can be resumed explicitly; a new token fences the old worker.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from math import prod
from threading import Event, Lock, Thread
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import sessionmaker

from scenario_db.api.resource_limits import admission_slot, enforce_request_size, enforce_timeline_frame_limit
from scenario_db.api.schemas.scenario_whatif import WhatIfScope, WhatIfSweepRequest
from scenario_db.api.services import scenario_whatif as engine
from scenario_db.api.services.whatif_sweep import run_sweep
from scenario_db.api.services.compute_session import REQUEST_OWNED
from scenario_db.config import get_settings
from scenario_db.db.models.whatif import WhatIfJob
from scenario_db.exceptions import ConflictError, NotFoundError

_pool = None
_lock = Lock()
_shutdown = Event()
_log = logging.getLogger(__name__)
_LEASE = timedelta(seconds=120)


def _now():
    return datetime.now(timezone.utc)


def _expired(row):
    stamp = row.heartbeat_at or row.updated_at or row.created_at
    return row.status in ("queued", "running") and stamp is not None and _now() - stamp > _LEASE


def _record(row):
    stale = _expired(row)
    return {"id": row.id, "status": "interrupted" if stale else row.status,
            "completed_cases": row.completed_cases, "total_cases": row.total_cases,
            "cancel_requested": row.cancel_requested, "result": row.result, "error": row.error,
            "resumable": stale or row.status in ("cancelled", "interrupted", "failed"),
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def _owned(db, job_id, subject, *, lock=False):
    query = db.query(WhatIfJob).filter_by(id=job_id, created_by=subject)
    if lock:
        query = query.with_for_update()
    row = query.one_or_none()
    if row is None:
        raise NotFoundError("What-if job not found")
    return row


def _launch(factory, job_id, token):
    global _pool
    with _lock:
        if _pool is None:
            _shutdown.clear()
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whatif")
        _pool.submit(_run, factory, job_id, token)


def _queue_lock(db):
    db.execute(text("SELECT pg_advisory_xact_lock(728312, 32)"))


def _check_capacity(db):
    active = db.query(func.count(WhatIfJob.id)).filter(WhatIfJob.status.in_(["queued", "running"]),
        WhatIfJob.updated_at >= _now() - _LEASE).scalar()
    if active >= 16:
        raise HTTPException(status_code=429, detail="What-if job queue is full", headers={"Retry-After": "5"})


def submit(db, request, subject):
    scope = WhatIfScope(**request.model_dump(include={"project_ref", "scenario_id", "variant_id"}))
    base = engine._baseline(db, scope, request)
    # Pin model identity before putting work in the queue. Resume checks it again.
    # Preserve unset fields: active-profile precedence distinguishes an omitted
    # config field from an explicitly supplied default after deserialization.
    payload = request.model_dump(mode="json", exclude_unset=True)
    payload["expected_analysis_hash"] = base["analysis_hash"]
    payload["basis_ref"] = base.get("lineage", {}).get("basis_ref")
    _queue_lock(db)
    job_id = "whatif-job-" + engine._digest({"actor": subject, "request": payload})
    existing = db.get(WhatIfJob, job_id)
    if existing is not None:
        result = _record(existing)
        db.commit()
        return result
    _check_capacity(db)
    token = uuid4().hex
    row = WhatIfJob(id=job_id, project_ref=request.project_ref, created_by=subject,
        status="queued", request=payload, completed_cases=0, total_cases=prod(len(a.values) for a in request.axes),
        cancel_requested=False, worker_token=token, heartbeat_at=_now(), updated_at=_now())
    db.add(row)
    db.commit()
    db.refresh(row)
    result = _record(row)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    _launch(factory, row.id, token)
    return result


def get(db, job_id, subject):
    return _record(_owned(db, job_id, subject))


def cancel(db, job_id, subject):
    row = _owned(db, job_id, subject, lock=True)
    if row.status in ("queued", "running"):
        row.cancel_requested = True
        if row.status == "queued" or _expired(row):
            row.status = "cancelled"
            row.worker_token = None
        row.updated_at = _now()
        db.commit()
    return _record(row)


def resume(db, job_id, subject):
    _queue_lock(db)
    row = _owned(db, job_id, subject, lock=True)
    if not _record(row)["resumable"]:
        raise ConflictError("Only cancelled, interrupted or failed jobs can be resumed")
    _check_capacity(db)
    request = WhatIfSweepRequest.model_validate(row.request)
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(max(request.options.frames, request.options.timeline_frames + 4,
        request.config.timeline_frame_count), settings.simulation_max_timeline_frames)
    token = uuid4().hex
    row.status, row.worker_token, row.cancel_requested, row.error = "queued", token, False, None
    row.heartbeat_at = row.updated_at = _now()
    db.commit()
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    result = _record(row)
    _launch(factory, row.id, token)
    return result


def _run(factory, job_id, token):
    stopped = Event()
    def heartbeat():
        while not stopped.wait(10):
            try:
                with factory() as db:
                    updated = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token, status="running").update(
                        {"heartbeat_at": _now(), "updated_at": _now()})
                    db.commit()
                    if not updated:
                        return
            except Exception:
                _log.exception("What-if job heartbeat failed")
                return
    thread = None
    try:
        with factory() as db:
            row = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token, status="queued").with_for_update().one_or_none()
            if row is None:
                return
            request = WhatIfSweepRequest.model_validate(row.request)
            previous = row.result
            row.status, row.heartbeat_at, row.updated_at = "running", _now(), _now()
            db.commit()
        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        def checkpoint(result):
            with factory() as db:
                current = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token).with_for_update().one_or_none()
                if current is None:
                    return False
                current.result = dict(result)
                current.completed_cases = result["completed_cases"]
                current.heartbeat_at = current.updated_at = _now()
                keep_going = not current.cancel_requested and not _shutdown.is_set()
                db.commit()
                return keep_going
        settings = get_settings()
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
            candidate_slot = admission_slot("simulation", settings.simulation_max_concurrent_runs)
            try:
                candidate_slot.__enter__()
                slot = candidate_slot
            except HTTPException as exc:
                if exc.status_code != 429:
                    raise
                _shutdown.wait(0.25)
        try:
            with factory() as db:
                db.info[REQUEST_OWNED] = True
                result = run_sweep(db, request, checkpoint=checkpoint, previous=previous)
        finally:
            slot.__exit__(None, None, None)
        with factory() as db:
            row = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token).with_for_update().one_or_none()
            if row is not None:
                row.result, row.completed_cases = result, result["completed_cases"]
                row.status = ("interrupted" if _shutdown.is_set() else "cancelled") if result["cancelled"] else "completed"
                row.updated_at = _now()
                db.commit()
    except Exception as exc:
        _log.exception("What-if job calculation failed")
        with factory() as db:
            row = db.query(WhatIfJob).filter_by(id=job_id, worker_token=token).with_for_update().one_or_none()
            if row is not None:
                row.status = "failed"
                # User-facing domain errors are useful; never return DB/driver details.
                row.error = str(exc)[:1000] if isinstance(exc, (ValueError, ConflictError)) else "계산 실패 — 입력과 서버 상태를 확인하고 다시 시도하세요."
                row.updated_at = _now()
                db.commit()
    finally:
        stopped.set()
        if thread:
            thread.join(timeout=2)


def shutdown_whatif_jobs():
    global _pool
    with _lock:
        pool, _pool = _pool, None
        _shutdown.set()
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=True)
