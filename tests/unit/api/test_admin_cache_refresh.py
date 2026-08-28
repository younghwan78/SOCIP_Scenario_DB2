from __future__ import annotations

from scenario_db.api.cache import RuleCache
from scenario_db.api.routers.admin import refresh_rule_cache
from scenario_db.db.models.decision import GateRule, Issue


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class _Session:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return _Query(self.rows.get(model, []))


def test_refresh_rule_cache_reloads_from_db():
    """Regression: ETL이 적재한 issue/gate_rule을 재시작 없이 반영하는 경로."""
    issue = Issue(
        id="iss-new",
        schema_version="2.2",
        metadata_={"title": "LLC thrashing"},
        affects=[{"scenario_ref": "*"}],
        yaml_sha256="sha",
    )
    session = _Session({Issue: [issue], GateRule: []})
    cache = RuleCache(issues=[], gate_rules=[], loaded=False, load_error="boot failure")

    result = refresh_rule_cache(db=session, cache=cache)

    assert result["loaded"] is True
    assert result["issues"] == 1
    assert result["gate_rules"] == 0
    assert result["load_error"] is None
    assert [iss.id for iss in cache.issues] == ["iss-new"]


def test_rule_cache_refreshes_after_ttl_and_not_before():
    issue = Issue(
        id="iss-new",
        schema_version="2.2",
        metadata_={"title": "LLC thrashing"},
        affects=[{"scenario_ref": "*"}],
        yaml_sha256="sha",
    )
    session = _Session({Issue: [issue], GateRule: []})
    cache = RuleCache(
        issues=[],
        gate_rules=[],
        loaded=True,
        loaded_at_monotonic=100.0,
    )

    cache.refresh_if_stale(session, 5.0, now=104.9)
    assert cache.issues == []

    cache.refresh_if_stale(session, 5.0, now=105.0)
    assert [item.id for item in cache.issues] == ["iss-new"]
    assert cache.loaded_at_monotonic == 105.0


def test_rule_cache_zero_ttl_refreshes_every_request():
    issue = Issue(
        id="iss-always-fresh",
        schema_version="2.2",
        metadata_={"title": "Fresh"},
        affects=[{"scenario_ref": "*"}],
        yaml_sha256="sha",
    )
    cache = RuleCache(loaded=True, loaded_at_monotonic=100.0)

    cache.refresh_if_stale(
        _Session({Issue: [issue], GateRule: []}),
        0.0,
        now=100.0,
    )

    assert [item.id for item in cache.issues] == ["iss-always-fresh"]


def test_admin_router_registered_only_when_enabled(monkeypatch):
    """기본 off(기존 'Admin 엔드포인트 제거' 결정 유지), 플래그로만 활성화."""
    from scenario_db.api import app as app_module
    from scenario_db.config import Settings

    def _routes(enabled: bool) -> set[str]:
        monkeypatch.setattr(
            app_module,
            "get_settings",
            lambda: Settings(database_url="sqlite://", admin_endpoints_enabled=enabled),
        )
        return {route.path for route in app_module.create_app().routes}

    assert "/api/v1/admin/cache/refresh" not in _routes(enabled=False)
    assert "/api/v1/admin/cache/refresh" in _routes(enabled=True)
