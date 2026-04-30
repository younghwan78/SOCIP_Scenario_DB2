from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests


class ViewerApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


RequestFunc = Callable[..., Any]


def list_scenarios(
    api_base: str,
    request_func: RequestFunc | None = None,
    *,
    project_ref: str | None = None,
    soc_ref: str | None = None,
    board_type: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    params = {
        "limit": limit,
        "sort_by": "id",
        "sort_dir": "asc",
        "project_ref": project_ref,
        "soc_ref": soc_ref,
        "board_type": board_type,
    }
    response = _request_json(
        "GET",
        api_base,
        "/scenarios",
        request_func=request_func,
        params=_clean_params(params),
    )
    return [item for item in response.get("items") or [] if isinstance(item, dict)]


def list_soc_platforms(
    api_base: str,
    request_func: RequestFunc | None = None,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    response = _request_json(
        "GET",
        api_base,
        "/soc-platforms",
        request_func=request_func,
        params={"limit": limit, "sort_by": "id", "sort_dir": "asc"},
    )
    return [item for item in response.get("items") or [] if isinstance(item, dict)]


def list_projects(
    api_base: str,
    request_func: RequestFunc | None = None,
    *,
    soc_ref: str | None = None,
    board_type: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    response = _request_json(
        "GET",
        api_base,
        "/projects",
        request_func=request_func,
        params=_clean_params(
            {
                "limit": limit,
                "sort_by": "id",
                "sort_dir": "asc",
                "soc_ref": soc_ref,
                "board_type": board_type,
            }
        ),
    )
    return [item for item in response.get("items") or [] if isinstance(item, dict)]


def list_variants(
    api_base: str,
    scenario_id: str,
    request_func: RequestFunc | None = None,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    if not scenario_id:
        return []
    response = _request_json(
        "GET",
        api_base,
        f"/scenarios/{scenario_id}/variants",
        request_func=request_func,
        params={"limit": limit, "sort_by": "id", "sort_dir": "asc"},
    )
    return [item for item in response.get("items") or [] if isinstance(item, dict)]


def scenario_label(item: dict[str, Any]) -> str:
    scenario_id = str(item.get("id") or "")
    metadata = _metadata(item)
    name = metadata.get("name")
    project_ref = item.get("project_ref")
    parts = [scenario_id]
    if name:
        parts.append(str(name))
    if project_ref:
        parts.append(f"project={project_ref}")
    return " | ".join(parts)


def soc_label(item: dict[str, Any]) -> str:
    soc_id = str(item.get("id") or "")
    chips = []
    for key in ("process_node", "memory_type", "bus_protocol"):
        value = item.get(key)
        if value:
            chips.append(str(value))
    return f"{soc_id} | {', '.join(chips)}" if chips else soc_id


def project_label(item: dict[str, Any]) -> str:
    project_id = str(item.get("id") or "")
    metadata = _metadata(item)
    name = metadata.get("name")
    soc_ref = metadata.get("soc_ref")
    board_type = metadata.get("board_type")
    board_name = metadata.get("board_name")
    chips = []
    if name:
        chips.append(str(name))
    if soc_ref:
        chips.append(f"soc={soc_ref}")
    if board_type:
        chips.append(f"board={board_type}")
    if board_name:
        chips.append(str(board_name))
    return f"{project_id} | {' | '.join(chips)}" if chips else project_id


def variant_label(item: dict[str, Any]) -> str:
    variant_id = str(item.get("id") or "")
    design = item.get("design_conditions") if isinstance(item.get("design_conditions"), dict) else {}
    chips = []
    for key in ("resolution", "fps", "codec", "dynamic_range"):
        value = design.get(key)
        if value is not None:
            chips.append(f"{key}={value}")
    return f"{variant_id} | {', '.join(chips)}" if chips else variant_id


def default_variant_id(variants: list[dict[str, Any]], previous: str | None = None) -> str:
    ids = [str(item.get("id")) for item in variants if item.get("id")]
    if previous and previous in ids:
        return previous
    return ids[0] if ids else ""


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata_")
    if not isinstance(metadata, dict):
        metadata = item.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value is not None}


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
        response = requester(method, url, timeout=10, **kwargs)
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
