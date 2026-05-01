from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from dashboard.components.viewer_api_client import RequestFunc, ViewerApiError, _clean_params, _request_json


def get_summary(api_base: str, request_func: RequestFunc | None = None, **filters: Any) -> dict[str, Any]:
    return _request_json(
        "GET",
        api_base,
        "/explorer/summary",
        request_func=request_func,
        params=_clean_params(filters),
    )


def get_scenario_catalog(api_base: str, request_func: RequestFunc | None = None, **filters: Any) -> dict[str, Any]:
    return _request_json(
        "GET",
        api_base,
        "/explorer/scenario-catalog",
        request_func=request_func,
        params=_clean_params(filters),
    )


def get_variant_matrix(api_base: str, request_func: RequestFunc | None = None, **filters: Any) -> dict[str, Any]:
    return _request_json(
        "GET",
        api_base,
        "/explorer/variant-matrix",
        request_func=request_func,
        params=_clean_params(filters),
    )


def get_import_health(api_base: str, request_func: RequestFunc | None = None, **filters: Any) -> dict[str, Any]:
    return _request_json(
        "GET",
        api_base,
        "/explorer/import-health",
        request_func=request_func,
        params=_clean_params(filters),
    )


def viewer_link(query: dict[str, Any]) -> str:
    clean = {key: value for key, value in query.items() if value not in (None, "")}
    return f"/Pipeline_Viewer?{urlencode(clean)}" if clean else "/Pipeline_Viewer"


__all__ = [
    "ViewerApiError",
    "get_import_health",
    "get_scenario_catalog",
    "get_summary",
    "get_variant_matrix",
    "viewer_link",
]
