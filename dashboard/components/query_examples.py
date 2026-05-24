from __future__ import annotations

from collections import Counter
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
