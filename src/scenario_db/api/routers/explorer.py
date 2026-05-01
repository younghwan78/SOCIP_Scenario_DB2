from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.explorer import (
    ExplorerCount,
    ExplorerSummaryResponse,
    ImportBatchSummary,
    ImportHealthIssue,
    ImportHealthResponse,
    ScenarioCatalogItem,
    ScenarioCatalogResponse,
    VariantMatrixItem,
    VariantMatrixResponse,
)
from scenario_db.db.models.capability import IpCatalog, SocPlatform, SwProfile
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.write import WriteBatch

router = APIRouter(prefix="/explorer", tags=["explorer"])


@router.get("/summary", response_model=ExplorerSummaryResponse)
def explorer_summary(
    soc_ref: str | None = Query(None),
    board_type: str | None = Query(None),
    project_ref: str | None = Query(None),
    db: Session = Depends(get_db),
):
    projects, scenarios, variants = _filtered_rows(db, soc_ref, board_type, project_ref)
    category_counts = Counter()
    severity_counts = Counter()
    board_counts = Counter()
    for project in projects:
        board_counts[_project_meta(project, "board_type") or "unknown"] += 1
    for scenario in scenarios:
        for category in _scenario_list_meta(scenario, "category") or ["uncategorized"]:
            category_counts[str(category)] += 1
    for variant in variants:
        severity_counts[variant.severity or "unknown"] += 1

    soc_ids = {str(_project_meta(project, "soc_ref")) for project in projects if _project_meta(project, "soc_ref")}
    return ExplorerSummaryResponse(
        filters=_filters(soc_ref, board_type, project_ref),
        totals={
            "soc": _count_matching_socs(db, soc_ids) if soc_ids else db.query(SocPlatform).count(),
            "project": len(projects),
            "scenario": len(scenarios),
            "variant": len(variants),
            "ip": _count_matching_ips(db, soc_ids) if soc_ids else db.query(IpCatalog).count(),
            "sw_profile": _count_matching_sw_profiles(db, soc_ids) if soc_ids else db.query(SwProfile).count(),
        },
        category_counts=_counter_items(category_counts),
        severity_counts=_counter_items(severity_counts),
        board_counts=_counter_items(board_counts),
        latest_import_batches=_latest_import_batches(db),
    )


