from __future__ import annotations

import re
from typing import Any

from scenario_db.api.schemas.query import QueryField


OPERATORS = ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "contains", "exists"]

_DYNAMIC_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*$")

_TEXT_OPS = ["eq", "neq", "in", "not_in", "contains", "exists"]
_NUMBER_OPS = ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "exists"]
_BOOL_OPS = ["eq", "neq", "exists"]
_COLLECTION_OPS = ["eq", "neq", "in", "not_in", "contains", "exists"]

_STATIC_FIELDS: dict[str, QueryField] = {
    "project.id": QueryField(field="project.id", label="Project ID", type="string", operators=_TEXT_OPS),
    "project.soc_ref": QueryField(field="project.soc_ref", label="SoC", type="string", operators=_TEXT_OPS),
    "project.board_type": QueryField(field="project.board_type", label="Board Type", type="string", operators=_TEXT_OPS),
    "scenario.id": QueryField(field="scenario.id", label="Scenario ID", type="string", operators=_TEXT_OPS),
    "scenario.category": QueryField(field="scenario.category", label="Scenario Category", type="collection", operators=_COLLECTION_OPS),
    "scenario.domain": QueryField(field="scenario.domain", label="Scenario Domain", type="collection", operators=_COLLECTION_OPS),
    "variant.id": QueryField(field="variant.id", label="Variant ID", type="string", operators=_TEXT_OPS),
    "variant.severity": QueryField(field="variant.severity", label="Variant Severity", type="string", operators=_TEXT_OPS),
    "variant.tags": QueryField(field="variant.tags", label="Variant Tags", type="collection", operators=_COLLECTION_OPS),
    "variant.derived": QueryField(field="variant.derived", label="Derived Variant", type="boolean", operators=_BOOL_OPS),
    "topology.uses_ip": QueryField(field="topology.uses_ip", label="Uses IP", type="collection", operators=_COLLECTION_OPS),
    "topology.uses_ip_category": QueryField(field="topology.uses_ip_category", label="Uses IP Category", type="collection", operators=_COLLECTION_OPS),
    "topology.edge_type": QueryField(field="topology.edge_type", label="Edge Type", type="collection", operators=_COLLECTION_OPS),
    "topology.uses_buffer": QueryField(field="topology.uses_buffer", label="Uses Buffer", type="collection", operators=_COLLECTION_OPS),
    "topology.disabled_node": QueryField(field="topology.disabled_node", label="Disabled Node", type="collection", operators=_COLLECTION_OPS),
    "buffer.compression": QueryField(field="buffer.compression", label="Buffer Compression", type="collection", operators=_COLLECTION_OPS),
    "buffer.format": QueryField(field="buffer.format", label="Buffer Format", type="collection", operators=_COLLECTION_OPS),
    "evidence.latest.sw_version": QueryField(field="evidence.latest.sw_version", label="Latest SW Version", type="string", operators=_TEXT_OPS),
    "evidence.latest.feasibility": QueryField(field="evidence.latest.feasibility", label="Latest Feasibility", type="string", operators=_TEXT_OPS),
    "issue.matched": QueryField(field="issue.matched", label="Has Matched Issue", type="boolean", operators=_BOOL_OPS),
    "issue.matched_id": QueryField(field="issue.matched_id", label="Matched Issue ID", type="collection", operators=_COLLECTION_OPS),
}

_FIELD_ORDER = [
    "project.soc_ref",
    "project.board_type",
    "scenario.id",
    "scenario.category",
    "scenario.domain",
    "variant.id",
    "variant.severity",
    "variant.tags",
    "variant.derived",
    "topology.uses_ip",
    "topology.uses_ip_category",
    "topology.edge_type",
    "topology.uses_buffer",
    "topology.disabled_node",
    "buffer.compression",
    "buffer.format",
    "evidence.latest.sw_version",
    "evidence.latest.feasibility",
    "issue.matched",
    "issue.matched_id",
]


def is_supported_field(field: str) -> bool:
    if field in _STATIC_FIELDS:
        return True
    if field.startswith("axis."):
        return _valid_dynamic_suffix(field.removeprefix("axis."))
    if field.startswith("evidence.latest.kpi."):
        return _valid_dynamic_suffix(field.removeprefix("evidence.latest.kpi."))
    return False


def field_definition(field: str) -> QueryField | None:
    if field in _STATIC_FIELDS:
        return _STATIC_FIELDS[field]
    if field.startswith("axis.") and is_supported_field(field):
        suffix = field.removeprefix("axis.")
        return QueryField(field=field, label=f"Axis: {suffix}", type="string", operators=OPERATORS)
    if field.startswith("evidence.latest.kpi.") and is_supported_field(field):
        suffix = field.removeprefix("evidence.latest.kpi.")
        return QueryField(field=field, label=f"Latest KPI: {suffix}", type="number", operators=_NUMBER_OPS)
    return None


def field_definitions(
    axis_keys: set[str] | None = None,
    kpi_keys: set[str] | None = None,
    value_hints: dict[str, list[Any]] | None = None,
) -> list[QueryField]:
    hints = value_hints or {}
    result = [_with_values(_STATIC_FIELDS[field], hints.get(field)) for field in _FIELD_ORDER]
    for key in _sorted_axis_keys(axis_keys or set()):
        field = f"axis.{key}"
        if not is_supported_field(field):
            continue
        result.append(_with_values(QueryField(field=field, label=f"Axis: {key}", type="string", operators=OPERATORS), hints.get(field)))
    for key in sorted(kpi_keys or set()):
        field = f"evidence.latest.kpi.{key}"
        if not is_supported_field(field):
            continue
        result.append(_with_values(QueryField(field=field, label=f"Latest KPI: {key}", type="number", operators=_NUMBER_OPS), hints.get(field)))
    return result


def _valid_dynamic_suffix(value: str) -> bool:
    return bool(value and _DYNAMIC_KEY_RE.match(value))


def _with_values(field: QueryField, values: list[Any] | None) -> QueryField:
    if not values:
        return field
    data = field.model_dump()
    data["values"] = values
    return QueryField(**data)


def _sorted_axis_keys(keys: set[str]) -> list[str]:
    priority = ["resolution", "fps", "hdr", "dynamic_range", "bit_depth", "codec", "codec_mfc", "sensor_mode", "format", "audio", "gpu", "npu"]
    return [key for key in priority if key in keys] + sorted(key for key in keys if key not in priority)
