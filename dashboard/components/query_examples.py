from __future__ import annotations

from collections import Counter
import json
from typing import Any


EXAMPLE_CASES = [
    {
        "id": "sbwc_buffers",
        "title": "SBWC 사용",
        "description": "SBWC 압축 buffer를 사용하는 scenario/variant를 찾습니다.",
        "scope": {},
        "predicates": [
            {"field": "buffer.compression", "op": "contains", "value": "SBWC"},
            {"field": "topology.uses_buffer", "op": "exists", "value": True},
        ],
    },
    {
        "id": "llc_usage",
        "title": "LLC 사용",
        "description": "Effective topology에서 LLC IP를 사용하는 scenario/variant를 찾습니다.",
        "scope": {},
        "predicates": [
            {"field": "topology.uses_ip", "op": "contains", "value": "llc"},
        ],
    },
    {
        "id": "camera_power_threshold",
        "title": "Camera power 기준 이상",
        "description": "Camera scenario 중 latest evidence total_power_mw가 기준 이상인 variant를 찾습니다. 기본 기준은 100mW입니다.",
        "scope": {},
        "predicates": [
            {"field": "scenario.category", "op": "eq", "value": "camera"},
            {"field": "evidence.latest.kpi.total_power_mw", "op": "gte", "value": "100"},
            {"field": "evidence.latest.feasibility", "op": "exists", "value": True},
        ],
    },
    {
        "id": "camera_npu_usage",
        "title": "Camera NPU 사용",
        "description": "Camera scenario 중 effective topology에서 NPU IP를 사용하는 variant를 찾습니다.",
        "scope": {},
        "predicates": [
            {"field": "scenario.category", "op": "eq", "value": "camera"},
            {"field": "topology.uses_ip", "op": "contains", "value": "npu"},
        ],
    },
    {
        "id": "camera_gpu_usage",
        "title": "Camera GPU 사용",
        "description": "Camera scenario 중 effective topology에서 GPU IP를 사용하는 variant를 찾습니다.",
        "scope": {},
        "predicates": [
            {"field": "scenario.category", "op": "eq", "value": "camera"},
            {"field": "topology.uses_ip", "op": "contains", "value": "gpu"},
        ],
    },
]

_SCOPE_TO_STATE = {
    "soc_ref": "query_soc_ref",
    "project_ref": "query_project_ref",
    "scenario_id": "query_scenario_id",
    "variant_id": "query_variant_id",
}


def apply_example_to_state(state: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Apply an example without clearing user-selected scope filters."""

    updated = dict(state)
    scope = case.get("scope") if isinstance(case.get("scope"), dict) else {}
    for scope_key, state_key in _SCOPE_TO_STATE.items():
        if scope_key in scope:
            updated[state_key] = str(scope.get(scope_key) or "")
    updated["query_predicate_rows"] = [dict(row) for row in case.get("predicates") or []]
    updated["query_predicate_editor_version"] = int(updated.get("query_predicate_editor_version", 0) or 0) + 1
    return updated


def predicate_rows_for_editor(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        value = row.get("value")
        if value is None:
            text_value = ""
        elif isinstance(value, bool):
            text_value = "True" if value else "False"
        else:
            text_value = str(value)
        result.append(
            {
                "field": str(row.get("field") or ""),
                "op": str(row.get("op") or "eq"),
                "value": text_value,
            }
        )
    return result


def active_query_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    for key in _ordered_scope_keys(scope):
        value = scope.get(key)
        if value not in (None, "", []):
            rows.append({"kind": "scope", "field": str(key), "op": "eq", "value": _value_text(value)})

    predicates = payload.get("where") if isinstance(payload.get("where"), list) else []
    for predicate in predicates:
        if not isinstance(predicate, dict):
            continue
        field = str(predicate.get("field") or "")
        if not field:
            continue
        rows.append(
            {
                "kind": "predicate",
                "field": field,
                "op": str(predicate.get("op") or "eq"),
                "value": _value_text(predicate.get("value")),
            }
        )
    groups = payload.get("groups") if isinstance(payload.get("groups"), list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        join = str(group.get("join") or "or").lower()
        for predicate in group.get("where") or []:
            if not isinstance(predicate, dict):
                continue
            field = str(predicate.get("field") or "")
            if not field:
                continue
            rows.append(
                {
                    "kind": f"group:{join}",
                    "field": field,
                    "op": str(predicate.get("op") or "eq"),
                    "value": _value_text(predicate.get("value")),
                }
            )
    return rows


def zero_result_guidance(payload: dict[str, Any]) -> str:
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    predicates = payload.get("where") if isinstance(payload.get("where"), list) else []
    guidance = ["Scope filters and predicate rows are AND conditions."]
    if scope:
        guidance.append("Try widening the sidebar scope, for example All Projects or All Scenarios.")
    if predicates:
        guidance.append("If the scope is correct, remove one predicate at a time and re-run to find the limiting condition.")
    if not scope and not predicates:
        guidance.append("Select a frequent query or add at least one predicate before running again.")
    return " ".join(guidance)


def summarize_query_results(items: list[dict[str, Any]]) -> dict[str, Any]:
    scenario_counts = Counter(str(item.get("scenario_id")) for item in items if item.get("scenario_id"))
    categories = {
        str(category)
        for item in items
        for category in (item.get("category") or [])
        if category not in (None, "")
    }
    top_scenarios = ", ".join(f"{scenario}:{count}" for scenario, count in scenario_counts.most_common(5))
    return {
        "scenario_count": len(scenario_counts),
        "variant_count": len(items),
        "category_count": len(categories),
        "top_scenarios": top_scenarios,
    }


def aggregation_rows(aggregations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket in aggregations:
        key = bucket.get("key") if isinstance(bucket.get("key"), dict) else {}
        row = {str(field): value for field, value in key.items()}
        row["count"] = bucket.get("count", 0)
        metrics = bucket.get("metrics") if isinstance(bucket.get("metrics"), dict) else {}
        for field, values in metrics.items():
            if not isinstance(values, dict):
                continue
            label = _short_field_label(str(field))
            for op, value in values.items():
                row[f"{label}.{op}"] = value
        rows.append(row)
    return rows


def _ordered_scope_keys(scope: dict[str, Any]) -> list[str]:
    priority = ["soc_ref", "project_ref", "scenario_id", "variant_id"]
    return [key for key in priority if key in scope] + sorted(key for key in scope if key not in priority)


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_value_text(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _short_field_label(field: str) -> str:
    for prefix in ("evidence.latest.kpi.", "topology.", "scenario.", "variant.", "buffer.", "axis."):
        if field.startswith(prefix):
            return field.removeprefix(prefix)
    return field
