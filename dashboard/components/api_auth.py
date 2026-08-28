from __future__ import annotations

import os


def mutation_auth_headers() -> dict[str, str]:
    """Return configured ScenarioDB mutation credentials for server-side clients."""

    key_id = os.environ.get("SCENARIODB_API_KEY_ID", "").strip()
    api_key = os.environ.get("SCENARIODB_API_KEY", "").strip()
    if bool(key_id) != bool(api_key):
        raise RuntimeError(
            "Set both SCENARIODB_API_KEY_ID and SCENARIODB_API_KEY for mutation requests"
        )
    if not key_id:
        return {}
    return {
        "X-ScenarioDB-Key-Id": key_id,
        "X-ScenarioDB-API-Key": api_key,
    }
