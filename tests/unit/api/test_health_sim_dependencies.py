from __future__ import annotations

import json
import time
from types import SimpleNamespace

from scenario_db.api.cache import RuleCache
from scenario_db.api.routers import utility


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement):
        return None


def test_readiness_is_not_ready_when_simulation_dependencies_are_missing(monkeypatch):
    monkeypatch.setattr(
        utility,
        "timeline_dependencies_status",
        lambda: {
            "available": False,
            "missing": ["simpy"],
            "error": "timeline simulation dependencies are missing: simpy",
        },
        raising=False,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                session_factory=lambda: _Session(),
                rule_cache=RuleCache(loaded=True),
                start_time=time.time(),
            )
        )
    )

    response = utility.readiness(request)
    body = json.loads(response.body)

    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["simulation_dependencies"] == {
        "available": False,
        "missing": ["simpy"],
        "error": "timeline simulation dependencies are missing: simpy",
    }
