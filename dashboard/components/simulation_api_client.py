from __future__ import annotations

from typing import Any

import requests

from dashboard.components.viewer_api_client import RequestFunc, ViewerApiError


def list_simulation_results(
    api_base: str,
    request_func: RequestFunc | None = None,
    *,
    scenario_ref: str | None = None,
    variant_ref: str | None = None,
    latest: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    response = _request_json(
        "GET",
        api_base,
        "/simulation/results",
        request_func=request_func,
        params={
            "scenario_ref": scenario_ref,
            "variant_ref": variant_ref,
            "latest": latest,
            "limit": limit,
            "sort_by": "id",
            "sort_dir": "desc",
        },
    )
    return [item for item in response.get("items") or [] if isinstance(item, dict)]


def run_simulation(
    api_base: str,
    payload: dict[str, Any],
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        api_base,
        "/simulation/run",
        request_func=request_func,
        json=payload,
    )


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
