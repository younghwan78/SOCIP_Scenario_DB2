from __future__ import annotations

import hashlib
import json
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
from scenario_db.db.models.capability import IpCatalog, SocPlatform
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.write import WriteBatch, WriteEvent
from scenario_db.etl.mappers.capability import upsert_ip, upsert_soc
from scenario_db.etl.mappers.definition import upsert_project, upsert_usecase
from scenario_db.models.capability.hw import IpCatalog as PydanticIpCatalog
from scenario_db.models.capability.hw import SocPlatform as PydanticSocPlatform
from scenario_db.models.definition.project import Project as PydanticProject
from scenario_db.models.definition.usecase import Usecase as PydanticUsecase

VARIANT_OVERLAY_KIND = "scenario.variant_overlay"
PIPELINE_PATCH_KIND = "scenario.pipeline_patch"
IMPORT_BUNDLE_KIND = "scenario.import_bundle"
SUPPORTED_KINDS = {VARIANT_OVERLAY_KIND, PIPELINE_PATCH_KIND, IMPORT_BUNDLE_KIND}

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

PATCH_LIST_FIELDS = {
    "add_nodes",
    "update_nodes",
    "remove_nodes",
    "add_edges",
    "remove_edges",
    "remove_buffers",
}
ALLOWED_BASE_EDGE_TYPES = {"OTF", "vOTF", "M2M"}
IMPORT_KIND_ORDER = ["soc", "ip", "project", "scenario.usecase"]
IMPORT_MODEL_BY_KIND = {
    "soc": PydanticSocPlatform,
    "ip": PydanticIpCatalog,
    "project": PydanticProject,
    "scenario.usecase": PydanticUsecase,
}
IMPORT_UPSERT_BY_KIND = {
    "soc": upsert_soc,
    "ip": upsert_ip,
    "project": upsert_project,
    "scenario.usecase": upsert_usecase,
}
IMPORT_DB_MODEL_BY_KIND = {
    "soc": SocPlatform,
    "ip": IpCatalog,
    "project": Project,
    "scenario.usecase": Scenario,
}


def stage_write(db: Session, request: StageWriteRequest) -> StageWriteResponse:
    if request.kind not in SUPPORTED_KINDS:
        raise HTTPException(status_code=400, detail=f"Unsupported write kind: {request.kind}")

    normalized = normalize_write_payload(request.kind, request.payload)
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
    normalized = normalize_write_payload(batch.kind, batch.raw_payload)
    issues = validate_write_payload(db, batch.kind, normalized)
    valid = not any(issue.severity == "error" for issue in issues)
    result = {
        "valid": valid,
        "issues": [issue.model_dump() for issue in issues],
    }
    if batch.kind == IMPORT_BUNDLE_KIND:
        result["import_report"] = _import_report_summary(normalized.get("import_report") or {})
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
        import_report=result.get("import_report"),
    )


def diff_batch(db: Session, batch_id: str) -> DiffPreviewResponse:
    batch = get_batch_or_404(db, batch_id)
    normalized = batch.normalized_payload or normalize_write_payload(batch.kind, batch.raw_payload)
    validation = batch.validation_result or validate_batch(db, batch_id).model_dump()
    if not validation.get("valid"):
        raise HTTPException(status_code=409, detail="Cannot diff an invalid write batch")

    diff = build_write_diff(db, batch.kind, normalized)
    diff.batch_id = batch.id
    batch.diff_result = diff.model_dump()
    batch.status = "diff_ready"
    _touch(batch)
    _record_event(db, batch.id, "diff", batch.actor, batch.diff_result)
    db.commit()
    return diff


def apply_batch(db: Session, batch_id: str) -> ApplyWriteResponse:
    batch = get_batch_or_404(db, batch_id)
    normalized = batch.normalized_payload or normalize_write_payload(batch.kind, batch.raw_payload)
    validation = batch.validation_result or validate_batch(db, batch_id).model_dump()
    if not validation.get("valid"):
        raise HTTPException(status_code=409, detail="Cannot apply an invalid write batch")

    if batch.kind == VARIANT_OVERLAY_KIND:
        applied_refs = _apply_variant_overlay(db, normalized)
    elif batch.kind == PIPELINE_PATCH_KIND:
        applied_refs = _apply_pipeline_patch(db, normalized)
    elif batch.kind == IMPORT_BUNDLE_KIND:
        applied_refs = _apply_import_bundle(db, normalized)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported write kind: {batch.kind}")

    batch.applied_refs = applied_refs
    batch.status = "applied"
    _touch(batch)
    _record_event(db, batch.id, "apply", batch.actor, applied_refs)
    db.commit()
    return ApplyWriteResponse(batch_id=batch.id, status=batch.status, applied_refs=applied_refs)


