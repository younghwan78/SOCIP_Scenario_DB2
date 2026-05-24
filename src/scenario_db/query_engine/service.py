from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.api.schemas.query import QueryFacetsResponse, QueryPredicate, QueryRequest, QueryResponse, QueryResultItem
from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.decision import Issue
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.variant_resolution import ResolvedScenarioVariant, resolve_variant_from_rows
from scenario_db.query_engine.facts import build_variant_facts
from scenario_db.query_engine.field_registry import OPERATORS, field_definitions, is_supported_field


def query_variants(db: Session, request: QueryRequest) -> QueryResponse:
    predicates = _scope_predicates(request.scope) + list(request.where)
    errors = _validate_predicates(predicates)
    if errors:
        return QueryResponse(items=[], total=0, limit=request.limit, offset=request.offset, has_next=False, errors=errors)

    items = _build_items(db)
    filtered = [item for item in items if all(_matches_predicate(item, predicate) for predicate in predicates)]
    sorted_items = _sort_items(filtered, request.sort)
    total = len(sorted_items)
    page = sorted_items[request.offset : request.offset + request.limit]
    return QueryResponse(
        items=page,
        total=total,
        limit=request.limit,
        offset=request.offset,
        has_next=request.offset + request.limit < total,
        errors=[],
    )


def build_facets(db: Session) -> QueryFacetsResponse:
    items = _build_items(db)
    axis_keys: set[str] = set()
    kpi_keys: set[str] = set()
    value_hints: dict[str, set[Any]] = defaultdict(set)
    for item in items:
        for field, values in _facet_values(item).items():
            for value in values:
                if value not in (None, "") and len(value_hints[field]) < 100:
                    value_hints[field].add(value)
        axis_keys.update(str(key) for key in item.design_conditions)
        kpi_keys.update(str(key) for key in item.latest_kpi)

    hints = {field: sorted(values, key=lambda value: str(value).lower()) for field, values in value_hints.items()}
    return QueryFacetsResponse(fields=field_definitions(axis_keys, kpi_keys, hints), operators=OPERATORS)


def _build_items(db: Session) -> list[QueryResultItem]:
    projects = _safe_all(db, Project)
    scenarios = _safe_all(db, Scenario)
    variants = _safe_all(db, ScenarioVariant)
    evidence_rows = _safe_all(db, Evidence)
    issue_rows = _safe_all(db, Issue)
    ip_rows = _safe_all(db, IpCatalog)

    project_by_id = {str(getattr(project, "id", "")): project for project in projects}
    scenarios_by_id = {str(getattr(scenario, "id", "")): scenario for scenario in scenarios}
    variants_by_scenario: dict[str, dict[str, Any]] = defaultdict(dict)
    for variant in variants:
        variants_by_scenario[str(getattr(variant, "scenario_id", ""))][str(getattr(variant, "id", ""))] = variant

    ip_categories = {
        str(getattr(row, "id", "")): str(getattr(row, "category", "") or "")
        for row in ip_rows
        if getattr(row, "id", None)
    }
    latest_evidence = _latest_evidence_by_variant(evidence_rows)

    items: list[QueryResultItem] = []
    for scenario_id, row_map in sorted(variants_by_scenario.items()):
        scenario = scenarios_by_id.get(scenario_id)
        if scenario is None:
            continue
        project = project_by_id.get(str(getattr(scenario, "project_ref", "")))
        if project is None:
            continue
        for variant_id, raw_variant in sorted(row_map.items()):
            variant = _resolved_variant(row_map, scenario_id, variant_id, raw_variant)
            ev = latest_evidence.get((scenario_id, variant_id))
            matched_issue_ids = _matched_issue_ids(issue_rows, scenario, variant)
            items.append(
                build_variant_facts(
                    project=project,
                    scenario=scenario,
                    variant=variant,
                    ip_categories=ip_categories,
                    latest_evidence=ev,
                    matched_issue_ids=matched_issue_ids,
                )
            )
    return items


def _safe_all(db: Session, model: Any) -> list[Any]:
    try:
        rows = db.query(model).all()
    except Exception:
        return []
    return list(rows) if isinstance(rows, list) else []


