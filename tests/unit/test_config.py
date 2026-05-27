from __future__ import annotations

import pytest
from pydantic import ValidationError

from scenario_db.config import Settings, get_settings


def test_get_settings_uses_lru_cached_singleton(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test-cache.db")
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second


def test_settings_require_database_url_for_server_startup(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SCENARIO_DB_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    message = str(exc_info.value)
    assert "SCENARIO_DB_DATABASE_URL" in message
