from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from itertools import product
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.config import get_settings

from scenario_db.api.schemas.query import (
    QueryAggregationBucket,
    QueryAggregationMetric,
    QueryAggregationSpec,
    QueryFacetsResponse,
    QueryPredicate,
    QueryPredicateGroup,
    QueryRequest,
    QueryResponse,
    QueryResultItem,
)
from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.decision import Issue
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.variant_resolution import resolve_variant_from_rows
from scenario_db.matcher.context import MatcherContext
from scenario_db.matcher.runner import evaluate
from scenario_db.query_engine.facts import build_variant_facts
from scenario_db.query_engine.field_registry import OPERATORS, field_definition, field_definitions, is_supported_field


class QueryValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def query_variants(db: Session, request: QueryRequest) -> QueryResponse:
    predicates = _scope_predicates(request.scope) + list(request.where)
    errors = _validate_request(request, predicates)
    if errors:
        raise QueryValidationError(errors)

    items = _build_items(db, scope=request.scope)
    filtered = [
        item
        for item in items
        if all(_matches_predicate(item, predicate) for predicate in predicates)
        and all(_matches_group(item, group) for group in request.groups)
    ]
    aggregations = _build_aggregations(filtered, request.aggregate)
    sorted_items = _sort_items(filtered, request.sort)
    total = len(sorted_items)
    page = sorted_items[request.offset : request.offset + request.limit]
    return QueryResponse(
        items=page,
        total=total,
        limit=request.limit,
        offset=request.offset,
        has_next=request.offset + request.limit < total,
        aggregations=aggregations,
        errors=[],
    )


# Facets respond from a short-TTL cache (review 4.2): the full-table item
# build only reruns after the TTL or an explicit invalidation on write apply.
# TTL 0 (default) disables caching entirely.
_FACETS_CACHE: dict[str, Any] = {"value": None, "expires_at": 0.0}


def _facets_cache_ttl() -> float:
    try:
        return float(get_settings().query_facets_cache_ttl_seconds)
    except Exception:
        return 0.0


def invalidate_facets_cache() -> None:
    _FACETS_CACHE["value"] = None
    _FACETS_CACHE["expires_at"] = 0.0


def build_facets(db: Session) -> QueryFacetsResponse:
    ttl = _facets_cache_ttl()
    if ttl > 0 and _FACETS_CACHE["value"] is not None and time.monotonic() < _FACETS_CACHE["expires_at"]:
        return _FACETS_CACHE["value"]
    response = _build_facets(db)
    if ttl > 0:
        _FACETS_CACHE["value"] = response
        _FACETS_CACHE["expires_at"] = time.monotonic() + ttl
    return response


def _build_facets(db: Session) -> QueryFacetsResponse:
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


def _build_items(db: Session, scope: dict[str, Any] | None = None) -> list[QueryResultItem]:
    scenarios, projects, variants, evidence_rows = _load_scoped_rows(db, scope)
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
    rows = db.query(model).all()
    return list(rows) if isinstance(rows, list) else []


