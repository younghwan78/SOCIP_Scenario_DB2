from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Header, HTTPException

from scenario_db.config import get_settings


@dataclass(frozen=True, slots=True)
class MutationPrincipal:
    subject: str


def require_mutation_principal(
    key_id: str | None = Header(default=None, alias="X-ScenarioDB-Key-Id"),
    api_key: str | None = Header(default=None, alias="X-ScenarioDB-API-Key"),
) -> MutationPrincipal:
    """Authenticate state-changing and operational API calls.

    Key IDs are stable audit identities. Secrets are configured only on the
    server and compared in constant time.
    """

    settings = get_settings()
    if settings.mutation_auth_disabled:
        return MutationPrincipal(subject="local-auth-disabled")

    configured_keys = settings.mutation_api_keys
    if not configured_keys:
        raise HTTPException(
            status_code=503,
            detail=(
                "Mutation API authentication is not configured. "
                "Set SCENARIO_DB_MUTATION_API_KEYS or explicitly enable the local-only bypass."
            ),
        )
    if not key_id or not api_key:
        raise HTTPException(
            status_code=401,
            detail="Mutation API credentials are required",
            headers={"WWW-Authenticate": "ScenarioDBApiKey"},
        )

    expected = configured_keys.get(key_id)
    if expected is None or not secrets.compare_digest(api_key, expected.get_secret_value()):
        raise HTTPException(
            status_code=401,
            detail="Invalid mutation API credentials",
            headers={"WWW-Authenticate": "ScenarioDBApiKey"},
        )
    return MutationPrincipal(subject=key_id)
