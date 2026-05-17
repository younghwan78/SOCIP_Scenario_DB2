from __future__ import annotations

from typing import Any

import requests

from dashboard.components.viewer_api_client import RequestFunc, ViewerApiError


def list_exploration_examples(
    api_base: str,
    request_func: RequestFunc | None = None,
) -> list[dict[str, Any]]:
    response = _request_json("GET", api_base, "/exploration/examples", request_func=request_func)
    return [item for item in response.get("items") or [] if isinstance(item, dict)]


def get_exploration_example(
    api_base: str,
    example_id: str,
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json("GET", api_base, f"/exploration/examples/{example_id}", request_func=request_func)


def compile_exploration_recipe(
    api_base: str,
    *,
    source_yaml: str,
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        api_base,
        "/exploration/recipes/compile",
        request_func=request_func,
        json={"source_yaml": source_yaml},
    )


def compile_exploration_sweep(
    api_base: str,
    *,
    source_yaml: str,
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        api_base,
        "/exploration/sweeps/compile",
        request_func=request_func,
        json={"source_yaml": source_yaml},
    )


def compile_exploration_template(
    api_base: str,
    *,
    source_yaml: str,
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        api_base,
        "/exploration/templates/compile",
        request_func=request_func,
        json={"source_yaml": source_yaml},
    )


def preview_exploration_sweep(
    api_base: str,
    *,
    source_yaml: str | None = None,
    sweep: dict[str, Any] | None = None,
    include_results: bool = True,
    config: dict[str, Any] | None = None,
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "include_results": include_results,
        "config": config or {"include_timeline": True, "timeline_frame_count": 4, "debug_trace": True, "debug_trace_level": "formula"},
    }
    if source_yaml is not None:
        payload["source_yaml"] = source_yaml
    if sweep is not None:
        payload["sweep"] = sweep
    return _request_json(
        "POST",
        api_base,
        "/exploration/sweeps/preview",
        request_func=request_func,
        json=payload,
    )


def preview_exploration_template(
    api_base: str,
    *,
    source_yaml: str,
    include_results: bool = True,
    config: dict[str, Any] | None = None,
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json(
        "POST",
        api_base,
        "/exploration/templates/preview",
        request_func=request_func,
        json={
            "source_yaml": source_yaml,
            "include_results": include_results,
            "config": config or {"include_timeline": True, "timeline_frame_count": 4, "debug_trace": True, "debug_trace_level": "formula"},
        },
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
        response = requester(method, url, timeout=30, **kwargs)
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