def _resolved_variant(row_map: dict[str, Any], scenario_id: str, variant_id: str, raw_variant: Any) -> Any:
    try:
        return resolve_variant_from_rows(row_map, scenario_id, variant_id)
    except Exception:
        return ResolvedScenarioVariant(
            scenario_id=scenario_id,
            id=variant_id,
            severity=getattr(raw_variant, "severity", None),
            design_conditions=getattr(raw_variant, "design_conditions", None) or {},
            design_conditions_override=getattr(raw_variant, "design_conditions_override", None) or {},
            size_overrides=getattr(raw_variant, "size_overrides", None) or {},
            routing_switch=getattr(raw_variant, "routing_switch", None) or {},
            topology_patch=getattr(raw_variant, "topology_patch", None) or {},
            node_configs=getattr(raw_variant, "node_configs", None) or {},
            buffer_overrides=getattr(raw_variant, "buffer_overrides", None) or {},
            ip_requirements=getattr(raw_variant, "ip_requirements", None) or {},
            sw_requirements=getattr(raw_variant, "sw_requirements", None),
            violation_policy=getattr(raw_variant, "violation_policy", None),
            tags=getattr(raw_variant, "tags", None) or [],
            derived_from_variant=getattr(raw_variant, "derived_from_variant", None),
            resolved=False,
            inheritance_chain=[variant_id],
        )


def _latest_evidence_by_variant(evidence_rows: list[Any]) -> dict[tuple[str, str], Any]:
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in evidence_rows:
        scenario_id = str(getattr(row, "scenario_ref", "") or "")
        variant_id = str(getattr(row, "variant_ref", "") or "")
        if scenario_id and variant_id:
            grouped[(scenario_id, variant_id)].append(row)
    return {
        key: sorted(rows, key=_evidence_sort_key, reverse=True)[0]
        for key, rows in grouped.items()
        if rows
    }


def _evidence_sort_key(row: Any) -> tuple[str, str]:
    run_info = getattr(row, "run_info", None) or {}
    timestamp = run_info.get("timestamp") if isinstance(run_info, dict) else None
    return str(timestamp or ""), str(getattr(row, "id", "") or "")


def _matched_issue_ids(issue_rows: list[Any], scenario: Any, variant: Any) -> list[str]:
    scenario_id = str(getattr(scenario, "id", "") or "")
    variant_id = str(getattr(variant, "id", "") or "")
    matched: list[str] = []
    for issue in issue_rows:
        affects = getattr(issue, "affects", None) or {}
        if not isinstance(affects, dict):
            continue
        scenario_refs = _as_string_set(affects.get("scenario_ref") or affects.get("scenario_refs") or affects.get("scenario_id") or affects.get("scenario_ids"))
        variant_refs = _as_string_set(affects.get("variant_ref") or affects.get("variant_refs") or affects.get("variant_id") or affects.get("variant_ids"))
        scenario_matches = not scenario_refs or scenario_id in scenario_refs
        variant_matches = not variant_refs or variant_id in variant_refs
        if scenario_matches and variant_matches and getattr(issue, "id", None):
            matched.append(str(getattr(issue, "id")))
    return matched


def _scope_predicates(scope: dict[str, Any] | None) -> list[QueryPredicate]:
    mapping = {
        "project_ref": "project.id",
        "project_id": "project.id",
        "soc_ref": "project.soc_ref",
        "soc_id": "project.soc_ref",
        "board_type": "project.board_type",
        "scenario_id": "scenario.id",
        "variant_id": "variant.id",
        "category": "scenario.category",
        "domain": "scenario.domain",
    }
    predicates: list[QueryPredicate] = []
    for key, value in (scope or {}).items():
        if value in (None, "", []):
            continue
        field = mapping.get(str(key))
        if field:
            predicates.append(QueryPredicate(field=field, op="in" if isinstance(value, list) else "eq", value=value))
    return predicates


def _validate_predicates(predicates: list[QueryPredicate]) -> list[str]:
    errors: list[str] = []
    for predicate in predicates:
        if not is_supported_field(predicate.field):
            errors.append(f"Unsupported query field: {predicate.field}")
    return errors


def _matches_predicate(item: QueryResultItem, predicate: QueryPredicate) -> bool:
    values = _values_for_field(item, predicate.field)
    op = predicate.op
    expected = predicate.value
    if op == "exists":
        exists = any(value not in (None, "", []) for value in values)
        if expected is None:
            return exists
        return exists is _to_bool(expected)
    if op == "eq":
        return _any_equal(values, expected)
    if op == "neq":
        return not _any_equal(values, expected)
    if op == "in":
        expected_values = _expected_values(expected)
        return any(_any_equal(values, value) for value in expected_values)
    if op == "not_in":
        expected_values = _expected_values(expected)
        return not any(_any_equal(values, value) for value in expected_values)
    if op == "contains":
        return _contains(values, expected)
    if op in {"gt", "gte", "lt", "lte"}:
        return _compare(values, expected, op)
    return False


