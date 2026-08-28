from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, Header, HTTPException

from scenario_db.config import get_settings

PROTECTED_ROLES = frozenset({"analyst", "writer", "admin"})
ALL_ROLES = frozenset({"reader", *PROTECTED_ROLES})


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    subject: str
    roles: frozenset[str] = PROTECTED_ROLES


def require_api_principal(
    key_id: str | None = Header(default=None, alias="X-ScenarioDB-Key-Id"),
    api_key: str | None = Header(default=None, alias="X-ScenarioDB-API-Key"),
) -> ApiPrincipal:
    """Authenticate protected API calls and return the configured roles.

    Key IDs are stable audit identities. Secrets are configured only on the
    server and compared in constant time.
    """

    settings = get_settings()
    if settings.mutation_auth_disabled:
        return ApiPrincipal(subject="local-auth-disabled", roles=ALL_ROLES)

    configured_principals = getattr(settings, "api_principals", {})
    legacy_keys = settings.mutation_api_keys
    if not configured_principals and not legacy_keys:
        raise HTTPException(
            status_code=503,
            detail=(
                "API authentication is not configured. Set SCENARIO_DB_API_PRINCIPALS "
                "(preferred), SCENARIO_DB_MUTATION_API_KEYS (deprecated), or explicitly "
                "enable the local-only bypass."
            ),
        )
    if not key_id or not api_key:
        raise HTTPException(
            status_code=401,
            detail="API credentials are required",
            headers={"WWW-Authenticate": "ScenarioDBApiKey"},
        )

    configured = configured_principals.get(key_id)
    if configured is not None:
        expected_secret = configured.secret
        roles = frozenset(configured.roles)
    else:
        expected_secret = legacy_keys.get(key_id)
        roles = PROTECTED_ROLES
    if expected_secret is None or not secrets.compare_digest(api_key, expected_secret.get_secret_value()):
        raise HTTPException(
            status_code=401,
            detail="Invalid API credentials",
            headers={"WWW-Authenticate": "ScenarioDBApiKey"},
        )
    return ApiPrincipal(subject=key_id, roles=roles)


def require_roles(*allowed_roles: str) -> Callable[..., ApiPrincipal]:
    """Build a FastAPI dependency that requires at least one allowed role."""

    required = frozenset(allowed_roles)
    unknown = required - ALL_ROLES
    if not required or unknown:
        raise ValueError(f"Invalid role requirement: {sorted(unknown or required)}")

    def authorize(principal: ApiPrincipal = Depends(require_api_principal)) -> ApiPrincipal:
        if principal.roles.isdisjoint(required):
            raise HTTPException(
                status_code=403,
                detail=f"Required role: one of {', '.join(sorted(required))}",
            )
        return principal

    return authorize


# Backward-compatible names for callers that have not migrated yet.
MutationPrincipal = ApiPrincipal
require_mutation_principal = require_api_principal
