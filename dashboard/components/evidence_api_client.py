"""Generic evidence list client (kind-aware) for the Evidence Dashboard.

Uses the generic ``GET /evidence`` endpoint (filters by kind / project_ref /
scenario_ref / variant_ref), so it serves measurement and projection evidence
that the simulation-specific ``/simulation/results`` endpoint does not target.
"""
from __future__ import annotations

from typing import Any

import requests

from dashboard.components.viewer_api_client import RequestFunc, ViewerApiError

KIND_MEASUREMENT = "evidence.measurement"
KIND_SIMULATION = "evidence.simulation"


def list_evidence(
    api_base: str,
    request_func: RequestFunc | None = None,
    *,
    kind: str | None = None,
    scenario_ref: str | None = None,
    variant_ref: str | None = None,
    project_ref: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params = {
        "kind": kind,
        "scenario_ref": scenario_ref,
        "variant_ref": variant_ref,
        "project_ref": project_ref,
        "limit": limit,
        "sort_by": "measured_at",
        "sort_dir": "desc",
    }
    # Drop unset filters: an empty/None value must mean "no filter", not
    # "match empty string" (the API filters on any non-None value).
    params = {k: v for k, v in params.items() if v is not None}
    response = _request_json(
        "GET",
        api_base,
        "/evidence",
        request_func=request_func,
        params=params,
    )
    return [item for item in response.get("items") or [] if isinstance(item, dict)]


def _request_json(
    method: str,
    api_base: str,
    path: str,
    *,
    request_func: RequestFunc | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    requester = request_func or requests.request
    url = f"{api_base.rstrip('/')}{path}"
    try:
        response = requester(method, url, timeout=20, **kwargs)
    except requests.RequestException as exc:
        raise ViewerApiError(f"API request failed: {exc}") from exc

    status_code = getattr(response, "status_code", None)
    if status_code is not None and status_code >= 400:
        body = getattr(response, "text", "")
        raise ViewerApiError(f"API returned HTTP {status_code}", status_code=status_code, body=body)
    try:
        result = response.json()
    except ValueError as exc:
        body = getattr(response, "text", "")
        raise ViewerApiError("API response was not JSON", status_code=status_code, body=body) from exc
    if not isinstance(result, dict):
        raise ViewerApiError("API response JSON root was not an object", status_code=status_code)
    return result
