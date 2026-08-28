from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from scenario_db.api import auth
from scenario_db.api.auth import (
    ApiPrincipal,
    MutationPrincipal,
    require_mutation_principal,
    require_roles,
)
from scenario_db.api.routers import write as write_router
from scenario_db.api.schemas.write import StageWriteRequest


def _settings(
    *,
    keys: dict[str, str] | None = None,
    principals: dict[str, object] | None = None,
    disabled: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        api_principals=principals or {},
        mutation_api_keys={
            key_id: SecretStr(secret)
            for key_id, secret in (keys or {}).items()
        },
        mutation_auth_disabled=disabled,
    )


def _client(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> TestClient:
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    app = FastAPI()

    @app.post("/mutation")
    def mutation(
        principal: MutationPrincipal = Depends(require_mutation_principal),
    ) -> dict[str, str]:
        return {"subject": principal.subject}

    return TestClient(app)


def _role_client(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace, *roles: str) -> TestClient:
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    app = FastAPI()

    @app.post("/role-protected")
    def role_protected(
        principal: ApiPrincipal = Depends(require_roles(*roles)),
    ) -> dict[str, object]:
        return {"subject": principal.subject, "roles": sorted(principal.roles)}

    return TestClient(app)


def test_mutation_auth_fails_closed_when_keys_are_not_configured(monkeypatch):
    response = _client(monkeypatch, _settings()).post("/mutation")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_mutation_auth_requires_both_headers(monkeypatch):
    response = _client(
        monkeypatch,
        _settings(keys={"architect@example.com": "top-secret"}),
    ).post("/mutation")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "ScenarioDBApiKey"


def test_mutation_auth_rejects_invalid_secret_without_echoing_it(monkeypatch):
    response = _client(
        monkeypatch,
        _settings(keys={"architect@example.com": "top-secret"}),
    ).post(
        "/mutation",
        headers={
            "X-ScenarioDB-Key-Id": "architect@example.com",
            "X-ScenarioDB-API-Key": "wrong-secret",
        },
    )

    assert response.status_code == 401
    assert "wrong-secret" not in response.text
    assert "top-secret" not in response.text


def test_mutation_auth_returns_key_id_as_audit_subject(monkeypatch):
    response = _client(
        monkeypatch,
        _settings(keys={"architect@example.com": "top-secret"}),
    ).post(
        "/mutation",
        headers={
            "X-ScenarioDB-Key-Id": "architect@example.com",
            "X-ScenarioDB-API-Key": "top-secret",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "architect@example.com"}


def test_explicit_local_bypass_uses_non_user_audit_subject(monkeypatch):
    response = _client(monkeypatch, _settings(disabled=True)).post("/mutation")

    assert response.status_code == 200
    assert response.json() == {"subject": "local-auth-disabled"}


def test_role_bearing_principal_is_authorized_for_matching_role(monkeypatch):
    principal = SimpleNamespace(secret=SecretStr("top-secret"), roles={"analyst"})
    response = _role_client(
        monkeypatch,
        _settings(principals={"analyst@example.com": principal}),
        "analyst",
        "admin",
    ).post(
        "/role-protected",
        headers={
            "X-ScenarioDB-Key-Id": "analyst@example.com",
            "X-ScenarioDB-API-Key": "top-secret",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "subject": "analyst@example.com",
        "roles": ["analyst"],
    }


def test_role_bearing_principal_is_forbidden_for_non_matching_role(monkeypatch):
    principal = SimpleNamespace(secret=SecretStr("top-secret"), roles={"reader"})
    response = _role_client(
        monkeypatch,
        _settings(principals={"reader@example.com": principal}),
        "writer",
        "admin",
    ).post(
        "/role-protected",
        headers={
            "X-ScenarioDB-Key-Id": "reader@example.com",
            "X-ScenarioDB-API-Key": "top-secret",
        },
    )

    assert response.status_code == 403
    assert "top-secret" not in response.text


def test_legacy_key_retains_protected_roles_during_migration(monkeypatch):
    response = _role_client(
        monkeypatch,
        _settings(keys={"legacy@example.com": "top-secret"}),
        "admin",
    ).post(
        "/role-protected",
        headers={
            "X-ScenarioDB-Key-Id": "legacy@example.com",
            "X-ScenarioDB-API-Key": "top-secret",
        },
    )

    assert response.status_code == 200
    assert set(response.json()["roles"]) == {"admin", "analyst", "writer"}


def test_staging_actor_is_derived_from_authenticated_principal(monkeypatch):
    captured: dict[str, object] = {}

    def _stage_write(db, request):
        captured["db"] = db
        captured["request"] = request
        return {"batch_id": "batch-1", "status": "staged"}

    monkeypatch.setattr(write_router, "stage_write", _stage_write)
    db = object()
    result = write_router.create_staging_batch(
        StageWriteRequest(
            kind="scenario.pipeline_patch",
            payload={},
            actor="spoofed@example.com",
        ),
        db=db,
        principal=MutationPrincipal(subject="architect@example.com"),
    )

    assert result["batch_id"] == "batch-1"
    assert captured["db"] is db
    assert captured["request"].actor == "architect@example.com"
