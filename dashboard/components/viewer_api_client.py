from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests


class ViewerApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


RequestFunc = Callable[..., Any]
RETRY_STATUS_CODES = {502, 503, 504}
MAX_ATTEMPTS = 3


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
    return _paged_items(response, "/scenarios")


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
    return _paged_items(response, "/soc-platforms")


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
    return _paged_items(response, "/projects")


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
    return _paged_items(response, f"/scenarios/{scenario_id}/variants")


def list_sw_profiles(
    api_base: str,
    request_func: RequestFunc | None = None,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    response = _request_json(
        "GET",
        api_base,
        "/sw-profiles",
        request_func=request_func,
        params={"limit": limit, "sort_by": "id", "sort_dir": "asc"},
    )
    return _paged_items(response, "/sw-profiles")


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


def compact_scenario_label(item: dict[str, Any]) -> str:
    metadata = _metadata(item)
    name = metadata.get("name")
    if name:
        return _compact_text(str(name), 32)
    return _compact_text(_title_from_id(str(item.get("id") or ""), prefixes=("uc-",)), 32)


def soc_label(item: dict[str, Any]) -> str:
    soc_id = str(item.get("id") or "")
    chips = []
    for key in ("process_node", "memory_type", "bus_protocol"):
        value = item.get(key)
        if value:
            chips.append(str(value))
    return f"{soc_id} | {', '.join(chips)}" if chips else soc_id


def compact_soc_label(item: dict[str, Any]) -> str:
    return _compact_text(_title_from_id(str(item.get("id") or ""), prefixes=("soc-",)), 24)


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


def compact_project_label(item: dict[str, Any]) -> str:
    project_id = str(item.get("id") or "")
    metadata = _metadata(item)
    for key in ("board_type", "board_name", "name"):
        value = metadata.get(key)
        if value:
            return _compact_text(str(value), 28)
    return _compact_text(_title_from_id(project_id, prefixes=("proj-",)), 28)


def variant_label(item: dict[str, Any]) -> str:
    variant_id = str(item.get("id") or "")
    design = item.get("design_conditions") if isinstance(item.get("design_conditions"), dict) else {}
    chips = []
    for key in ("resolution", "fps", "codec", "dynamic_range"):
        value = design.get(key)
        if value is not None:
            chips.append(f"{key}={value}")
    return f"{variant_id} | {', '.join(chips)}" if chips else variant_id


def compact_variant_label(item: dict[str, Any]) -> str:
    return _compact_text(str(item.get("id") or ""), 32)


def sw_profile_label(item: dict[str, Any]) -> str:
    profile_id = str(item.get("id") or "")
    metadata = _metadata(item)
    version = metadata.get("version")
    family = metadata.get("baseline_family")
    release_type = metadata.get("release_type")
    compatible = metadata.get("compatible_soc")
    chips = []
    if version:
        chips.append(f"v{version}")
    if family:
        chips.append(str(family))
    if release_type:
        chips.append(str(release_type))
    if isinstance(compatible, list) and compatible:
        chips.append(",".join(str(item) for item in compatible[:2]))
    return f"{profile_id} | {', '.join(chips)}" if chips else profile_id


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


def _compact_text(value: str, max_len: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1]}…"


def _title_from_id(value: str, *, prefixes: tuple[str, ...] = ()) -> str:
    text = value
    for prefix in prefixes:
        if text.lower().startswith(prefix):
            text = text[len(prefix) :]
            break
    words = [word for word in text.replace("_", "-").split("-") if word]
    return " ".join(_title_word(word) for word in words) or value


def _title_word(word: str) -> str:
    lower = word.lower()
    known = {
        "apv": "APV",
        "cpu": "CPU",
        "dpu": "DPU",
        "fhd": "FHD",
        "gpu": "GPU",
        "hdr": "HDR",
        "mfc": "MFC",
        "npu": "NPU",
        "uhd": "UHD",
        "vdis": "VDIS",
    }
    if lower in known:
        return known[lower]
    if lower.startswith("exynos"):
        return f"Exynos{word[6:]}"
    return word[:1].upper() + word[1:]


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in params.items()
        if value not in (None, "", [])
    }


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
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requester(method, url, timeout=10, **kwargs)
        except requests.RequestException as exc:
            if attempt < MAX_ATTEMPTS - 1:
                _sleep_before_retry(attempt)
                continue
            raise ViewerApiError(f"API request failed: {exc}") from exc

        status_code = getattr(response, "status_code", None)
        if status_code in RETRY_STATUS_CODES and attempt < MAX_ATTEMPTS - 1:
            _sleep_before_retry(attempt)
            continue
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
    raise ViewerApiError("API request failed after retries")


def _sleep_before_retry(attempt: int) -> None:
    time.sleep(0.05 * (2 ** attempt))


def _paged_items(response: dict[str, Any], path: str) -> list[dict[str, Any]]:
    items = response.get("items")
    if not isinstance(items, list):
        raise ViewerApiError(f"API response for {path} must contain list 'items'")
    invalid_indexes = [idx for idx, item in enumerate(items) if not isinstance(item, dict)]
    if invalid_indexes:
        raise ViewerApiError(
            f"API response for {path} contains non-object items at indexes: {invalid_indexes}"
        )
    return items