def _scope_id_values(scope: dict[str, Any] | None, *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = (scope or {}).get(key)
        if value in (None, "", []):
            continue
        items = value if isinstance(value, list) else [value]
        values.extend(str(item) for item in items if item not in (None, ""))
    return values


def _load_scoped_rows(
    db: Session,
    scope: dict[str, Any] | None,
) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    """Load the four variant-item source tables, pre-filtered in SQL when the
    request scope pins scenarios/projects (review 4.2). The Python-side scope
    predicates still run afterwards, so this only narrows the working set."""
    scenario_scope = _scope_id_values(scope, "scenario_id")
    project_scope = _scope_id_values(scope, "project_ref", "project_id")

    if not scenario_scope and not project_scope:
        return (
            _safe_all(db, Scenario),
            _safe_all(db, Project),
            _safe_all(db, ScenarioVariant),
            _safe_all(db, Evidence),
        )

    scenario_query = db.query(Scenario)
    if scenario_scope:
        scenario_query = scenario_query.filter(Scenario.id.in_(scenario_scope))
    if project_scope:
        scenario_query = scenario_query.filter(Scenario.project_ref.in_(project_scope))
    rows = scenario_query.all()
    scenarios = list(rows) if isinstance(rows, list) else []

    scenario_ids = {str(getattr(row, "id", "")) for row in scenarios if getattr(row, "id", None)}
    project_refs = {
        str(getattr(row, "project_ref", ""))
        for row in scenarios
        if getattr(row, "project_ref", None)
    }
    projects = (
        list(db.query(Project).filter(Project.id.in_(project_refs)).all() or [])
        if project_refs
        else []
    )
    variants = (
        list(db.query(ScenarioVariant).filter(ScenarioVariant.scenario_id.in_(scenario_ids)).all() or [])
        if scenario_ids
        else []
    )
    evidence_rows = (
        list(db.query(Evidence).filter(Evidence.scenario_ref.in_(scenario_ids)).all() or [])
        if scenario_ids
        else []
    )
    return scenarios, projects, variants, evidence_rows


def _resolved_variant(row_map: dict[str, Any], scenario_id: str, variant_id: str, raw_variant: Any) -> Any:
    return resolve_variant_from_rows(row_map, scenario_id, variant_id)


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


def _evidence_sort_key(row: Any) -> tuple[int, Any, str]:
    run_info = getattr(row, "run_info", None) or {}
    timestamp = run_info.get("timestamp") if isinstance(run_info, dict) else None
    parsed = _parse_utc_timestamp(timestamp)
    if parsed is not None:
        return 1, parsed.timestamp(), str(getattr(row, "id", "") or "")
    return 0, str(timestamp or ""), str(getattr(row, "id", "") or "")


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _matched_issue_ids(issue_rows: list[Any], scenario: Any, variant: Any) -> list[str]:
    """Match issues against the canonical affects list format.

    Canonical format (same semantics as review_gate._match_issues and the
    /matched-issues endpoint, variant context only):
        affects: [{"scenario_ref": "...", "match_rule": {...}}, ...]
    The legacy dict form ({scenario_ref(s)/variant_ref(s)}) stays supported.
    """
    scenario_id = str(getattr(scenario, "id", "") or "")
    variant_id = str(getattr(variant, "id", "") or "")
    ctx = MatcherContext(
        design_conditions=getattr(variant, "design_conditions", None) or {},
        ip_requirements=getattr(variant, "ip_requirements", None) or {},
        sw_requirements=getattr(variant, "sw_requirements", None) or {},
    )
    matched: list[str] = []
    for issue in issue_rows:
        issue_id = getattr(issue, "id", None)
        if not issue_id:
            continue
        affects = getattr(issue, "affects", None)
        if isinstance(affects, list):
            if _affects_entries_match(affects, scenario_id, ctx):
                matched.append(str(issue_id))
        elif isinstance(affects, dict):
            if _legacy_affects_match(affects, scenario_id, variant_id):
                matched.append(str(issue_id))
    return matched


def _affects_entries_match(affects: list[Any], scenario_id: str, ctx: MatcherContext) -> bool:
    for affect in affects:
        if not isinstance(affect, dict):
            continue
        ref = affect.get("scenario_ref", "*")
        if ref not in (None, "*", scenario_id):
            continue
        match_rule = affect.get("match_rule")
        if not match_rule:
            return True
        if _safe_rule_evaluate(match_rule, ctx):
            return True
    return False


def _safe_rule_evaluate(rule: dict[str, Any], ctx: MatcherContext) -> bool:
    try:
        return evaluate(rule, ctx)
    except (KeyError, TypeError, ValueError):
        return False


def _legacy_affects_match(affects: dict[str, Any], scenario_id: str, variant_id: str) -> bool:
    scenario_refs = _as_string_set(affects.get("scenario_ref") or affects.get("scenario_refs") or affects.get("scenario_id") or affects.get("scenario_ids"))
    variant_refs = _as_string_set(affects.get("variant_ref") or affects.get("variant_refs") or affects.get("variant_id") or affects.get("variant_ids"))
    scenario_matches = not scenario_refs or scenario_id in scenario_refs
    variant_matches = not variant_refs or variant_id in variant_refs
    return scenario_matches and variant_matches


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


def _validate_request(request: QueryRequest, predicates: list[QueryPredicate]) -> list[str]:
    errors = _validate_predicates(predicates)
    for group in request.groups:
        errors.extend(_validate_predicates(list(group.where)))
    aggregate = request.aggregate
    if aggregate is not None:
        for field in aggregate.group_by:
            if not is_supported_field(field):
                errors.append(f"Unsupported aggregate field: {field}")
        for metric in aggregate.metrics:
            if not is_supported_field(metric.field):
                errors.append(f"Unsupported aggregate metric field: {metric.field}")
                continue
            if any(op != "count" for op in metric.ops):
                definition = field_definition(metric.field)
                if definition is None or definition.type != "number":
                    errors.append(
                        "aggregation_field_type_mismatch: "
                        f"{metric.field} is {definition.type if definition else 'unknown'}, "
                        "but min/avg/p50/p95/max require a number field"
                    )
    return errors


def _validate_predicates(predicates: list[QueryPredicate]) -> list[str]:
    errors: list[str] = []
    for predicate in predicates:
        if not is_supported_field(predicate.field):
            errors.append(f"Unsupported query field: {predicate.field}")
    return errors


def _matches_group(item: QueryResultItem, group: QueryPredicateGroup) -> bool:
    predicates = list(group.where)
    if not predicates:
        return True
    if group.join == "or":
        return any(_matches_predicate(item, predicate) for predicate in predicates)
    return all(_matches_predicate(item, predicate) for predicate in predicates)


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


def _build_aggregations(items: list[QueryResultItem], aggregate: QueryAggregationSpec | None) -> list[QueryAggregationBucket]:
    if aggregate is None or not aggregate.group_by:
        return []

    buckets: dict[tuple[Any, ...], list[QueryResultItem]] = defaultdict(list)
    key_values_by_tuple: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        for key_values in _aggregation_key_values(item, aggregate.group_by):
            key_tuple = tuple(key_values[field] for field in aggregate.group_by)
            buckets[key_tuple].append(item)
            key_values_by_tuple[key_tuple] = key_values

    result: list[QueryAggregationBucket] = []
    for key_tuple, bucket_items in buckets.items():
        result.append(
            QueryAggregationBucket(
                key=key_values_by_tuple[key_tuple],
                count=len(bucket_items),
                metrics=_aggregation_metrics(bucket_items, aggregate.metrics),
            )
        )

    result.sort(key=lambda bucket: (-bucket.count, tuple(str(bucket.key.get(field, "")) for field in aggregate.group_by)))
    return result[: aggregate.top_n]


def _aggregation_key_values(item: QueryResultItem, fields: list[str]) -> list[dict[str, Any]]:
    value_lists = [_aggregation_values_for_field(item, field) for field in fields]
    keys: list[dict[str, Any]] = []
    for values in product(*value_lists):
        keys.append({field: value for field, value in zip(fields, values, strict=True)})
    return keys


def _aggregation_values_for_field(item: QueryResultItem, field: str) -> list[Any]:
    values = _unique_values(value for value in _values_for_field(item, field) if value not in (None, "", []))
    return values or [None]


def _aggregation_metrics(items: list[QueryResultItem], metrics: list[QueryAggregationMetric]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        values = _numeric_metric_values(items, metric.field)
        metric_result: dict[str, Any] = {}
        for op in metric.ops:
            if op == "count":
                metric_result["count"] = len(items)
            elif op == "min":
                metric_result["min"] = min(values) if values else None
            elif op == "avg":
                metric_result["avg"] = sum(values) / len(values) if values else None
            elif op == "p50":
                metric_result["p50"] = _percentile(values, 0.50)
            elif op == "p95":
                metric_result["p95"] = _percentile(values, 0.95)
            elif op == "max":
                metric_result["max"] = max(values) if values else None
        result[metric.field] = metric_result
    return result


def _numeric_metric_values(items: list[QueryResultItem], field: str) -> list[float]:
    values: list[float] = []
    for item in items:
        for value in _values_for_field(item, field):
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
    return values


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def _unique_values(values: Any) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = str(_norm(value))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


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


def _sort_key(values: list[Any]) -> tuple[int, float, str]:
    # Rank separates numeric, text, and missing values so mixed-type fields
    # (e.g. axis values 1080 and "4K") never compare float against str.
    value = next((item for item in values if item not in (None, "")), None)
    if value is None:
        return (2, 0.0, "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value).lower())


def _as_string_set(value: Any) -> set[str]:
    if value in (None, ""):
        return set()
    if isinstance(value, list):
        return {str(item) for item in value if item not in (None, "")}
    return {str(value)}
