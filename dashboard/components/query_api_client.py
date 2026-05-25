from __future__ import annotations

import json
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
    clean = {
        key: _encode_query_value(value)
        for key, value in query.items()
        if value not in (None, "", [])
    }
    return f"/Architecture_Query?{urlencode(clean)}" if clean else "/Architecture_Query"


def decode_query_params(params: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(params)
    for key, expected_type in (("where", list), ("groups", list), ("aggregate", dict)):
        value = decoded.get(key)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, expected_type):
                decoded[key] = parsed
            else:
                decoded.pop(key, None)
    limit = decoded.get("limit")
    if isinstance(limit, str) and limit.strip().isdigit():
        decoded["limit"] = int(limit)
    elif "limit" in decoded:
        decoded.pop("limit")
    return decoded


def _encode_query_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


__all__ = ["ViewerApiError", "architecture_query_link", "decode_query_params", "get_query_facets", "query_variants"]
