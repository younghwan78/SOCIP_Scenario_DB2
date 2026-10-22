"""Enabled timing observation leaves real PostgreSQL HTTP reads unchanged."""
import json
import logging

from fastapi.testclient import TestClient

from scenario_db.api import app as api_app
from scenario_db.api import performance as perf
from scenario_db.db.session import make_session_factory


def test_postgres_http_observation_preserves_response_and_removes_hooks(engine, monkeypatch, caplog):
    # The in-process Alembic fixture disables existing loggers via fileConfig.
    monkeypatch.setattr(perf.logger, "disabled", False)
    original = api_app.get_settings()
    url = "/api/v1/scenarios/uc-projecta-fhd30-recording/variants?limit=1&sort_by=id"

    def client(enabled):
        monkeypatch.setattr(api_app, "get_settings", lambda: original.model_copy(
            update={"performance_log_enabled": enabled}))
        app = api_app.create_app()
        app.state.session_factory = make_session_factory(engine)
        # No app lifespan: this test's PostgreSQL fixture owns the migrated engine.
        return TestClient(app)

    baseline = client(False).get(url)
    assert baseline.status_code == 200 and engine.pool.checkedout() == 0
    listeners_before = len(engine.dispatch.before_cursor_execute)
    remove = perf.install_sql_observers(engine)
    try:
        assert len(engine.dispatch.before_cursor_execute) == listeners_before + 1
        with caplog.at_level(logging.INFO, logger=perf.__name__):
            observed = client(True).get(url)
        assert observed.status_code == baseline.status_code
        assert observed.headers == baseline.headers and observed.content == baseline.content
        row, = [json.loads(record.message) for record in caplog.records if record.name == perf.__name__]
        assert row["route"] == "/api/v1/scenarios/{scenario_id}/variants"
        assert row["status"] == 200 and row["method"] == "GET"
        assert row["sql_count"] >= 3 and row["sql_ms"] > 0
        assert row["db_connection_hold_ms"] >= row["sql_ms"]
        assert row["db_connections_open_at_finish"] == 0
        assert row["response_complete"] and not row["failed"] and row["active_requests"] == 0
        assert engine.pool.checkedout() == 0
        assert "uc-projecta" not in json.dumps(row) and "sort_by" not in json.dumps(row)
    finally:
        remove()
    assert len(engine.dispatch.before_cursor_execute) == listeners_before
