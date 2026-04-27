from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from scenario_db.api.schemas.write import (
    ApplyWriteResponse,
    DiffEntry,
    DiffPreviewResponse,
    StageWriteRequest,
    StageWriteResponse,
    ValidateWriteResponse,
    ValidationIssue,
)
from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.models.write import WriteBatch, WriteEvent

SUPPORTED_KIND = "scenario.variant_overlay"

VARIANT_FIELDS = [
    "severity",
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
    "tags",
    "derived_from_variant",
]

DICT_FIELDS = {
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
}


def stage_write(db: Session, request: StageWriteRequest) -> StageWriteResponse:
    if request.kind != SUPPORTED_KIND:
        raise HTTPException(status_code=400, detail=f"Unsupported write kind: {request.kind}")

    normalized = normalize_payload(request.payload)
    batch = WriteBatch(
        id=str(uuid4()),
        kind=request.kind,
        target_id=_target_id(normalized),
        status="staged",
        actor=request.actor,
        note=request.note,
        raw_payload=request.payload,
        normalized_payload=normalized,
    )
    db.add(batch)
    _record_event(db, batch.id, "stage", request.actor, {"status": "staged"})
    db.commit()
    return StageWriteResponse(batch_id=batch.id, status=batch.status, target_id=batch.target_id)


def get_batch_or_404(db: Session, batch_id: str) -> WriteBatch:
    batch = db.query(WriteBatch).filter_by(id=batch_id).one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail=f"Write batch not found: {batch_id}")
    return batch


def validate_batch(db: Session, batch_id: str) -> ValidateWriteResponse:
    batch = get_batch_or_404(db, batch_id)
    normalized = normalize_payload(batch.raw_payload)
    issues = validate_variant_overlay(db, normalized)
    valid = not any(issue.severity == "error" for issue in issues)
    result = {
        "valid": valid,
        "issues": [issue.model_dump() for issue in issues],
    }
    batch.normalized_payload = normalized
    batch.validation_result = result
    batch.status = "validated" if valid else "validation_failed"
    _touch(batch)
    _record_event(db, batch.id, "validate", batch.actor, result)
    db.commit()
    return ValidateWriteResponse(
        batch_id=batch.id,
        valid=valid,
        issues=issues,
        normalized_payload=normalized,
    )


def diff_batch(db: Session, batch_id: str) -> DiffPreviewResponse:
    batch = get_batch_or_404(db, batch_id)
    normalized = batch.normalized_payload or normalize_payload(batch.raw_payload)
    validation = batch.validation_result or validate_batch(db, batch_id).model_dump()
    if not validation.get("valid"):
        raise HTTPException(status_code=409, detail="Cannot diff an invalid write batch")

    diff = build_diff(db, normalized)
    diff.batch_id = batch.id
    batch.diff_result = diff.model_dump()
    batch.status = "diff_ready"
    _touch(batch)
    _record_event(db, batch.id, "diff", batch.actor, batch.diff_result)
    db.commit()
    return diff