def normalize_write_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == VARIANT_OVERLAY_KIND:
        return normalize_payload(payload)
    if kind == PIPELINE_PATCH_KIND:
        return normalize_pipeline_patch_payload(payload)
    if kind == IMPORT_BUNDLE_KIND:
        return normalize_import_bundle_payload(payload)
    raise HTTPException(status_code=400, detail=f"Unsupported write kind: {kind}")


def validate_write_payload(db: Session, kind: str, normalized: dict[str, Any]) -> list[ValidationIssue]:
    if kind == VARIANT_OVERLAY_KIND:
        return validate_variant_overlay(db, normalized)
    if kind == PIPELINE_PATCH_KIND:
        return validate_pipeline_patch(db, normalized)
    if kind == IMPORT_BUNDLE_KIND:
        return validate_import_bundle(db, normalized)
    return [_issue("error", "unsupported_write_kind", f"Unsupported write kind: {kind}", "kind")]


def build_write_diff(db: Session, kind: str, normalized: dict[str, Any]) -> DiffPreviewResponse:
    if kind == VARIANT_OVERLAY_KIND:
        return build_diff(db, normalized)
    if kind == PIPELINE_PATCH_KIND:
        return build_pipeline_patch_diff(db, normalized)
    if kind == IMPORT_BUNDLE_KIND:
        return build_import_bundle_diff(db, normalized)
    raise HTTPException(status_code=400, detail=f"Unsupported write kind: {kind}")


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible normalizer for scenario.variant_overlay tests."""
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


def normalize_pipeline_patch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    scenario_ref = payload.get("scenario_ref") or payload.get("scenario_id")
    patch = payload.get("patch") or payload.get("pipeline_patch")
    if not isinstance(scenario_ref, str) or not scenario_ref:
        raise HTTPException(status_code=400, detail="payload.scenario_ref is required")
    if not isinstance(patch, dict):
        raise HTTPException(status_code=400, detail="payload.patch must be an object")

    normalized_patch: dict[str, Any] = {}
    for field in PATCH_LIST_FIELDS:
        value = deepcopy(patch.get(field) or [])
        if not isinstance(value, list):
            raise HTTPException(status_code=400, detail=f"payload.patch.{field} must be a list")
        normalized_patch[field] = value

    upsert_buffers = deepcopy(patch.get("upsert_buffers") or patch.get("add_buffers") or {})
    if not isinstance(upsert_buffers, dict):
        raise HTTPException(status_code=400, detail="payload.patch.upsert_buffers must be an object")
    normalized_patch["upsert_buffers"] = upsert_buffers
    normalized_patch["add_edges"] = [_normalize_edge(edge) for edge in normalized_patch["add_edges"]]
    normalized_patch["remove_edges"] = [_normalize_edge(edge) for edge in normalized_patch["remove_edges"]]
    normalized_patch["remove_nodes"] = [_normalize_ref(item) for item in normalized_patch["remove_nodes"]]
    normalized_patch["remove_buffers"] = [_normalize_ref(item) for item in normalized_patch["remove_buffers"]]
    return {"scenario_ref": scenario_ref, "patch": normalized_patch}


def normalize_import_bundle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    documents = (
        payload.get("documents")
        or payload.get("canonical_documents")
        or payload.get("generated_documents")
        or payload.get("usecases")
        or []
    )
    if payload.get("document"):
        documents = [payload["document"], *list(documents or [])]
    if not isinstance(documents, list):
        raise HTTPException(status_code=400, detail="payload.documents must be a list")
    if not documents:
        raise HTTPException(status_code=400, detail="payload.documents must not be empty")

    normalized_docs: list[dict[str, Any]] = []
    for idx, doc in enumerate(documents):
        if not isinstance(doc, dict):
            raise HTTPException(status_code=400, detail=f"payload.documents[{idx}] must be an object")
        normalized_docs.append(deepcopy(doc))
    import_report = deepcopy(payload.get("import_report") or {})
    if import_report and not isinstance(import_report, dict):
        raise HTTPException(status_code=400, detail="payload.import_report must be an object")
    return {
        "documents": normalized_docs,
        "import_report": import_report,
        "options": deepcopy(payload.get("options") or {}),
    }


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


def validate_pipeline_patch(db: Session, normalized: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    scenario_ref = normalized["scenario_ref"]
    patch = normalized["patch"]
    scenario = db.query(Scenario).filter_by(id=scenario_ref).one_or_none()
    if scenario is None:
        return [_issue("error", "scenario_not_found", f"Scenario not found: {scenario_ref}", "payload.scenario_ref")]

    pipeline = scenario.pipeline or {}
    base_nodes = _base_nodes(scenario)
    base_edges = _base_edges(scenario)
    base_buffers = set((pipeline.get("buffers") or {}).keys())

    issues.extend(_validate_pipeline_patch_node_ops(db, patch, base_nodes))
    issues.extend(_validate_pipeline_patch_edge_removes(patch, base_edges))
    issues.extend(_validate_pipeline_patch_buffer_removes(patch, base_buffers, pipeline.get("edges") or []))

    if any(issue.severity == "error" for issue in issues):
        return issues

    candidate = _patched_pipeline(pipeline, patch)
    issues.extend(_validate_candidate_pipeline(db, candidate))
    impact = _pipeline_patch_impact(db, scenario_ref, candidate)
    for variant in impact["affected_variants"]:
        for error in variant.get("errors") or []:
            issues.append(_issue("error", "variant_overlay_impact", f"{variant['variant_id']}: {error}", "payload.patch"))
    return issues


def validate_import_bundle(db: Session, normalized: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    docs = normalized["documents"]
    included = _included_import_refs(docs)
    seen: set[tuple[str, str]] = set()

    for idx, doc in enumerate(docs):
        kind = doc.get("kind")
        doc_id = doc.get("id")
        path = f"documents[{idx}]"
        if not isinstance(kind, str) or not isinstance(doc_id, str):
            issues.append(_issue("error", "import_document_missing_identity", "Import document requires string id and kind", path))
            continue
        if kind not in IMPORT_MODEL_BY_KIND:
            issues.append(_issue("error", "import_document_kind_unsupported", f"Unsupported import document kind: {kind}", f"{path}.kind"))
            continue
        key = (kind, doc_id)
        if key in seen:
            issues.append(_issue("error", "import_document_duplicate", f"Duplicate import document: {kind}/{doc_id}", path))
        seen.add(key)
        try:
            IMPORT_MODEL_BY_KIND[kind].model_validate(doc)
        except Exception as exc:
            issues.append(_issue("error", "import_document_schema_invalid", str(exc), path))
            continue
        if kind == "scenario.usecase":
            issues.extend(_validate_import_usecase_refs(db, doc, included, path))

    report = normalized.get("import_report") or {}
    if report and report.get("ok") is False:
        issues.append(_issue("warning", "import_report_not_ok", "Import report has ok=false; review before apply", "import_report.ok"))
    for message in report.get("messages") or []:
        if isinstance(message, dict) and message.get("level") == "error":
            issues.append(
                _issue(
                    "error",
                    "import_report_error",
                    str(message.get("message") or message.get("code") or "import report error"),
                    "import_report.messages",
                )
            )
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


def build_pipeline_patch_diff(db: Session, normalized: dict[str, Any]) -> DiffPreviewResponse:
    scenario_ref = normalized["scenario_ref"]
    scenario = db.query(Scenario).filter_by(id=scenario_ref).one_or_none()
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {scenario_ref}")

    before = scenario.pipeline or {}
    after = _patched_pipeline(before, normalized["patch"])
    changes = [
        _pipeline_count_diff("pipeline.nodes", before.get("nodes") or [], after.get("nodes") or []),
        _pipeline_count_diff("pipeline.edges", before.get("edges") or [], after.get("edges") or []),
        _pipeline_count_diff("pipeline.buffers", before.get("buffers") or {}, after.get("buffers") or {}),
    ]
    return DiffPreviewResponse(
        batch_id="",
        target_id=scenario_ref,
        operation="update",
        changes=changes,
        impact=_pipeline_patch_impact(db, scenario_ref, after),
    )


def build_import_bundle_diff(db: Session, normalized: dict[str, Any]) -> DiffPreviewResponse:
    docs = normalized["documents"]
    changes: list[DiffEntry] = []
    existing_any = False
    for kind in IMPORT_KIND_ORDER:
        kind_docs = [doc for doc in docs if doc.get("kind") == kind]
        if not kind_docs:
            continue
        ids = [str(doc["id"]) for doc in kind_docs]
        existing_ids = _existing_import_doc_ids(db, kind, ids)
        existing_any = existing_any or bool(existing_ids)
        if not existing_ids:
            change = "add"
        elif len(existing_ids) == len(ids):
            change = "modify"
        else:
            change = "modify"
        changes.append(
            DiffEntry(
                field=f"documents.{kind}",
                change=change,
                before={"existing_ids": sorted(existing_ids), "count": len(existing_ids)},
                after={"ids": ids, "count": len(ids)},
            )
        )
    return DiffPreviewResponse(
        batch_id="",
        target_id=_target_id(normalized),
        operation="update" if existing_any else "create",
        changes=changes,
        impact=_import_bundle_impact(db, normalized),
    )


def _apply_variant_overlay(db: Session, normalized: dict[str, Any]) -> dict[str, Any]:
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
    return {
        "scenario_ref": scenario_ref,
        "variant_ref": variant["id"],
        "operation": operation,
    }


def _apply_pipeline_patch(db: Session, normalized: dict[str, Any]) -> dict[str, Any]:
    scenario_ref = normalized["scenario_ref"]
    scenario = db.query(Scenario).filter_by(id=scenario_ref).one_or_none()
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Scenario not found: {scenario_ref}")
    before = scenario.pipeline or {}
    after = _patched_pipeline(before, normalized["patch"])
    scenario.pipeline = after
    db.add(scenario)
    db.flush()
    return {
        "scenario_ref": scenario_ref,
        "operation": "pipeline_patch",
        "node_count": len(after.get("nodes") or []),
        "edge_count": len(after.get("edges") or []),
        "buffer_count": len(after.get("buffers") or {}),
    }


def _apply_import_bundle(db: Session, normalized: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    scenario_refs: list[str] = []
    for kind in IMPORT_KIND_ORDER:
        for doc in [item for item in normalized["documents"] if item.get("kind") == kind]:
            upsert = IMPORT_UPSERT_BY_KIND[kind]
            upsert(doc, _document_sha256(doc), db)
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "scenario.usecase":
                scenario_refs.append(str(doc["id"]))
    db.flush()
    return {
        "operation": "import_bundle",
        "document_counts": counts,
        "scenario_refs": scenario_refs,
        "import_report": _import_report_summary(normalized.get("import_report") or {}),
    }


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


def _validate_pipeline_patch_node_ops(
    db: Session,
    patch: dict[str, Any],
    base_nodes: dict[str, dict[str, Any]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    add_ids: set[str] = set()
    for idx, node in enumerate(patch.get("add_nodes") or []):
        if not isinstance(node, dict):
            issues.append(_issue("error", "added_node_invalid", "Added node must be an object", f"patch.add_nodes[{idx}]"))
            continue
        node_id = node.get("id")
        if not node_id:
            issues.append(_issue("error", "added_node_missing_id", "Added node must have id", f"patch.add_nodes[{idx}]"))
            continue
        if node_id in base_nodes:
            issues.append(_issue("error", "added_node_already_exists", f"Node already exists: {node_id}", f"patch.add_nodes[{idx}].id"))
        if node_id in add_ids:
            issues.append(_issue("error", "duplicate_added_node", f"Duplicate added node: {node_id}", f"patch.add_nodes[{idx}].id"))
        add_ids.add(str(node_id))
        issues.extend(_validate_ip_ref_exists(db, node, f"patch.add_nodes[{idx}].ip_ref"))

    for idx, node in enumerate(patch.get("update_nodes") or []):
        if not isinstance(node, dict):
            issues.append(_issue("error", "updated_node_invalid", "Updated node must be an object", f"patch.update_nodes[{idx}]"))
            continue
        node_id = node.get("id")
        if not node_id:
            issues.append(_issue("error", "updated_node_missing_id", "Updated node must have id", f"patch.update_nodes[{idx}]"))
            continue
        if node_id not in base_nodes:
            issues.append(_issue("error", "updated_node_not_found", f"Node not found: {node_id}", f"patch.update_nodes[{idx}].id"))
        issues.extend(_validate_ip_ref_exists(db, node, f"patch.update_nodes[{idx}].ip_ref"))

    for idx, node_id in enumerate(patch.get("remove_nodes") or []):
        if not node_id:
            issues.append(_issue("error", "removed_node_missing_id", "Removed node must have id", f"patch.remove_nodes[{idx}]"))
        elif node_id not in base_nodes:
            issues.append(_issue("error", "removed_node_not_found", f"Node not found: {node_id}", f"patch.remove_nodes[{idx}]"))
    return issues


def _validate_pipeline_patch_edge_removes(
    patch: dict[str, Any],
    base_edges: set[tuple[str | None, str | None, str | None]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for idx, edge in enumerate(patch.get("remove_edges") or []):
        if not _edge_exists(edge, base_edges):
            issues.append(_issue("error", "removed_edge_not_found", f"Edge not found: {edge}", f"patch.remove_edges[{idx}]"))
    return issues


def _validate_pipeline_patch_buffer_removes(
    patch: dict[str, Any],
    base_buffers: set[str],
    base_edges: list[dict[str, Any]],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    removed_edges = patch.get("remove_edges") or []
    for idx, buffer_id in enumerate(patch.get("remove_buffers") or []):
        if not buffer_id:
            issues.append(_issue("error", "removed_buffer_missing_id", "Removed buffer must have id", f"patch.remove_buffers[{idx}]"))
            continue
        if buffer_id not in base_buffers:
            issues.append(_issue("error", "removed_buffer_not_found", f"Buffer not found: {buffer_id}", f"patch.remove_buffers[{idx}]"))
            continue
        still_referenced = [
            edge
            for edge in base_edges
            if edge.get("buffer") == buffer_id and not any(_edge_matches(edge, spec) for spec in removed_edges)
        ]
        if still_referenced:
            issues.append(
                _issue(
                    "error",
                    "removed_buffer_still_referenced",
                    f"Buffer still referenced by base edges: {buffer_id}",
                    f"patch.remove_buffers[{idx}]",
                )
            )

    for buffer_id, descriptor in (patch.get("upsert_buffers") or {}).items():
        if not buffer_id:
            issues.append(_issue("error", "upsert_buffer_missing_id", "Buffer key must not be empty", "patch.upsert_buffers"))
        if not isinstance(descriptor, dict):
            issues.append(_issue("error", "upsert_buffer_invalid", f"Buffer descriptor must be an object: {buffer_id}", f"patch.upsert_buffers.{buffer_id}"))
    return issues


def _validate_candidate_pipeline(db: Session, pipeline: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    nodes = _nodes_from_pipeline(pipeline)
    node_ids = set(nodes)
    buffers = set((pipeline.get("buffers") or {}).keys())
    seen_edges: set[tuple[Any, Any, Any, Any]] = set()

    for idx, edge in enumerate(pipeline.get("edges") or []):
        source = _edge_source(edge)
        target = _edge_target(edge)
        edge_type = str(edge.get("type") or "")
        path = f"pipeline.edges[{idx}]"
        if source not in node_ids:
            issues.append(_issue("error", "edge_source_not_found", f"Edge source not found: {source}", f"{path}.from"))
        if target not in node_ids:
            issues.append(_issue("error", "edge_target_not_found", f"Edge target not found: {target}", f"{path}.to"))
        if edge_type not in ALLOWED_BASE_EDGE_TYPES:
            issues.append(_issue("error", "edge_type_not_allowed", f"Base edge type is not allowed: {edge_type}", f"{path}.type"))
            continue
        if edge_type in {"OTF", "vOTF"}:
            if edge.get("buffer"):
                if edge_type == "OTF":
                    issues.append(_issue("error", "otf_edge_must_not_have_buffer", "OTF edge must not declare buffer", f"{path}.buffer"))
            if _node_class(db, nodes.get(source) or {}) != "hw" or _node_class(db, nodes.get(target) or {}) != "hw":
                issues.append(
                    _issue(
                        "error",
                        "physical_edge_endpoint_invalid",
                        f"{edge_type} edge requires HW endpoints: {source}->{target}",
                        path,
                    )
                )
        if edge_type in {"vOTF", "M2M"}:
            buffer_id = edge.get("buffer")
            if not buffer_id:
                code = "votf_edge_missing_buffer" if edge_type == "vOTF" else "m2m_edge_missing_buffer"
                issues.append(_issue("error", code, f"{edge_type} edge requires buffer: {source}->{target}", f"{path}.buffer"))
            elif buffer_id not in buffers:
                issues.append(_issue("error", "edge_buffer_not_found", f"Edge buffer not found: {buffer_id}", f"{path}.buffer"))
        key = (_edge_source(edge), _edge_target(edge), edge.get("type"), edge.get("buffer"))
        if key in seen_edges:
            issues.append(_issue("warning", "duplicate_edge", f"Duplicate edge after patch: {key}", path))
        seen_edges.add(key)
    return issues


def _pipeline_patch_impact(db: Session, scenario_ref: str, candidate: dict[str, Any]) -> dict[str, Any]:
    node_ids = set(_nodes_from_pipeline(candidate))
    edge_set = _edges_from_pipeline(candidate)
    buffer_ids = set((candidate.get("buffers") or {}).keys())
    variants = db.query(ScenarioVariant).filter_by(scenario_id=scenario_ref).all()
    affected: list[dict[str, Any]] = []
    for variant in variants:
        errors: list[str] = []
        warnings = ["base_pipeline_changed"]
        routing_switch = variant.routing_switch or {}
        topology_patch = variant.topology_patch or {}
        injected_nodes = {
            str(node.get("id"))
            for node in topology_patch.get("add_nodes") or []
            if isinstance(node, dict) and node.get("id")
        }
        known_variant_nodes = node_ids | injected_nodes

        for node_id in routing_switch.get("disabled_nodes") or []:
            if node_id not in node_ids:
                errors.append(f"routing_switch.disabled_nodes references removed node '{node_id}'")
        for edge in routing_switch.get("disabled_edges") or []:
            if not _edge_exists(edge, edge_set):
                errors.append(f"routing_switch.disabled_edges references removed edge '{edge}'")
        for edge in topology_patch.get("remove_edges") or []:
            if not _edge_exists(edge, edge_set):
                errors.append(f"topology_patch.remove_edges references removed edge '{edge}'")
        for node_id in (variant.node_configs or {}):
            if node_id not in known_variant_nodes:
                errors.append(f"node_configs references removed node '{node_id}'")
        for buffer_id in (variant.buffer_overrides or {}):
            if buffer_id not in buffer_ids:
                errors.append(f"buffer_overrides references removed buffer '{buffer_id}'")
        for edge in topology_patch.get("add_edges") or []:
            if not isinstance(edge, dict):
                continue
            source = _edge_source(edge)
            target = _edge_target(edge)
            buffer_id = edge.get("buffer")
            if source not in known_variant_nodes or target not in known_variant_nodes:
                errors.append(f"topology_patch.add_edges endpoint missing after base patch '{source}->{target}'")
            if str(edge.get("type") or "").upper() == "M2M" and buffer_id and buffer_id not in buffer_ids:
                errors.append(f"topology_patch.add_edges references removed buffer '{buffer_id}'")
        for node in topology_patch.get("add_nodes") or []:
            if isinstance(node, dict) and node.get("id") in node_ids:
                warnings.append(f"topology_patch.add_nodes now duplicates base node '{node.get('id')}'")

        affected.append({"variant_id": variant.id, "warnings": warnings, "errors": errors})
    return {
        "variant_count": len(affected),
        "affected_variants": affected,
        "blocking_variant_count": sum(1 for variant in affected if variant["errors"]),
    }


def _included_import_refs(docs: list[dict[str, Any]]) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for doc in docs:
        kind = doc.get("kind")
        doc_id = doc.get("id")
        if isinstance(kind, str) and isinstance(doc_id, str):
            refs.setdefault(kind, set()).add(doc_id)
    return refs


def _validate_import_usecase_refs(
    db: Session,
    doc: dict[str, Any],
    included: dict[str, set[str]],
    path: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    project_ref = doc.get("project_ref")
    if project_ref and project_ref not in included.get("project", set()) and db.query(Project).filter_by(id=project_ref).one_or_none() is None:
        issues.append(_issue("error", "import_project_ref_not_found", f"Project not found: {project_ref}", f"{path}.project_ref"))

    ip_refs = included.get("ip", set())
    db_ip_refs = {
        row.id
        for row in db.query(IpCatalog).all()
    }
    pipeline = doc.get("pipeline") or {}
    node_ids = {node.get("id") for node in pipeline.get("nodes") or [] if isinstance(node, dict)}
    buffer_ids = set((pipeline.get("buffers") or {}).keys())
    for idx, node in enumerate(pipeline.get("nodes") or []):
        if not isinstance(node, dict):
            continue
        ip_ref = node.get("ip_ref")
        if ip_ref and ip_ref not in ip_refs and ip_ref not in db_ip_refs:
            issues.append(_issue("error", "import_ip_ref_not_found", f"IP catalog not found: {ip_ref}", f"{path}.pipeline.nodes[{idx}].ip_ref"))

    seen_edges: set[tuple[Any, Any, Any, Any]] = set()
    for idx, edge in enumerate(pipeline.get("edges") or []):
        if not isinstance(edge, dict):
            continue
        edge_path = f"{path}.pipeline.edges[{idx}]"
        source = _edge_source(edge)
        target = _edge_target(edge)
        edge_type = str(edge.get("type") or "")
        if source not in node_ids:
            issues.append(_issue("error", "import_edge_source_not_found", f"Edge source not found: {source}", f"{edge_path}.from"))
        if target not in node_ids:
            issues.append(_issue("error", "import_edge_target_not_found", f"Edge target not found: {target}", f"{edge_path}.to"))
        if edge_type not in ALLOWED_BASE_EDGE_TYPES:
            issues.append(_issue("error", "import_edge_type_not_allowed", f"Import edge type is not allowed: {edge_type}", f"{edge_path}.type"))
        if edge_type == "OTF" and edge.get("buffer"):
            issues.append(_issue("error", "import_otf_edge_must_not_have_buffer", "OTF edge must not declare buffer", f"{edge_path}.buffer"))
        if edge_type in {"vOTF", "M2M"}:
            buffer_id = edge.get("buffer")
            if not buffer_id:
                code = "import_votf_edge_missing_buffer" if edge_type == "vOTF" else "import_m2m_edge_missing_buffer"
                issues.append(_issue("error", code, f"{edge_type} edge requires buffer: {source}->{target}", f"{edge_path}.buffer"))
            elif buffer_id not in buffer_ids:
                issues.append(_issue("error", "import_edge_buffer_not_found", f"Edge buffer not found: {buffer_id}", f"{edge_path}.buffer"))
        key = (source, target, edge_type, edge.get("buffer"))
        if key in seen_edges:
            issues.append(_issue("warning", "import_duplicate_edge", f"Duplicate import edge: {key}", edge_path))
        seen_edges.add(key)

    for variant_idx, variant in enumerate(doc.get("variants") or []):
        if not isinstance(variant, dict):
            continue
        variant_path = f"{path}.variants[{variant_idx}]"
        injected_nodes = {
            node.get("id")
            for node in ((variant.get("topology_patch") or {}).get("add_nodes") or [])
            if isinstance(node, dict) and node.get("id")
        }
        known_nodes = node_ids | injected_nodes
        for node_id in (variant.get("node_configs") or {}):
            if node_id not in known_nodes:
                issues.append(_issue("error", "import_variant_node_config_not_found", f"node_configs references missing node: {node_id}", f"{variant_path}.node_configs"))
        for buffer_id in (variant.get("buffer_overrides") or {}):
            if buffer_id not in buffer_ids:
                issues.append(_issue("error", "import_variant_buffer_override_not_found", f"buffer_overrides references missing buffer: {buffer_id}", f"{variant_path}.buffer_overrides"))
    return issues


def _existing_import_doc_ids(db: Session, kind: str, ids: list[str]) -> set[str]:
    model = IMPORT_DB_MODEL_BY_KIND.get(kind)
    if model is None or not ids:
        return set()
    id_set = set(ids)
    return {
        row.id
        for row in db.query(model).all()
        if row.id in id_set
    }


def _import_bundle_impact(db: Session, normalized: dict[str, Any]) -> dict[str, Any]:
    report = normalized.get("import_report") or {}
    scenario_impacts: list[dict[str, Any]] = []
    for doc in normalized["documents"]:
        if doc.get("kind") != "scenario.usecase":
            continue
        scenario_id = str(doc["id"])
        existing_variants = {
            row.id
            for row in db.query(ScenarioVariant).filter_by(scenario_id=scenario_id).all()
        }
        imported_variants = {
            variant["id"]
            for variant in doc.get("variants") or []
            if isinstance(variant, dict) and variant.get("id")
        }
        scenario_impacts.append(
            {
                "scenario_id": scenario_id,
                "operation": "update" if db.query(Scenario).filter_by(id=scenario_id).one_or_none() else "create",
                "variant_count_before": len(existing_variants),
                "variant_count_after": len(imported_variants),
                "variants_added": sorted(imported_variants - existing_variants),
                "variants_removed": sorted(existing_variants - imported_variants),
                "variants_updated": sorted(imported_variants & existing_variants),
            }
        )
    return {
        "document_count": len(normalized["documents"]),
        "document_counts": _count_docs_by_kind(normalized["documents"]),
        "scenario_impacts": scenario_impacts,
        "import_report": _import_report_summary(report),
    }


def _count_docs_by_kind(docs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in docs:
        kind = str(doc.get("kind"))
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _import_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    messages = report.get("messages") or []
    by_level: dict[str, int] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        level = str(message.get("level") or "unknown")
        by_level[level] = by_level.get(level, 0) + 1
    return {
        "ok": report.get("ok"),
        "generated": report.get("generated") or {},
        "message_count": len(messages),
        "messages_by_level": by_level,
    }


def _document_sha256(doc: dict[str, Any]) -> str:
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _patched_pipeline(pipeline: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(pipeline or {})
    nodes = [deepcopy(node) for node in result.get("nodes") or []]
    edges = [_normalize_edge(edge) for edge in result.get("edges") or []]
    buffers = deepcopy(result.get("buffers") or {})

    remove_edge_specs = patch.get("remove_edges") or []
    edges = [edge for edge in edges if not any(_edge_matches(edge, spec) for spec in remove_edge_specs)]

    remove_nodes = set(patch.get("remove_nodes") or [])
    nodes = [node for node in nodes if node.get("id") not in remove_nodes]
    edges = [
        edge
        for edge in edges
        if _edge_source(edge) not in remove_nodes and _edge_target(edge) not in remove_nodes
    ]

    for update in patch.get("update_nodes") or []:
        if not isinstance(update, dict):
            continue
        node_id = update.get("id")
        for node in nodes:
            if node.get("id") == node_id:
                node.update(deepcopy(update))
                break

    for add in patch.get("add_nodes") or []:
        if isinstance(add, dict):
            nodes.append(deepcopy(add))

    for buffer_id in patch.get("remove_buffers") or []:
        buffers.pop(buffer_id, None)
    for buffer_id, descriptor in (patch.get("upsert_buffers") or {}).items():
        existing = deepcopy(buffers.get(buffer_id) or {})
        existing.update(deepcopy(descriptor))
        buffers[buffer_id] = existing

    edges.extend(_normalize_edge(edge) for edge in patch.get("add_edges") or [])
    result["nodes"] = nodes
    result["edges"] = edges
    result["buffers"] = buffers
    return result


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
    return _nodes_from_pipeline(scenario.pipeline or {})


def _nodes_from_pipeline(pipeline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = pipeline.get("nodes") or []
    return {node.get("id"): node for node in nodes if isinstance(node, dict) and node.get("id")}


def _base_edges(scenario: Scenario) -> set[tuple[str | None, str | None, str | None]]:
    return _edges_from_pipeline(scenario.pipeline or {})


def _edges_from_pipeline(pipeline: dict[str, Any]) -> set[tuple[str | None, str | None, str | None]]:
    edges = pipeline.get("edges") or []
    return {
        (edge.get("id"), _edge_source(edge), _edge_target(edge))
        for edge in edges
        if isinstance(edge, dict)
    }


def _variant_ids(db: Session, scenario_ref: str) -> set[str]:
    return {
        row.id
        for row in db.query(ScenarioVariant).filter_by(scenario_id=scenario_ref).all()
    }


def _edge_exists(edge: Any, base_edges: set[tuple[str | None, str | None, str | None]]) -> bool:
    if not isinstance(edge, dict):
        return False
    edge_id = edge.get("id")
    source = _edge_source(edge)
    target = _edge_target(edge)
    for base_id, base_source, base_target in base_edges:
        if edge_id and edge_id == base_id:
            return True
        if source == base_source and target == base_target:
            return True
    return False


def _edge_matches(edge: dict[str, Any], spec: dict[str, Any]) -> bool:
    spec_id = spec.get("id")
    if spec_id and spec_id == edge.get("id"):
        return True
    return _edge_source(edge) == _edge_source(spec) and _edge_target(edge) == _edge_target(spec)


def _edge_source(edge: dict[str, Any]) -> Any:
    return edge.get("from") if edge.get("from") is not None else edge.get("source")


def _edge_target(edge: dict[str, Any]) -> Any:
    return edge.get("to") if edge.get("to") is not None else edge.get("target")


def _normalize_edge(edge: Any) -> dict[str, Any]:
    if not isinstance(edge, dict):
        return {}
    normalized = deepcopy(edge)
    if "source" in normalized and "from" not in normalized:
        normalized["from"] = normalized.pop("source")
    if "target" in normalized and "to" not in normalized:
        normalized["to"] = normalized.pop("target")
    return normalized


def _normalize_ref(item: Any) -> str:
    if isinstance(item, dict):
        value = item.get("id") or item.get("ref") or item.get("name")
    else:
        value = item
    return str(value) if value is not None else ""


def _is_sw_node(node: dict[str, Any]) -> bool:
    text = f"{node.get('node_type', '')} {node.get('layer', '')} {node.get('kind', '')}".lower()
    return any(token in text.split() for token in {"sw", "app", "framework", "hal", "kernel", "task", "cpu"})


def _node_class(db: Session, node: dict[str, Any]) -> str:
    if _is_sw_node(node):
        return "sw"
    explicit = f"{node.get('node_type', '')} {node.get('layer', '')} {node.get('kind', '')}".lower()
    if any(token in explicit.split() for token in {"memory", "buffer", "llc", "dram"}):
        return "memory"
    node_id = str(node.get("id") or "").lower()
    ip_ref = node.get("ip_ref")
    category = _ip_category(db, ip_ref)
    if category == "memory" or any(token in node_id for token in ("llc", "dram", "mem")):
        return "memory"
    if ip_ref:
        return "hw"
    return "unknown"


def _validate_ip_ref_exists(db: Session, node: dict[str, Any], path: str) -> list[ValidationIssue]:
    ip_ref = node.get("ip_ref")
    if not ip_ref:
        return []
    if db.query(IpCatalog).filter_by(id=ip_ref).one_or_none() is None:
        return [_issue("error", "ip_ref_not_found", f"IP catalog not found: {ip_ref}", path)]
    return []


def _ip_category(db: Session, ip_ref: str | None) -> str | None:
    if not ip_ref:
        return None
    ip = db.query(IpCatalog).filter_by(id=ip_ref).one_or_none()
    return str(ip.category).lower() if ip is not None and ip.category else None


def _operating_mode_ids(db: Session, ip_ref: str) -> set[str]:
    ip = db.query(IpCatalog).filter_by(id=ip_ref).one_or_none()
    modes = (((ip.capabilities if ip else {}) or {}).get("operating_modes") or [])
    return {str(mode.get("id")) for mode in modes if isinstance(mode, dict) and mode.get("id")}


def _pipeline_count_diff(field: str, before: Any, after: Any) -> DiffEntry:
    before_count = len(before)
    after_count = len(after)
    if before == after:
        change = "unchanged"
    elif before_count == 0 and after_count > 0:
        change = "add"
    elif after_count == 0 and before_count > 0:
        change = "remove"
    else:
        change = "modify"
    return DiffEntry(
        field=field,
        change=change,
        before={"count": before_count, "value": before},
        after={"count": after_count, "value": after},
    )


def _target_id(normalized: dict[str, Any]) -> str:
    if "variant" in normalized:
        return f"{normalized['scenario_ref']}/{normalized['variant']['id']}"
    if "documents" in normalized:
        scenario_ids = [
            str(doc["id"])
            for doc in normalized["documents"]
            if doc.get("kind") == "scenario.usecase"
        ]
        if scenario_ids:
            return ",".join(scenario_ids)
        return f"import_bundle:{len(normalized['documents'])}"
    return normalized["scenario_ref"]


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