def _values_for_field(item: QueryResultItem, field: str) -> list[Any]:
    if field == "project.id":
        return [item.project_id]
    if field == "project.soc_ref":
        return [item.soc_ref]
    if field == "project.board_type":
        return [item.board_type]
    if field == "scenario.id":
        return [item.scenario_id]
    if field == "scenario.category":
        return list(item.category)
    if field == "scenario.domain":
        return list(item.domain)
    if field == "variant.id":
        return [item.variant_id]
    if field == "variant.severity":
        return [item.severity]
    if field == "variant.tags":
        return list(item.tags)
    if field == "variant.derived":
        return [item.derived]
    if field == "topology.uses_ip":
        return list(item.active_ip_refs)
    if field == "topology.uses_ip_category":
        return list(item.active_ip_categories)
    if field == "topology.edge_type":
        return list(item.edge_types)
    if field == "topology.uses_buffer":
        return list(item.buffer_refs)
    if field == "topology.disabled_node":
        return list(item.disabled_nodes)
    if field == "buffer.compression":
        return list(item.buffer_compressions)
    if field == "buffer.format":
        return list(item.buffer_formats)
    if field == "evidence.latest.sw_version":
        return [item.latest_sw_version]
    if field == "evidence.latest.feasibility":
        return [item.latest_feasibility]
    if field == "issue.matched":
        return [item.matched_issue_count > 0]
    if field == "issue.matched_id":
        return list(item.matched_issue_ids)
    if field.startswith("axis."):
        return [_nested_value(item.design_conditions, field.removeprefix("axis."))]
    if field.startswith("evidence.latest.kpi."):
        return [_nested_value(item.latest_kpi, field.removeprefix("evidence.latest.kpi."))]
    return []


def _facet_values(item: QueryResultItem) -> dict[str, list[Any]]:
    return {
        "project.soc_ref": _values_for_field(item, "project.soc_ref"),
        "project.board_type": _values_for_field(item, "project.board_type"),
        "scenario.category": _values_for_field(item, "scenario.category"),
        "scenario.domain": _values_for_field(item, "scenario.domain"),
        "variant.severity": _values_for_field(item, "variant.severity"),
        "variant.tags": _values_for_field(item, "variant.tags"),
        "topology.uses_ip": _values_for_field(item, "topology.uses_ip"),
        "topology.uses_ip_category": _values_for_field(item, "topology.uses_ip_category"),
        "topology.edge_type": _values_for_field(item, "topology.edge_type"),
        "topology.uses_buffer": _values_for_field(item, "topology.uses_buffer"),
        "topology.disabled_node": _values_for_field(item, "topology.disabled_node"),
        "buffer.compression": _values_for_field(item, "buffer.compression"),
        "buffer.format": _values_for_field(item, "buffer.format"),
        "evidence.latest.sw_version": _values_for_field(item, "evidence.latest.sw_version"),
        "evidence.latest.feasibility": _values_for_field(item, "evidence.latest.feasibility"),
    }


def _nested_value(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _expected_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and "," in value:
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def _any_equal(values: list[Any], expected: Any) -> bool:
    expected_norm = _norm(expected)
    return any(_norm(value) == expected_norm for value in values if value not in (None, ""))


def _contains(values: list[Any], expected: Any) -> bool:
    expected_text = str(expected).lower()
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, (list, tuple, set)):
            if any(_norm(item) == _norm(expected) for item in value):
                return True
        elif expected_text in str(value).lower():
            return True
    return False


def _compare(values: list[Any], expected: Any, op: str) -> bool:
    try:
        expected_number = float(expected)
    except (TypeError, ValueError):
        return False
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if op == "gt" and number > expected_number:
            return True
        if op == "gte" and number >= expected_number:
            return True
        if op == "lt" and number < expected_number:
            return True
        if op == "lte" and number <= expected_number:
            return True
    return False


def _norm(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if value is None:
        return None
    text = str(value).strip()
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text.lower()


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _sort_items(items: list[QueryResultItem], sort_specs: list[dict[str, Any]]) -> list[QueryResultItem]:
    result = list(items)
    for spec in reversed(sort_specs or []):
        field = str(spec.get("field") or "")
        if not is_supported_field(field):
            continue
        reverse = str(spec.get("dir") or "asc").lower() == "desc"
        result.sort(key=lambda item: _sort_key(_values_for_field(item, field)), reverse=reverse)
    return result


def _sort_key(values: list[Any]) -> tuple[int, Any]:
    value = next((item for item in values if item not in (None, "")), None)
    if value is None:
        return (1, "")
    if isinstance(value, (int, float)):
        return (0, value)
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (0, str(value).lower())


def _as_string_set(value: Any) -> set[str]:
    if value in (None, ""):
        return set()
    if isinstance(value, list):
        return {str(item) for item in value if item not in (None, "")}
    return {str(value)}
