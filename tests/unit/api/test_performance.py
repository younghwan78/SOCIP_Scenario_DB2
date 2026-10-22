"""Opt-in HTTP/SQL observation preserves responses, contexts and application errors."""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import QueuePool

from scenario_db.api import app as api_app
from scenario_db.api import performance as perf
from scenario_db.config import Settings


@pytest.fixture
def sql_engine():
    # Unit-level event plumbing only: no application schema or SQLite runtime substitute.
    engine = create_engine("sqlite://", poolclass=QueuePool, connect_args={"check_same_thread": False})
    remove = perf.install_sql_observers(engine)
    try:
        yield engine
    finally:
        remove()
        engine.dispose()


def records(caplog):
    return [json.loads(row.message) for row in caplog.records if row.name == perf.__name__]


def scope(method="GET"):
    return {"type": "http", "method": method, "path": "/private-value", "query_string": b"token=secret",
            "headers": [(b"authorization", b"secret")], "route": SimpleNamespace(path="/items/{item}")}


async def receive():
    return {"type": "http.request", "body": b"private-body"}


async def send(_message):
    pass


def test_disabled_by_default_has_no_middleware_or_sql_hooks(monkeypatch, caplog):
    settings = Settings(database_url="sqlite://", _env_file=None)
    assert settings.performance_log_enabled is False
    monkeypatch.setattr(api_app, "get_settings", lambda: settings)
    install = Mock(side_effect=AssertionError("disabled instrumentation installed SQL hooks"))
    monkeypatch.setattr(api_app, "install_sql_observers", install)
    monkeypatch.setattr(api_app.RuleCache, "load_with_retry", lambda *_: SimpleNamespace())
    monkeypatch.setattr(api_app, "shutdown_cpu_pool", lambda: None)
    app = api_app.create_app()
    assert all(m.cls is not perf.PerformanceMiddleware for m in app.user_middleware)
    with caplog.at_level(logging.INFO, logger=perf.__name__), TestClient(app) as client:
        assert client.get("/unknown").status_code == 404
    install.assert_not_called()
    assert records(caplog) == []


def test_sync_thread_queries_errors_and_hold_time_are_scoped_without_payloads(sql_engine, caplog):
    app = FastAPI()
    app.add_middleware(perf.PerformanceMiddleware)

    @app.get("/items/{item}")
    def query(item: str):
        assert perf._current.get() is not None  # anyio copied the request context to this worker
        with sql_engine.connect() as connection:
            assert connection.execute(text("select :value"), {"value": item}).scalar() == item
            with pytest.raises(DBAPIError):
                connection.execute(text("select private_sql_column_that_does_not_exist"))
            assert connection.execute(text("select 2")).scalar() == 2
        return Response(content="unchanged", status_code=201, headers={"X-Unchanged": "yes"})

    with caplog.at_level(logging.INFO, logger=perf.__name__):
        response = TestClient(app).get("/items/private-id?token=secret", headers={"Authorization": "secret"})
    assert (response.status_code, response.text, response.headers["X-Unchanged"]) == (201, "unchanged", "yes")
    assert "server-timing" not in response.headers
    row, = records(caplog)
    assert row["route"] == "/items/{item}" and row["method"] == "GET" and row["status"] == 201
    assert row["sql_count"] == 3 and row["sql_ms"] >= 0
    assert row["wall_ms"] >= row["db_connection_hold_ms"] >= row["sql_ms"]
    assert row["active_requests_at_start"] == 1 and row["active_requests"] == 0
    assert row["db_connections_open_at_finish"] == 0 and row["response_complete"] and not row["failed"]
    assert not any(secret in caplog.text for secret in ("private-id", "token", "secret", "private_sql_column"))
    assert perf._current.get() is None


