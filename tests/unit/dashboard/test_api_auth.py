from __future__ import annotations

import pytest

from dashboard.components.api_auth import mutation_auth_headers


def test_mutation_auth_headers_are_empty_when_not_configured(monkeypatch):
    monkeypatch.delenv("SCENARIODB_API_KEY_ID", raising=False)
    monkeypatch.delenv("SCENARIODB_API_KEY", raising=False)

    assert mutation_auth_headers() == {}


def test_mutation_auth_headers_require_a_complete_pair(monkeypatch):
    monkeypatch.setenv("SCENARIODB_API_KEY_ID", "architect@example.com")
    monkeypatch.delenv("SCENARIODB_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Set both"):
        mutation_auth_headers()


def test_mutation_auth_headers_build_server_contract(monkeypatch):
    monkeypatch.setenv("SCENARIODB_API_KEY_ID", "architect@example.com")
    monkeypatch.setenv("SCENARIODB_API_KEY", "top-secret")

    assert mutation_auth_headers() == {
        "X-ScenarioDB-Key-Id": "architect@example.com",
        "X-ScenarioDB-API-Key": "top-secret",
    }

