from __future__ import annotations

from copy import deepcopy
from typing import Any

from scenario_db.api.schemas.query import QueryResultItem
from scenario_db.db.repositories.scenario_graph import _effective_pipeline


KEY_AXIS_PRIORITY = ["resolution", "fps", "codec", "hdr", "dynamic_range", "sensor_mode", "format"]


def build_variant_facts(
    *,
    project: Any,
    scenario: Any,
    variant: Any,
    ip_categories: dict[str, str],
    latest_evidence: Any | None = None,
    matched_issue_ids: list[str] | None = None,
) -> QueryResultItem:
    pipeline = getattr(scenario, "pipeline", None) or {}
    nodes, edges = _effective_pipeline(pipeline, variant)
    active_ip_refs = _unique_strings(node.get("ip_ref") for node in nodes if isinstance(node, dict))
    active_ip_categories = _unique_strings(ip_categories.get(ip_ref) for ip_ref in active_ip_refs if ip_categories.get(ip_ref))
    edge_types = _unique_strings(edge.get("type") for edge in edges if isinstance(edge, dict) and edge.get("type"))
    buffer_refs = _unique_strings(edge.get("buffer") for edge in edges if isinstance(edge, dict) and edge.get("buffer"))
    buffers = _effective_buffers(pipeline.get("buffers") if isinstance(pipeline, dict) else {}, getattr(variant, "buffer_overrides", None))

    design = dict(getattr(variant, "design_conditions", None) or {})
    routing = getattr(variant, "routing_switch", None) or {}
    disabled_nodes = _unique_strings(routing.get("disabled_nodes") or [])
    issue_ids = matched_issue_ids or []
    metadata = getattr(scenario, "metadata_", None) or {}

    return QueryResultItem(
        project_id=str(getattr(project, "id", "") or ""),
        soc_ref=_meta(project, "soc_ref"),
        board_type=_meta(project, "board_type"),
        scenario_id=str(getattr(scenario, "id", "") or ""),
        scenario_name=str(metadata.get("name") or getattr(scenario, "id", "") or ""),
        variant_id=str(getattr(variant, "id", "") or ""),
        severity=getattr(variant, "severity", None),
        category=_list_meta(scenario, "category"),
        domain=_list_meta(scenario, "domain"),
        tags=_unique_strings(getattr(variant, "tags", None) or []),
        derived=bool(getattr(variant, "derived_from_variant", None)),
        design_conditions=design,
        key_axes=_key_axes(design),
        active_ip_refs=active_ip_refs,
        active_ip_categories=active_ip_categories,
        edge_types=edge_types,
        buffer_refs=buffer_refs,
        buffer_formats=_buffer_values(buffers, buffer_refs, "format"),
        buffer_compressions=_buffer_values(buffers, buffer_refs, "compression"),
        disabled_nodes=disabled_nodes,
        latest_evidence_id=str(getattr(latest_evidence, "id", "") or "") or None,
        latest_sw_version=_latest_sw_version(latest_evidence),
        latest_feasibility=getattr(latest_evidence, "overall_feasibility", None) if latest_evidence is not None else None,
        latest_kpi=dict(getattr(latest_evidence, "kpi", None) or {}) if latest_evidence is not None else {},
        matched_issue_ids=issue_ids,
        matched_issue_count=len(issue_ids),
        viewer_query=_viewer_query(project, scenario, variant),
    )


def _effective_buffers(buffers: Any, overrides: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if isinstance(buffers, dict):
        for key, value in buffers.items():
            result[str(key)] = deepcopy(value) if isinstance(value, dict) else {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if not isinstance(value, dict):
                continue
            base = result.get(str(key), {})
            result[str(key)] = {**base, **deepcopy(value)}
    return result


def _buffer_values(buffers: dict[str, dict[str, Any]], buffer_refs: list[str], key: str) -> list[str]:
    values = []
    for ref in buffer_refs:
        value = (buffers.get(ref) or {}).get(key)
        if value not in (None, ""):
            values.append(value)
    return _unique_strings(values)


def _key_axes(design: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in KEY_AXIS_PRIORITY:
        if key in design and design[key] not in (None, ""):
            result[key] = design[key]
    for key in sorted(design):
        if key not in result and design[key] not in (None, "") and len(result) < 6:
            result[key] = design[key]
    return result


def _meta(project: Any, key: str) -> str | None:
    value = (getattr(project, "metadata_", None) or {}).get(key)
    return str(value) if value not in (None, "") else None


def _list_meta(scenario: Any, key: str) -> list[str]:
    value = (getattr(scenario, "metadata_", None) or {}).get(key)
    if isinstance(value, list):
        return _unique_strings(value)
    if value not in (None, ""):
        return [str(value)]
    return []


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        if value in (None, ""):
            continue
        text = str(value)
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _latest_sw_version(evidence: Any | None) -> str | None:
    if evidence is None:
        return None
    hint = getattr(evidence, "sw_version_hint", None)
    if hint not in (None, ""):
        return str(hint)
    context = getattr(evidence, "execution_context", None) or {}
    if isinstance(context, dict) and context.get("sw_baseline_ref"):
        return str(context["sw_baseline_ref"])
    baseline = getattr(evidence, "sw_baseline_ref", None)
    return str(baseline) if baseline not in (None, "") else None


def _viewer_query(project: Any, scenario: Any, variant: Any) -> dict[str, str]:
    query = {
        "soc_id": _meta(project, "soc_ref") or "",
        "project_id": str(getattr(project, "id", "") or ""),
        "scenario_id": str(getattr(scenario, "id", "") or ""),
        "variant_id": str(getattr(variant, "id", "") or ""),
    }
    return {key: value for key, value in query.items() if value}
