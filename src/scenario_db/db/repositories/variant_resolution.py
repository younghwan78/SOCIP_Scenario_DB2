from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.db.models.definition import ScenarioVariant


DICT_FIELDS = (
    "design_conditions",
    "design_conditions_override",
    "size_overrides",
    "routing_switch",
    "topology_patch",
    "node_configs",
    "buffer_overrides",
    "ip_requirements",
    "sw_requirements",
    "violation_policy",
)

LIST_FIELDS = ("tags",)

SCALAR_FIELDS = ("severity", "derived_from_variant")


@dataclass(slots=True)
class ResolvedScenarioVariant:
    scenario_id: str
    id: str
    severity: str | None = None
    design_conditions: dict[str, Any] | None = None
    design_conditions_override: dict[str, Any] | None = None
    size_overrides: dict[str, Any] | None = None
    routing_switch: dict[str, Any] | None = None
    topology_patch: dict[str, Any] | None = None
    node_configs: dict[str, Any] | None = None
    buffer_overrides: dict[str, Any] | None = None
    ip_requirements: dict[str, Any] | None = None
    sw_requirements: dict[str, Any] | None = None
    violation_policy: dict[str, Any] | None = None
    tags: list[str] | None = None
    derived_from_variant: str | None = None
    resolved: bool = True
    inheritance_chain: list[str] | None = None


def resolve_variant(db: Session, scenario_id: str, variant_id: str) -> ResolvedScenarioVariant | None:
    rows = {
        row.id: row
        for row in db.query(ScenarioVariant).filter_by(scenario_id=scenario_id).all()
    }
    if variant_id not in rows:
        return None
    return resolve_variant_from_rows(rows, scenario_id, variant_id)


def resolve_variant_from_rows(
    rows: dict[str, ScenarioVariant],
    scenario_id: str,
    variant_id: str,
) -> ResolvedScenarioVariant:
    chain = _inheritance_chain(rows, variant_id)
    merged: dict[str, Any] = {
        "scenario_id": scenario_id,
        "id": variant_id,
        "severity": None,
        "design_conditions": {},
        "design_conditions_override": {},
        "size_overrides": {},
        "routing_switch": {},
        "topology_patch": {},
        "node_configs": {},
        "buffer_overrides": {},
        "ip_requirements": {},
        "sw_requirements": None,
        "violation_policy": None,
        "tags": [],
        "derived_from_variant": rows[variant_id].derived_from_variant,
        "resolved": True,
        "inheritance_chain": chain,
    }

    for row_id in chain:
        row = rows[row_id]
        _merge_row(merged, row)

    merged["id"] = variant_id
    merged["scenario_id"] = scenario_id
    merged["derived_from_variant"] = rows[variant_id].derived_from_variant
    merged["inheritance_chain"] = chain
    return ResolvedScenarioVariant(**merged)


def _inheritance_chain(rows: dict[str, ScenarioVariant], variant_id: str) -> list[str]:
    chain: list[str] = []
    seen: set[str] = set()
    current = variant_id
    while current:
        if current in seen:
            raise ValueError(f"Circular variant inheritance detected: {current}")
        seen.add(current)
        row = rows.get(current)
        if row is None:
            raise LookupError(f"Parent variant not found: {current}")
        chain.append(current)
        current = row.derived_from_variant
    chain.reverse()
    return chain


def _merge_row(merged: dict[str, Any], row: ScenarioVariant) -> None:
    if row.severity:
        merged["severity"] = row.severity

    for field in DICT_FIELDS:
        value = deepcopy(getattr(row, field, None) or {})
        if not value:
            continue
        if field == "topology_patch":
            merged[field] = _merge_patch_dict(merged.get(field) or {}, value)
        elif field == "routing_switch":
            merged[field] = _merge_patch_dict(merged.get(field) or {}, value)
        elif field in {"sw_requirements", "violation_policy"} and merged.get(field) is None:
            merged[field] = value
        elif field in {"sw_requirements", "violation_policy"}:
            merged[field] = _deep_merge_dict(merged[field] or {}, value)
        else:
            merged[field] = _deep_merge_dict(merged.get(field) or {}, value)

    override = getattr(row, "design_conditions_override", None) or {}
    if override:
        merged["design_conditions"] = _deep_merge_dict(merged.get("design_conditions") or {}, deepcopy(override))

    for field in LIST_FIELDS:
        value = deepcopy(getattr(row, field, None) or [])
        merged[field] = _merge_list(merged.get(field) or [], value)


def _deep_merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _merge_patch_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, list):
            result[key] = _merge_list(result.get(key) or [], value)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _merge_list(base: list[Any], overlay: list[Any]) -> list[Any]:
    result = deepcopy(base)
    for item in overlay:
        if item not in result:
            result.append(deepcopy(item))
    return result
