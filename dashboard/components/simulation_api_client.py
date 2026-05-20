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


def delete_simulation_result(
    api_base: str,
    evidence_id: str,
    request_func: RequestFunc | None = None,
) -> None:
    _request_no_content(
        "DELETE",
        api_base,
        f"/simulation/results/{evidence_id}",
        request_func=request_func,
    )


def export_simulation_artifacts(
    api_base: str,
    evidence_id: str,
    request_func: RequestFunc | None = None,
    *,
    output_dir: str | None = None,
    overwrite: bool = True,
    project_ref: str | None = None,
    scenario_name: str | None = None,
    variant_name: str | None = None,
    soc_ref: str | None = None,
) -> dict[str, Any]:
    payload = {
        "output_dir": output_dir,
        "overwrite": overwrite,
        "project_ref": project_ref,
        "scenario_name": scenario_name,
        "variant_name": variant_name,
        "soc_ref": soc_ref,
    }
    return _request_json(
        "POST",
        api_base,
        f"/simulation/results/{evidence_id}/artifacts/export",
        request_func=request_func,
        json={key: value for key, value in payload.items() if value is not None},
    )


def get_simulation_readiness(
    api_base: str,
    *,
    scenario_id: str,
    variant_id: str,
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json(
        "GET",
        api_base,
        "/simulation/readiness",
        request_func=request_func,
        params={"scenario_id": scenario_id, "variant_id": variant_id},
    )


def _request_no_content(
    method: str,
    api_base: str,
    path: str,
    *,
    request_func: RequestFunc | None = None,
    **kwargs: Any,
) -> None:
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