def test_429_and_unmatched_routes_use_bounded_labels(caplog):
    app = FastAPI()
    app.add_middleware(perf.PerformanceMiddleware)

    @app.get("/busy")
    def busy():
        raise HTTPException(429, "simulation concurrency limit reached", headers={"Retry-After": "1"})

    with caplog.at_level(logging.INFO, logger=perf.__name__):
        client = TestClient(app)
        response = client.get("/busy")
        assert response.status_code == 429 and response.headers["Retry-After"] == "1"
        assert client.request("PRIVATE-METHOD", "/unknown-secret").status_code == 404
    busy_row, missing = records(caplog)
    assert busy_row["status"] == 429 and busy_row["route"] == "/busy"
    assert missing["route"] == "__unmatched__" and missing["method"] == "OTHER"
    assert "unknown-secret" not in caplog.text and "PRIVATE-METHOD" not in caplog.text


def test_stream_is_logged_only_after_last_body_and_application_cleanup(caplog):
    async def run():
        body_sent, finish = asyncio.Event(), asyncio.Event()

        async def app(_scope, _receive, output):
            await output({"type": "http.response.start", "status": 200, "headers": []})
            await output({"type": "http.response.body", "body": b"first", "more_body": True})
            body_sent.set()
            await finish.wait()
            await output({"type": "http.response.body", "body": b"last"})
            assert records(caplog) == []  # background/dependency cleanup is still part of the call

        middleware = perf.PerformanceMiddleware(app)
        messages = []

        async def collect(message):
            messages.append(message)

        task = asyncio.create_task(middleware(scope(), receive, collect))
        await body_sent.wait()
        assert records(caplog) == [] and middleware._active == 1
        assert perf._current.get() is None  # task-local, never leaks to the caller
        finish.set()
        await task
        assert [m.get("body") for m in messages[1:]] == [b"first", b"last"]
        assert middleware._active == 0

    with caplog.at_level(logging.INFO, logger=perf.__name__):
        asyncio.run(run())
    row, = records(caplog)
    assert row["response_complete"] and not row["failed"]


@pytest.mark.parametrize("after_start", [False, True])
def test_exception_preserves_original_error_and_resets_context(caplog, after_start):
    error = RuntimeError("private exception text")

    async def app(_scope, _receive, output):
        if after_start:
            await output({"type": "http.response.start", "status": 202, "headers": []})
        raise error

    async def run():
        middleware = perf.PerformanceMiddleware(app)
        with pytest.raises(RuntimeError) as raised:
            await middleware(scope(), receive, send)
        assert raised.value is error
        assert perf._current.get() is None and middleware._active == 0

    with caplog.at_level(logging.INFO, logger=perf.__name__):
        asyncio.run(run())
    row, = records(caplog)
    assert row["status"] == (202 if after_start else 500) and row["failed"] and not row["response_complete"]
    assert "private exception" not in caplog.text


def test_cancelled_stream_releases_active_count_and_context(caplog):
    async def run():
        entered = asyncio.Event()

        async def app(_scope, _receive, output):
            await output({"type": "http.response.start", "status": 200, "headers": []})
            entered.set()
            await asyncio.Event().wait()

        middleware = perf.PerformanceMiddleware(app)
        task = asyncio.create_task(middleware(scope(), receive, send))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert middleware._active == 0 and perf._current.get() is None

    with caplog.at_level(logging.INFO, logger=perf.__name__):
        asyncio.run(run())
    row, = records(caplog)
    assert row["failed"] and not row["response_complete"] and row["active_requests"] == 0