def apply_batch(db: Session, batch_id: str) -> ApplyWriteResponse:
    batch = get_batch_or_404(db, batch_id)
    normalized = batch.normalized_payload or normalize_payload(batch.raw_payload)
    validation = batch.validation_result or validate_batch(db, batch_id).model_dump()
    if not validation.get("valid"):
        raise HTTPException(status_code=409, detail="Cannot apply an invalid write batch")

    scenario_ref = normalized["scenario_ref"]
    variant = normalized["variant"]
    row = (
        db.query(ScenarioVariant)
        .filter_by(scenario_id=scenario_ref, id=variant["id"])
        .one_or_none()
    )
    operation = "update" if row is not None else "create"
    if row is None:
        row = ScenarioVariant(scenario_id=scenario_ref, id=variant["id"])

    _apply_variant_fields(row, variant)
    db.add(row)
    db.flush()

    applied_refs = {
        "scenario_ref": scenario_ref,
        "variant_ref": variant["id"],
        "operation": operation,
    }
    batch.applied_refs = applied_refs
    batch.status = "applied"
    _touch(batch)
    _record_event(db, batch.id, "apply", batch.actor, applied_refs)
    db.commit()
    return ApplyWriteResponse(batch_id=batch.id, status=batch.status, applied_refs=applied_refs)


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    scenario_ref = payload.get("scenario_ref") or payload.get("scenario_id")
    variant = payload.get("variant")
    if not isinstance(scenario_ref, str) or not scenario_ref:
        raise HTTPException(status_code=400, detail="payload.scenario_ref is required")
    if not isinstance(variant, dict):
        raise HTTPException(status_code=400, detail="payload.variant must be an object")
    if not isinstance(variant.get("id"), str) or not variant["id"]:
        raise HTTPException(status_code=400, detail="payload.variant.id is required")

    normalized_variant: dict[str, Any] = {"id": variant["id"]}
    for field in VARIANT_FIELDS:
        value = deepcopy(variant.get(field))
        if field in DICT_FIELDS:
            value = value or {}
        elif field == "tags":
            value = value or []
        normalized_variant[field] = value
    return {"scenario_ref": scenario_ref, "variant": normalized_variant}


