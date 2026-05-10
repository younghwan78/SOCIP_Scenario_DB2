from __future__ import annotations

from scenario_db.config import get_settings


def test_get_settings_uses_lru_cached_singleton():
    get_settings.cache_clear()

    first = get_settings()
    second = get_settings()

    assert first is second
