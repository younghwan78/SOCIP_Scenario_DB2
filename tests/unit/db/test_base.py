from __future__ import annotations

from scenario_db.config import get_settings
from scenario_db.db import base


def test_resolve_database_url_prefers_scenario_db_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///legacy.db")
    monkeypatch.setenv("SCENARIO_DB_DATABASE_URL", "sqlite:///scenario.db")
    get_settings.cache_clear()

    assert base.resolve_database_url() == "sqlite:///scenario.db"


def test_resolve_database_url_honors_explicit_argument(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///legacy.db")
    monkeypatch.setenv("SCENARIO_DB_DATABASE_URL", "sqlite:///scenario.db")
    get_settings.cache_clear()

    assert base.resolve_database_url("sqlite:///explicit.db") == "sqlite:///explicit.db"