def validate_variant_overlay(db: Session, normalized: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    scenario_ref = normalized["scenario_ref"]
    variant = normalized["variant"]
    scenario = db.query(Scenario).filter_by(id=scenario_ref).one_or_none()
    if scenario is None:
        return [
            _issue("error", "scenario_not_found", f"Scenario not found: {scenario_ref}", "payload.scenario_ref")
        ]

    base_nodes = _base_nodes(scenario)
    base_edges = _base_edges(scenario)
    base_node_ids = set(base_nodes)
    buffer_ids = set(((scenario.pipeline or {}).get("buffers") or {}).keys())

    parent = variant.get("derived_from_variant")
    if parent and parent not in _variant_ids(db, scenario_ref):
        issues.append(
            _issue(
                "error",
                "derived_variant_not_found",
                f"derived_from_variant does not exist: {parent}",
                "payload.variant.derived_from_variant",
            )
        )

    issues.extend(_validate_routing_switch(variant.get("routing_switch") or {}, base_node_ids, base_edges))
    injected_nodes, patch_issues = _validate_topology_patch(variant.get("topology_patch") or {}, base_edges)
    issues.extend(patch_issues)
    known_config_nodes = base_node_ids | injected_nodes
    issues.extend(_validate_node_configs(db, variant.get("node_configs") or {}, base_nodes, known_config_nodes))
    issues.extend(_validate_buffer_overrides(variant.get("buffer_overrides") or {}, buffer_ids))
    return issues


def build_diff(db: Session, normalized: dict[str, Any]) -> DiffPreviewResponse:
    scenario_ref = normalized["scenario_ref"]
    variant = normalized["variant"]
    existing = (
        db.query(ScenarioVariant)
        .filter_by(scenario_id=scenario_ref, id=variant["id"])
        .one_or_none()
    )
    operation = "create" if existing is None else "update"
    changes: list[DiffEntry] = []
    for field in VARIANT_FIELDS:
        before = getattr(existing, field, None) if existing is not None else None
        after = variant.get(field)
        if before == after:
            change = "unchanged"
        elif before is None and after not in (None, {}, []):
            change = "add"
        elif after in (None, {}, []) and before not in (None, {}, []):
            change = "remove"
        else:
            change = "modify"
        changes.append(DiffEntry(field=field, change=change, before=before, after=after))
    return DiffPreviewResponse(
        batch_id="",
        target_id=_target_id(normalized),
        operation=operation,
        changes=changes,
    )


def _apply_variant_fields(row: ScenarioVariant, variant: dict[str, Any]) -> None:
    row.severity = variant.get("severity")
    row.design_conditions = variant.get("design_conditions") or {}
    row.design_conditions_override = variant.get("design_conditions_override") or {}
    row.size_overrides = variant.get("size_overrides") or {}
    row.routing_switch = variant.get("routing_switch") or {}
    row.topology_patch = variant.get("topology_patch") or {}
    row.node_configs = variant.get("node_configs") or {}
    row.buffer_overrides = variant.get("buffer_overrides") or {}
    row.ip_requirements = variant.get("ip_requirements") or {}
    row.sw_requirements = variant.get("sw_requirements") or None
    row.violation_policy = variant.get("violation_policy") or None
    row.tags = variant.get("tags") or []
    row.derived_from_variant = variant.get("derived_from_variant")


def _validate_routing_switch(
    routing_switch: dict[str, Any],
    base_node_ids: set[str],
    base_edges: set[tuple[str | None, str | None, str | None]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for node_id in routing_switch.get("disabled_nodes") or []:
        if node_id not in base_node_ids:
            issues.append(_issue("error", "unknown_disabled_node", f"Unknown disabled node: {node_id}", "routing_switch.disabled_nodes"))
    for edge in routing_switch.get("disabled_edges") or []:
        if not _edge_exists(edge, base_edges):
            issues.append(_issue("error", "unknown_disabled_edge", f"Unknown disabled edge: {edge}", "routing_switch.disabled_edges"))
    return issues


def _validate_topology_patch(
    topology_patch: dict[str, Any],
    base_edges: set[tuple[str | None, str | None, str | None]],
) -> tuple[set[str], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    injected_nodes: set[str] = set()
    for edge in topology_patch.get("remove_edges") or []:
        if not _edge_exists(edge, base_edges):
            issues.append(_issue("error", "unknown_removed_edge", f"Unknown removed edge: {edge}", "topology_patch.remove_edges"))

    for node in topology_patch.get("add_nodes") or []:
        node_id = node.get("id") if isinstance(node, dict) else None
        if not node_id:
            issues.append(_issue("error", "added_node_missing_id", "Added node must have id", "topology_patch.add_nodes"))
            continue
        if not _is_sw_node(node):
            issues.append(
                _issue(
                    "error",
                    "hw_node_injection_forbidden",
                    f"Only SW task injection is allowed in topology_patch.add_nodes: {node_id}",
                    "topology_patch.add_nodes",
                )
            )
        injected_nodes.add(str(node_id))

    for edge in topology_patch.get("add_edges") or []:
        if not isinstance(edge, dict):
            issues.append(_issue("error", "added_edge_invalid", "Added edge must be an object", "topology_patch.add_edges"))
            continue
        source = edge.get("from") or edge.get("source")
        target = edge.get("to") or edge.get("target")
        if not source or not target:
            issues.append(_issue("error", "added_edge_missing_endpoint", "Added edge must have from/to", "topology_patch.add_edges"))
            continue
        if source not in injected_nodes and target not in injected_nodes:
            issues.append(
                _issue(
                    "error",
                    "hw_edge_injection_forbidden",
                    f"Added edge must touch an injected SW task: {source}->{target}",
                    "topology_patch.add_edges",
                )
            )
        edge_type = str(edge.get("type") or "M2M")
        if edge_type in {"OTF", "vOTF"}:
            issues.append(
                _issue(
                    "error",
                    "sw_patch_edge_type_invalid",
                    f"SW topology patch cannot add {edge_type} edge: {source}->{target}",
                    "topology_patch.add_edges",
                )
            )
    return injected_nodes, issues


def _validate_node_configs(
    db: Session,
    node_configs: dict[str, Any],
    base_nodes: dict[str, dict[str, Any]],
    known_config_nodes: set[str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for node_id, config in node_configs.items():
        if node_id not in known_config_nodes:
            issues.append(_issue("error", "unknown_node_config", f"Unknown node config target: {node_id}", f"node_configs.{node_id}"))
            continue
        if not isinstance(config, dict):
            issues.append(_issue("error", "node_config_invalid", f"Node config must be an object: {node_id}", f"node_configs.{node_id}"))
            continue
        selected_mode = config.get("selected_mode")
        if selected_mode is None:
            continue
        ip_ref = base_nodes.get(node_id, {}).get("ip_ref")
        if not ip_ref:
            issues.append(_issue("error", "selected_mode_without_ip", f"selected_mode requires a base IP node: {node_id}", f"node_configs.{node_id}.selected_mode"))
            continue
        modes = _operating_mode_ids(db, ip_ref)
        if selected_mode not in modes:
            issues.append(
                _issue(
                    "error",
                    "unsupported_selected_mode",
                    f"Mode '{selected_mode}' is not supported by {ip_ref}. Supported: {sorted(modes)}",
                    f"node_configs.{node_id}.selected_mode",
                )
            )
    return issues


def _validate_buffer_overrides(buffer_overrides: dict[str, Any], buffer_ids: set[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for buffer_id, override in buffer_overrides.items():
        if buffer_id not in buffer_ids:
            issues.append(_issue("error", "unknown_buffer_override", f"Unknown buffer override target: {buffer_id}", f"buffer_overrides.{buffer_id}"))
        if isinstance(override, dict):
            placement = override.get("placement") or {}
            if "compression" in placement:
                issues.append(
                    _issue(
                        "error",
                        "compression_in_placement",
                        "Compression belongs to buffer descriptor, not placement",
                        f"buffer_overrides.{buffer_id}.placement.compression",
                    )
                )
    return issues


def _base_nodes(scenario: Scenario) -> dict[str, dict[str, Any]]:
    nodes = (scenario.pipeline or {}).get("nodes") or []
    return {node.get("id"): node for node in nodes if node.get("id")}


def _base_edges(scenario: Scenario) -> set[tuple[str | None, str | None, str | None]]:
    edges = (scenario.pipeline or {}).get("edges") or []
    return {
        (edge.get("id"), edge.get("from") or edge.get("source"), edge.get("to") or edge.get("target"))
        for edge in edges
    }


def _variant_ids(db: Session, scenario_ref: str) -> set[str]:
    return {
        row[0]
        for row in db.query(ScenarioVariant.id).filter_by(scenario_id=scenario_ref).all()
    }


def _edge_exists(edge: Any, base_edges: set[tuple[str | None, str | None, str | None]]) -> bool:
    if not isinstance(edge, dict):
        return False
    edge_id = edge.get("id")
    source = edge.get("from") or edge.get("source")
    target = edge.get("to") or edge.get("target")
    for base_id, base_source, base_target in base_edges:
        if edge_id and edge_id == base_id:
            return True
        if source == base_source and target == base_target:
            return True
    return False


def _is_sw_node(node: dict[str, Any]) -> bool:
    text = f"{node.get('node_type', '')} {node.get('layer', '')} {node.get('kind', '')}".lower()
    return any(token in text.split() for token in {"sw", "app", "framework", "hal", "kernel", "task", "cpu"})


def _operating_mode_ids(db: Session, ip_ref: str) -> set[str]:
    ip = db.query(IpCatalog).filter_by(id=ip_ref).one_or_none()
    modes = (((ip.capabilities if ip else {}) or {}).get("operating_modes") or [])
    return {str(mode.get("id")) for mode in modes if isinstance(mode, dict) and mode.get("id")}


def _target_id(normalized: dict[str, Any]) -> str:
    return f"{normalized['scenario_ref']}/{normalized['variant']['id']}"


def _record_event(db: Session, batch_id: str, action: str, actor: str | None, result: dict[str, Any]) -> None:
    db.add(
        WriteEvent(
            id=str(uuid4()),
            batch_id=batch_id,
            action=action,
            actor=actor,
            result=result,
        )
    )


def _issue(severity: str, code: str, message: str, path: str | None = None) -> ValidationIssue:
    return ValidationIssue(severity=severity, code=code, message=message, path=path)


def _touch(batch: WriteBatch) -> None:
    batch.updated_at = datetime.now(timezone.utc)