@router.get("/scenario-catalog", response_model=ScenarioCatalogResponse)
def scenario_catalog(
    soc_ref: str | None = Query(None),
    board_type: str | None = Query(None),
    project_ref: str | None = Query(None),
    category: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    projects, scenarios, variants = _filtered_rows(db, soc_ref, board_type, project_ref)
    project_by_id = {project.id: project for project in projects}
    variants_by_scenario = _variants_by_scenario(variants)
    items: list[ScenarioCatalogItem] = []
    for scenario in sorted(scenarios, key=lambda row: row.id):
        categories = _scenario_list_meta(scenario, "category")
        if category is not None and category not in categories:
            continue
        project = project_by_id.get(scenario.project_ref)
        if project is None:
            continue
        scenario_variants = sorted(variants_by_scenario.get(scenario.id, []), key=lambda row: row.id)
        severity_counts = Counter(variant.severity or "unknown" for variant in scenario_variants)
        pipeline = scenario.pipeline or {}
        default_variant_id = scenario_variants[0].id if scenario_variants else None
        items.append(
            ScenarioCatalogItem(
                soc_ref=_project_meta(project, "soc_ref"),
                board_type=_project_meta(project, "board_type"),
                board_name=_project_meta(project, "board_name"),
                project_id=project.id,
                project_name=_project_meta(project, "name"),
                scenario_id=scenario.id,
                scenario_name=str(_scenario_meta(scenario, "name") or scenario.id),
                category=categories,
                domain=_scenario_list_meta(scenario, "domain"),
                variant_count=len(scenario_variants),
                severity_counts=dict(sorted(severity_counts.items())),
                sensor_module_ref=_project_meta(project, "sensor_module_ref"),
                display_module_ref=_project_meta(project, "display_module_ref"),
                default_sw_profile_ref=_project_meta(project, "default_sw_profile_ref") or _project_global(project, "default_sw_profile_ref"),
                node_count=len(pipeline.get("nodes") or []),
                edge_count=len(pipeline.get("edges") or []),
                buffer_count=len(pipeline.get("buffers") or {}),
                default_variant_id=default_variant_id,
                viewer_query=_viewer_query(project, scenario.id, default_variant_id),
            )
        )
    return ScenarioCatalogResponse(
        filters={**_filters(soc_ref, board_type, project_ref), "category": category},
        total=len(items),
        items=items[offset : offset + limit],
    )


@router.get("/variant-matrix", response_model=VariantMatrixResponse)
def variant_matrix(
    soc_ref: str | None = Query(None),
    board_type: str | None = Query(None),
    project_ref: str | None = Query(None),
    category: str | None = Query(None),
    scenario_id: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    projects, scenarios, variants = _filtered_rows(db, soc_ref, board_type, project_ref)
    project_by_id = {project.id: project for project in projects}
    scenario_by_id = {scenario.id: scenario for scenario in scenarios}
    axis_keys: set[str] = set()
    items: list[VariantMatrixItem] = []
    for variant in sorted(variants, key=lambda row: (row.scenario_id, row.id)):
        scenario = scenario_by_id.get(variant.scenario_id)
        if scenario is None:
            continue
        categories = _scenario_list_meta(scenario, "category")
        if category is not None and category not in categories:
            continue
        if scenario_id is not None and scenario.id != scenario_id:
            continue
        project = project_by_id.get(scenario.project_ref)
        if project is None:
            continue
        design = variant.design_conditions or {}
        axis_keys.update(str(key) for key in design)
        routing = variant.routing_switch or {}
        disabled_nodes = [str(item) for item in routing.get("disabled_nodes") or []]
        pipeline_node_count = len((scenario.pipeline or {}).get("nodes") or [])
        items.append(
            VariantMatrixItem(
                soc_ref=_project_meta(project, "soc_ref"),
                board_type=_project_meta(project, "board_type"),
                project_id=project.id,
                scenario_id=scenario.id,
                scenario_name=str(_scenario_meta(scenario, "name") or scenario.id),
                category=categories,
                variant_id=variant.id,
                severity=variant.severity,
                design_conditions=design,
                key_fields={key: design.get(key) for key in _priority_axis_keys(design)},
                enabled_nodes=max(pipeline_node_count - len(disabled_nodes), 0),
                disabled_nodes=disabled_nodes,
                disabled_edges=len(routing.get("disabled_edges") or []),
                buffer_override_count=len(variant.buffer_overrides or {}),
                node_config_count=len(variant.node_configs or {}),
                tags=variant.tags or [],
                viewer_query=_viewer_query(project, scenario.id, variant.id),
            )
        )
    return VariantMatrixResponse(
        filters={**_filters(soc_ref, board_type, project_ref), "category": category, "scenario_id": scenario_id},
        total=len(items),
        axis_keys=_sorted_axis_keys(axis_keys),
        items=items[offset : offset + limit],
    )


@router.get("/import-health", response_model=ImportHealthResponse)
def import_health(
    soc_ref: str | None = Query(None),
    board_type: str | None = Query(None),
    project_ref: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    projects, scenarios, variants = _filtered_rows(db, soc_ref, board_type, project_ref)
    issues = _data_quality_issues(db, projects, scenarios, variants)
    issues = issues[:limit]
    counts = Counter(issue.severity for issue in issues)
    return ImportHealthResponse(
        filters=_filters(soc_ref, board_type, project_ref),
        issue_counts=dict(sorted(counts.items())),
        issues=issues,
        latest_import_batches=_latest_import_batches(db),
    )


def _filtered_rows(
    db: Session,
    soc_ref: str | None,
    board_type: str | None,
    project_ref: str | None,
) -> tuple[list[Project], list[Scenario], list[ScenarioVariant]]:
    project_rows = sorted(db.query(Project).all(), key=lambda row: row.id)
    projects = [
        row
        for row in project_rows
        if (project_ref is None or row.id == project_ref)
        and (soc_ref is None or _project_meta(row, "soc_ref") == soc_ref)
        and (board_type is None or _project_meta(row, "board_type") == board_type)
    ]
    project_ids = {row.id for row in projects}
    scenarios = sorted(
        [row for row in db.query(Scenario).all() if row.project_ref in project_ids],
        key=lambda row: row.id,
    )
    scenario_ids = {row.id for row in scenarios}
    variants = sorted(
        [row for row in db.query(ScenarioVariant).all() if row.scenario_id in scenario_ids],
        key=lambda row: (row.scenario_id, row.id),
    )
    return projects, scenarios, variants


def _data_quality_issues(
    db: Session,
    projects: list[Project],
    scenarios: list[Scenario],
    variants: list[ScenarioVariant],
) -> list[ImportHealthIssue]:
    issues: list[ImportHealthIssue] = []
    soc_ids = {row.id for row in db.query(SocPlatform).all()}
    ip_ids = {row.id for row in db.query(IpCatalog).all()}
    sw_profile_ids = {row.id for row in db.query(SwProfile).all()}
    project_ids = {row.id for row in projects}
    variant_counts = Counter(variant.scenario_id for variant in variants)

    for project in projects:
        metadata = project.metadata_ or {}
        _check_ref(issues, metadata.get("soc_ref"), soc_ids, "project_soc_ref_missing", project.id, "metadata.soc_ref", "Add matching soc YAML or fix project metadata.soc_ref.")
        _check_ref(issues, metadata.get("sensor_module_ref"), ip_ids, "project_sensor_ref_missing", project.id, "metadata.sensor_module_ref", "Add sensor IP catalog YAML or fix sensor_module_ref.")
        _check_ref(issues, metadata.get("display_module_ref"), ip_ids, "project_display_ref_missing", project.id, "metadata.display_module_ref", "Add display panel IP catalog YAML or fix display_module_ref.")
        sw_ref = metadata.get("default_sw_profile_ref") or _project_global(project, "default_sw_profile_ref")
        _check_ref(issues, sw_ref, sw_profile_ids, "project_sw_profile_ref_missing", project.id, "metadata.default_sw_profile_ref", "Add sw_profile YAML under 01_sw or fix default_sw_profile_ref.")

    for scenario in scenarios:
        if scenario.project_ref not in project_ids:
            issues.append(_health_issue("error", "scenario_project_ref_missing", f"Project not found: {scenario.project_ref}", "scenario.usecase", scenario.id, "project_ref", "Import the project YAML before scenario YAML."))
        pipeline = scenario.pipeline or {}
        nodes = {str(node.get("id")): node for node in pipeline.get("nodes") or [] if isinstance(node, dict)}
        buffers = set((pipeline.get("buffers") or {}).keys())
        for idx, node in enumerate(pipeline.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            ip_ref = node.get("ip_ref")
            if ip_ref and ip_ref not in ip_ids:
                issues.append(_health_issue("error", "scenario_node_ip_ref_missing", f"IP catalog not found: {ip_ref}", "scenario.usecase", scenario.id, f"pipeline.nodes[{idx}].ip_ref", "Add matching IP YAML or fix node.ip_ref."))
        for idx, edge in enumerate(pipeline.get("edges") or []):
            if not isinstance(edge, dict):
                continue
            source = _edge_source(edge)
            target = _edge_target(edge)
            edge_type = str(edge.get("type") or "")
            edge_path = f"pipeline.edges[{idx}]"
            if source not in nodes:
                issues.append(_health_issue("error", "scenario_edge_source_missing", f"Edge source not found: {source}", "scenario.usecase", scenario.id, f"{edge_path}.from", "Fix edge.from or add the missing node."))
            if target not in nodes:
                issues.append(_health_issue("error", "scenario_edge_target_missing", f"Edge target not found: {target}", "scenario.usecase", scenario.id, f"{edge_path}.to", "Fix edge.to or add the missing node."))
            buffer_id = edge.get("buffer")
            if edge_type == "OTF" and buffer_id:
                issues.append(_health_issue("error", "scenario_otf_buffer_forbidden", "OTF edge must not declare buffer.", "scenario.usecase", scenario.id, f"{edge_path}.buffer", "Remove buffer from OTF edge. Use vOTF or M2M if memory is involved."))
            if edge_type in {"M2M", "vOTF"} and not buffer_id:
                issues.append(_health_issue("error", "scenario_memory_edge_buffer_missing", f"{edge_type} edge requires buffer: {source}->{target}", "scenario.usecase", scenario.id, f"{edge_path}.buffer", "If this is SW scheduling/control, use type: control. If data moves through memory, add a buffer descriptor."))
            if buffer_id and buffer_id not in buffers:
                issues.append(_health_issue("error", "scenario_edge_buffer_missing", f"Buffer not found: {buffer_id}", "scenario.usecase", scenario.id, f"{edge_path}.buffer", "Add pipeline.buffers entry or fix edge.buffer."))
        if variant_counts[scenario.id] == 0:
            issues.append(_health_issue("warning", "scenario_without_variant", f"Scenario has no variants: {scenario.id}", "scenario.usecase", scenario.id, "variants", "Add at least one variant unless this is intentionally a base-only scenario."))
    return issues


def _latest_import_batches(db: Session, limit: int = 5) -> list[ImportBatchSummary]:
    rows = (
        db.query(WriteBatch)
        .filter(WriteBatch.kind == "scenario.import_bundle")
        .order_by(WriteBatch.updated_at.desc())
        .limit(limit)
        .all()
    )
    result: list[ImportBatchSummary] = []
    for row in rows:
        validation = row.validation_result or {}
        applied_refs = row.applied_refs or {}
        result.append(
            ImportBatchSummary(
                id=row.id,
                kind=row.kind,
                status=row.status,
                target_id=row.target_id,
                actor=row.actor,
                note=row.note,
                created_at=row.created_at,
                updated_at=row.updated_at,
                validation_valid=validation.get("valid"),
                validation_issue_count=len(validation.get("issues") or []),
                applied_document_counts=applied_refs.get("document_counts") or {},
            )
        )
    return result


def _check_ref(
    issues: list[ImportHealthIssue],
    ref: Any,
    known_ids: set[str],
    code: str,
    document_id: str,
    path: str,
    fix_hint: str,
) -> None:
    if ref and str(ref) not in known_ids:
        issues.append(_health_issue("error", code, f"Reference not found: {ref}", "project", document_id, path, fix_hint))


def _health_issue(
    severity: str,
    code: str,
    message: str,
    document_kind: str,
    document_id: str,
    path: str,
    fix_hint: str,
) -> ImportHealthIssue:
    return ImportHealthIssue(
        severity=severity,  # type: ignore[arg-type]
        code=code,
        message=message,
        document_kind=document_kind,
        document_id=document_id,
        path=path,
        fix_hint=fix_hint,
    )


def _variants_by_scenario(variants: list[ScenarioVariant]) -> dict[str, list[ScenarioVariant]]:
    result: dict[str, list[ScenarioVariant]] = {}
    for variant in variants:
        result.setdefault(variant.scenario_id, []).append(variant)
    return result


def _project_meta(project: Project, key: str) -> str | None:
    value = (project.metadata_ or {}).get(key)
    return str(value) if value not in (None, "") else None


def _project_global(project: Project, key: str) -> str | None:
    value = (project.globals_ or {}).get(key)
    return str(value) if value not in (None, "") else None


def _scenario_meta(scenario: Scenario, key: str) -> Any:
    return (scenario.metadata_ or {}).get(key)


def _scenario_list_meta(scenario: Scenario, key: str) -> list[str]:
    value = _scenario_meta(scenario, key)
    if isinstance(value, list):
        return _unique_strings(value)
    if value:
        return [str(value)]
    return []


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _viewer_query(project: Project, scenario_id: str, variant_id: str | None) -> dict[str, str]:
    query = {
        "soc_id": _project_meta(project, "soc_ref") or "",
        "project_id": project.id,
        "scenario_id": scenario_id,
    }
    if variant_id:
        query["variant_id"] = variant_id
    return {key: value for key, value in query.items() if value}


def _filters(soc_ref: str | None, board_type: str | None, project_ref: str | None) -> dict[str, Any]:
    return {key: value for key, value in {"soc_ref": soc_ref, "board_type": board_type, "project_ref": project_ref}.items() if value is not None}


def _counter_items(counter: Counter[str]) -> list[ExplorerCount]:
    return [ExplorerCount(key=key, count=count) for key, count in sorted(counter.items())]


def _priority_axis_keys(design: dict[str, Any]) -> list[str]:
    priority = ["resolution", "fps", "hdr", "dynamic_range", "codec", "codec_mfc", "sensor", "audio", "gpu", "npu"]
    keys = [key for key in priority if key in design]
    keys.extend(sorted(key for key in design if key not in keys)[:6])
    return keys


def _sorted_axis_keys(keys: set[str]) -> list[str]:
    priority = ["resolution", "fps", "hdr", "dynamic_range", "bit_depth", "codec", "codec_mfc", "sensor", "audio", "gpu", "npu"]
    return [key for key in priority if key in keys] + sorted(key for key in keys if key not in priority)


def _count_matching_socs(db: Session, soc_ids: set[str]) -> int:
    return sum(1 for row in db.query(SocPlatform).all() if row.id in soc_ids)


def _count_matching_ips(db: Session, soc_ids: set[str]) -> int:
    count = 0
    for row in db.query(IpCatalog).all():
        compatible = row.compatible_soc or []
        if not compatible or any(str(item) in soc_ids for item in compatible):
            count += 1
    return count


def _count_matching_sw_profiles(db: Session, soc_ids: set[str]) -> int:
    count = 0
    for row in db.query(SwProfile).all():
        compatible = (row.metadata_ or {}).get("compatible_soc") or []
        if not compatible or any(str(item) in soc_ids for item in compatible):
            count += 1
    return count


def _edge_source(edge: dict[str, Any]) -> Any:
    return edge.get("from") if edge.get("from") is not None else edge.get("source")


def _edge_target(edge: dict[str, Any]) -> Any:
    return edge.get("to") if edge.get("to") is not None else edge.get("target")
