from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from dashboard.components.viewer_api_client import RequestFunc, ViewerApiError, _request_json


def get_query_facets(api_base: str, request_func: RequestFunc | None = None) -> dict[str, Any]:
    return _request_json("GET", api_base, "/query/facets", request_func=request_func)


def query_variants(
    api_base: str,
    payload: dict[str, Any],
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json("POST", api_base, "/query/variants", request_func=request_func, json=payload)


def architecture_query_link(query: dict[str, Any]) -> str:
    clean = {key: value for key, value in query.items() if value not in (None, "", [])}
    return f"/Architecture_Query?{urlencode(clean)}" if clean else "/Architecture_Query"


__all__ = ["ViewerApiError", "architecture_query_link", "get_query_facets", "query_variants"]
