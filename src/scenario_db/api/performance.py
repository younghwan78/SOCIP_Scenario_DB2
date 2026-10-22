"""Opt-in, request-scoped timings without payloads, identifiers or SQL text."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import logging
from threading import Lock
from time import perf_counter
from typing import Any, Callable

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.types import ASGIApp, Message, Receive, Scope, Send


logger = logging.getLogger(__name__)
_SQL_KEY = "_scenario_db_performance_query"
_HOLD_KEY = "_scenario_db_performance_checkout"
_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}


@dataclass
class _RequestMetrics:
    """The mutable owner is shared by context copies in FastAPI's worker threads."""

    sql_count: int = 0
    sql_seconds: float = 0.0
    hold_seconds: float = 0.0
    checkouts: dict[int, float] = field(default_factory=dict)
    closed: bool = False
    lock: Any = field(default_factory=Lock)

    def query_started(self) -> None:
        with self.lock:
            if not self.closed:
                self.sql_count += 1

    def query_finished(self, started: float) -> None:
        with self.lock:
            if not self.closed:
                self.sql_seconds += max(0.0, perf_counter() - started)

    def checked_out(self, key: int) -> None:
        with self.lock:
            if not self.closed:
                self.checkouts[key] = perf_counter()

    def checked_in(self, key: int) -> None:
        with self.lock:
            started = self.checkouts.pop(key, None)
            if started is not None and not self.closed:
                self.hold_seconds += max(0.0, perf_counter() - started)

    def finish(self) -> dict[str, int | float]:
        with self.lock:
            now = perf_counter()
            hold = self.hold_seconds + sum(max(0.0, now - start) for start in self.checkouts.values())
            self.closed = True
            return {"sql_count": self.sql_count, "sql_ms": round(self.sql_seconds * 1000, 3),
                    "db_connection_hold_ms": round(hold * 1000, 3),
                    "db_connections_open_at_finish": len(self.checkouts)}


_current: ContextVar[_RequestMetrics | None] = ContextVar("scenario_db_performance_request", default=None)


def install_sql_observers(engine: Engine) -> Callable[[], None]:
    """Attach only to the application's engine; return its lifespan cleanup.

    Checkout observes acquisition *after* any pool wait. Hold time is measured
    until checkin/invalidation, attributed to the checkout owner across threads.
    No statement, parameter, connection identity or exception text is retained.
    """
    def before_cursor(_conn, _cursor, _statement, _parameters, context, _many):
        owner = _current.get()
        if owner is not None:
            owner.query_started()
            setattr(context, _SQL_KEY, (owner, perf_counter()))

    def finish_query(context):
        timing = getattr(context, _SQL_KEY, None)
        if timing is not None:
            delattr(context, _SQL_KEY)
            owner, started = timing
            owner.query_finished(started)

    def after_cursor(_conn, _cursor, _statement, _parameters, context, _many):
        finish_query(context)

    def query_error(context):
        finish_query(context.execution_context)

    def checkout(_connection, record, _proxy):
        owner = _current.get()
        if owner is not None:
            record.info[_HOLD_KEY] = owner
            owner.checked_out(id(record))

    def checkin(_connection, record):
        owner = record.info.pop(_HOLD_KEY, None)
        if owner is not None:
            owner.checked_in(id(record))

    def invalidate(connection, record, _exception):
        checkin(connection, record)

    hooks: list[tuple[Any, str, Callable[..., Any]]] = [(engine, "before_cursor_execute", before_cursor),
             (engine, "after_cursor_execute", after_cursor), (engine, "handle_error", query_error),
             (engine.pool, "checkout", checkout), (engine.pool, "checkin", checkin),
             (engine.pool, "invalidate", invalidate)]
    for target, name, listener in hooks:
        event.listen(target, name, listener)

    def remove() -> None:
        for target, name, listener in hooks:
            event.remove(target, name, listener)

    return remove


class PerformanceMiddleware:
    """Observe the entire HTTP ASGI call, including streaming and dependency cleanup."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self._lock = Lock()
        self._active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = perf_counter()
        owner = _RequestMetrics()
        token = _current.set(owner)
        with self._lock:
            self._active += 1
            active_at_start = self._active
        status = 0
        complete = False
        failed = False

        async def observe_send(message: Message) -> None:
            nonlocal status, complete
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True

        try:
            await self.app(scope, receive, observe_send)
        except BaseException:
            failed = True
            raise
        finally:
            _current.reset(token)
            with self._lock:
                self._active -= 1
                active = self._active
            metrics = owner.finish()
            route = getattr(scope.get("route"), "path", None) or "__unmatched__"
            method = scope.get("method", "")
            payload = {"event": "request_performance", "route": route,
                       "method": method if method in _METHODS else "OTHER",
                       "status": status or (500 if failed else 0),
                       "wall_ms": round((perf_counter() - started) * 1000, 3),
                       "active_requests_at_start": active_at_start, "active_requests": active,
                       "response_complete": complete, "failed": failed, **metrics}
            # A logging handler failure must not replace an application response/exception.
            try:
                logger.info(json.dumps(payload, separators=(",", ":")))
            except Exception:
                pass
