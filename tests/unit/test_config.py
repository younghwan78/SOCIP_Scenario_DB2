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


def test_settings_parse_mutation_api_keys_as_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test-auth.db")
    monkeypatch.setenv(
        "SCENARIO_DB_MUTATION_API_KEYS",
        '{"architect@example.com":"top-secret"}',
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    secret = settings.mutation_api_keys["architect@example.com"]
    assert secret.get_secret_value() == "top-secret"
    assert "top-secret" not in repr(settings)


def test_settings_parse_role_bearing_api_principals_as_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test-rbac.db")
    monkeypatch.setenv(
        "SCENARIO_DB_API_PRINCIPALS",
        '{"analyst@example.com":{"secret":"role-secret","roles":["analyst"]}}',
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    principal = settings.api_principals["analyst@example.com"]
    assert principal.roles == {"analyst"}
    assert principal.secret.get_secret_value() == "role-secret"
    assert "role-secret" not in repr(settings)


def test_api_principal_requires_at_least_one_valid_role(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test-rbac-invalid.db")
    monkeypatch.setenv(
        "SCENARIO_DB_API_PRINCIPALS",
        '{"nobody@example.com":{"secret":"role-secret","roles":[]}}',
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "api_principals" in str(exc_info.value)


def test_query_candidate_limits_must_be_positive(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test-query-limit.db")
    monkeypatch.setenv("SCENARIO_DB_QUERY_MAX_CANDIDATES", "0")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "query_max_candidates" in str(exc_info.value)
