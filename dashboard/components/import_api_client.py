from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests


class ImportApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


RequestFunc = Callable[..., Any]


def health_check(api_base: str, request_func: RequestFunc | None = None) -> dict[str, Any]:
    return _request_json("GET", api_base, "/scenarios", request_func=request_func, params={"limit": 1})


def stage_import_bundle(
    api_base: str,
    payload: dict[str, Any],
    request_func: RequestFunc | None = None,
) -> dict[str, Any]:
    return _request_json("POST", api_base, "/write/staging", request_func=request_func, json=payload)


def get_batch(api_base: str, batch_id: str, request_func: RequestFunc | None = None) -> dict[str, Any]:
    return _request_json("GET", api_base, f"/write/staging/{batch_id}", request_func=request_func)


def validate_batch(api_base: str, batch_id: str, request_func: RequestFunc | None = None) -> dict[str, Any]:
    return _request_json("POST", api_base, f"/write/staging/{batch_id}/validate", request_func=request_func)


def diff_batch(api_base: str, batch_id: str, request_func: RequestFunc | None = None) -> dict[str, Any]:
    return _request_json("POST", api_base, f"/write/staging/{batch_id}/diff", request_func=request_func)


def apply_batch(api_base: str, batch_id: str, request_func: RequestFunc | None = None) -> dict[str, Any]:
    return _request_json("POST", api_base, f"/write/staging/{batch_id}/apply", request_func=request_func)


def document_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    documents = ((payload.get("payload") or {}).get("documents") or [])
    rows: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        rows.append(
            {
                "kind": doc.get("kind", ""),
                "id": doc.get("id", ""),
                "name": ((doc.get("metadata") or {}).get("name") if isinstance(doc.get("metadata"), dict) else ""),
                "status": "included",
            }
        )
    return rows


def import_report_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for message in report.get("messages") or []:
        if not isinstance(message, dict):
            continue
        rows.append(
            {
                "level": message.get("level", ""),
                "code": message.get("code", ""),
                "source": message.get("source", ""),
                "message": message.get("message", ""),
            }
        )
    return rows


def validation_issue_rows(validation: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for issue in validation.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        rows.append(
            {
                "severity": issue.get("severity", ""),
                "code": issue.get("code", ""),
                "path": issue.get("path", ""),
                "message": issue.get("message", ""),
            }
        )
    return rows


def diff_change_rows(diff: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for change in diff.get("changes") or []:
        if not isinstance(change, dict):
            continue
        before = change.get("before") if isinstance(change.get("before"), dict) else {}
        after = change.get("after") if isinstance(change.get("after"), dict) else {}
        rows.append(
            {
                "field": change.get("field", ""),
                "change": change.get("change", ""),
                "existing_count": before.get("count", ""),
                "import_count": after.get("count", ""),
                "added": _join_values(after.get("added_ids")),
                "modified": _join_values(after.get("modified_ids")),
                "unchanged": _join_values(after.get("unchanged_ids")),
                "removed": _join_values(after.get("removed_ids")),
            }
        )
    return rows


def scenario_impact_rows(diff: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    impact = diff.get("impact") or {}
    for scenario in impact.get("scenario_impacts") or []:
        if not isinstance(scenario, dict):
            continue
        rows.append(
            {
                "scenario_id": scenario.get("scenario_id", ""),
                "operation": scenario.get("operation", ""),
                "variants_before": scenario.get("variant_count_before", 0),
                "variants_after": scenario.get("variant_count_after", 0),
                "variants_added": ", ".join(scenario.get("variants_added") or []),
                "variants_removed": ", ".join(scenario.get("variants_removed") or []),
                "variants_updated": ", ".join(scenario.get("variants_updated") or []),
            }
        )
    return rows


def _join_values(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, list):
        return ", ".join(str(value) for value in values)
    return str(values)


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
        raise ImportApiError(f"API request failed: {exc}") from exc

    status_code = getattr(response, "status_code", None)
    if status_code is not None and status_code >= 400:
        body = getattr(response, "text", "")
        raise ImportApiError(
            f"API returned HTTP {status_code}",
            status_code=status_code,
            body=body,
        )
    try:
        result = response.json()
    except ValueError as exc:
        body = getattr(response, "text", "")
        raise ImportApiError("API response was not JSON", status_code=status_code, body=body) from exc
    if not isinstance(result, dict):
        raise ImportApiError("API response JSON root was not an object", status_code=status_code)
    return result
