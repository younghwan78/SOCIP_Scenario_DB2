from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace

from scenario_db.api import app as api_app
from scenario_db.api.cache import RuleCache
from scenario_db.api.routers import utility
from scenario_db.api.routers import write as write_router
from scenario_db.write import service as write_service


class _FailingSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement):
        raise RuntimeError("db is down")


def test_configure_logging_applies_project_log_level() -> None:
    logger = logging.getLogger("scenario_db")
    previous_level = logger.level
    try:
        api_app.configure_logging(SimpleNamespace(log_level="DEBUG"))
        assert logger.level == logging.DEBUG
    finally:
        logger.setLevel(previous_level)


def test_readiness_logs_database_probe_failure(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        utility,
        "timeline_dependencies_status",
        lambda: {"available": True, "missing": [], "error": None},
        raising=False,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                session_factory=lambda: _FailingSession(),
                rule_cache=RuleCache(loaded=True),
                start_time=time.time(),
            )
        )
    )

    with caplog.at_level(logging.WARNING, logger="scenario_db.api.routers.utility"):
        response = utility.readiness(request)

    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["db"] == "unreachable"
    assert "Readiness database probe failed" in caplog.text
    assert "db is down" in caplog.text


def test_write_apply_route_forwards_rule_cache(monkeypatch) -> None:
    forwarded: dict[str, object] = {}

    def fake_apply_batch(db, batch_id, *, rule_cache=None):
        forwarded["db"] = db
        forwarded["batch_id"] = batch_id
        forwarded["rule_cache"] = rule_cache
        return {"batch_id": batch_id, "status": "applied", "applied_refs": []}

    fake_db = object()
    fake_cache = RuleCache(loaded=True)
    monkeypatch.setattr(write_router, "apply_batch", fake_apply_batch)

    write_router.apply_staging_batch("batch-1", db=fake_db, rule_cache=fake_cache)

    assert forwarded == {
        "db": fake_db,
        "batch_id": "batch-1",
        "rule_cache": fake_cache,
    }


class _BatchQuery:
    def __init__(self, batch):
        self.batch = batch

    def filter_by(self, **kwargs):
        return self

    def one_or_none(self):
        return self.batch


class _FakeSession:
    def __init__(self, batch):
        self.batch = batch
        self.events: list[str] = []

    def query(self, model):
        return _BatchQuery(self.batch)

    def add(self, row) -> None:
        self.events.append("event")

    def commit(self) -> None:
        self.events.append("commit")


class _FakeRuleCache:
    def __init__(self, events: list[str]):
        self.events = events

    def invalidate_all(self, session) -> None:
        self.events.append("invalidate")


def test_apply_batch_invalidates_rule_cache_after_commit(monkeypatch) -> None:
    batch = SimpleNamespace(
        id="batch-1",
        kind=write_service.VARIANT_OVERLAY_KIND,
        raw_payload={},
        normalized_payload={"scenario_ref": "scenario-1", "variant": {"id": "variant-1"}},
        validation_result={"valid": True, "issues": []},
        actor="tester",
        status="diff_ready",
        diff_result={},
        applied_refs=None,
        updated_at=None,
    )
    session = _FakeSession(batch)
    cache = _FakeRuleCache(session.events)
    monkeypatch.setattr(
        write_service,
        "_apply_variant_overlay",
        lambda db, payload: {"scenario_ref": "scenario-1", "variant_id": "variant-1"},
    )

    response = write_service.apply_batch(session, "batch-1", rule_cache=cache)

    assert response.status == "applied"
    assert session.events[-2:] == ["commit", "invalidate"]