def test_concurrent_requests_and_cross_context_checkin_keep_their_owners(sql_engine, caplog):
    async def run():
        ready, finish = asyncio.Event(), asyncio.Event()

        async def app(request_scope, _receive, output):
            connection = sql_engine.connect()
            connection.execute(text("select 1"))
            if request_scope["method"] == "GET":
                ready.set()
                await finish.wait()
            else:
                connection.execute(text("select 2"))
                finish.set()
            # Connection teardown may execute outside the dependency's copied context.
            token = perf._current.set(None)
            try:
                connection.close()
            finally:
                perf._current.reset(token)
            await output({"type": "http.response.start", "status": 200, "headers": []})
            await output({"type": "http.response.body", "body": b""})

        middleware = perf.PerformanceMiddleware(app)
        first = asyncio.create_task(middleware(scope(), receive, send))
        await ready.wait()
        second = asyncio.create_task(middleware(scope("POST"), receive, send))
        await asyncio.gather(first, second)
        assert middleware._active == 0 and perf._current.get() is None

    with caplog.at_level(logging.INFO, logger=perf.__name__):
        asyncio.run(run())
    rows = {row["method"]: row for row in records(caplog)}
    assert rows["GET"]["sql_count"] == 1 and rows["POST"]["sql_count"] == 2
    assert rows["POST"]["active_requests_at_start"] == 2
    assert all(row["db_connections_open_at_finish"] == 0 for row in rows.values())


def test_enabled_lifespan_wires_hooks_and_preserves_cpu_cleanup(monkeypatch, caplog):
    settings = Settings(database_url="sqlite://", performance_log_enabled=True, _env_file=None)
    monkeypatch.setattr(api_app, "get_settings", lambda: settings)
    monkeypatch.setattr(api_app.RuleCache, "load_with_retry", lambda *_: SimpleNamespace())
    shutdown = Mock()
    monkeypatch.setattr(api_app, "shutdown_cpu_pool", shutdown)
    app = api_app.create_app()

    @app.get("/perf-test")
    def query():
        with app.state.engine.connect() as connection:
            return {"value": connection.execute(text("select 1")).scalar()}

    with caplog.at_level(logging.INFO, logger=perf.__name__), TestClient(app) as client:
        assert client.get("/perf-test").json() == {"value": 1}
    shutdown.assert_called_once()
    row, = records(caplog)
    assert row["sql_count"] == 1
    assert not app.state.engine.dispatch.before_cursor_execute


def test_logging_failure_does_not_replace_response_or_exception(monkeypatch):
    monkeypatch.setattr(perf.logger, "info", Mock(side_effect=RuntimeError("logging failed")))

    async def app(_scope, _receive, output):
        await output({"type": "http.response.start", "status": 204, "headers": []})
        await output({"type": "http.response.body", "body": b""})

    asyncio.run(perf.PerformanceMiddleware(app)(scope(), receive, send))
    assert perf._current.get() is None


def test_open_connection_is_clipped_at_request_end_and_late_checkin_does_not_leak(sql_engine, caplog):
    connections = []

    async def app(_scope, _receive, output):
        connection = sql_engine.connect()
        connections.append(connection)
        connection.execute(text("select 1"))
        await output({"type": "http.response.start", "status": 200, "headers": []})
        await output({"type": "http.response.body", "body": b""})

    with caplog.at_level(logging.INFO, logger=perf.__name__):
        try:
            asyncio.run(perf.PerformanceMiddleware(app)(scope(), receive, send))
            row, = records(caplog)
            assert row["db_connections_open_at_finish"] == 1 and row["db_connection_hold_ms"] >= row["sql_ms"]
        finally:
            for connection in connections:
                connection.close()
        assert records(caplog) == [row]
        assert perf._current.get() is None


def test_invalidated_connections_and_unscoped_sql_do_not_pollute_request_counts(sql_engine):
    with sql_engine.connect() as connection:
        connection.execute(text("select 1"))  # startup/background SQL has no request owner
    owner = perf._RequestMetrics()
    token = perf._current.set(owner)
    try:
        with sql_engine.connect() as connection:
            connection.execute(text("select 1"))
            connection.invalidate()
        result = owner.finish()
        assert result["sql_count"] == 1 and result["db_connections_open_at_finish"] == 0
        with sql_engine.connect() as connection:
            connection.execute(text("select 2"))  # a late copied context cannot change a closed summary
        assert owner.sql_count == 1 and not owner.checkouts
    finally:
        perf._current.reset(token)
