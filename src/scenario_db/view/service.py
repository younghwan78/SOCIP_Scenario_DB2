"""View projection service.

build_canonical_graph() → project_level0() → ViewResponse

Sample data matches the "Video Recording — FHD 30fps" scenario from the
design draft. Real DB integration is wired via the FastAPI router; the
dashboard can also call this module directly without an HTTP round-trip.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from scenario_db.api.schemas.view import (
    EdgeData, EdgeElement, MemoryDescriptor, MemoryPlacement,
    NodeData, NodeElement, OperationSummary, RiskCard,
    ViewHints, ViewResponse, ViewSummary,
)
from scenario_db.db.repositories.scenario_graph import (
    CanonicalScenarioGraph,
    load_base_canonical_graph,
    load_canonical_graph,
)
from scenario_db.review_gate.engine import run_review_gate
from scenario_db.view.level0 import (
    Level0ProjectionDeps,
    project_architecture as _level0_project_architecture,
    project_topology as _level0_project_topology,
)
from scenario_db.view.level0_v2 import (
    build_resource_overview,
    project_level0_resource_view,
    project_level0_topology_view,
)
from scenario_db.view.layout import (
    BG_CENTER_X, BG_WIDTH, CANVAS_H, CANVAS_W,
    LANE_H, LANE_LABEL_W, LANE_Y, LANE_DISPLAY_NAMES,
    NODE_H, NODE_W, STAGE_HEADER_H, STAGE_X,
)
from scenario_db.view.graph_utils import (
    edge_source as _edge_source,
    edge_target as _edge_target,
    parse_size as _parse_size,
    resolution_to_size as _resolution_to_size,
    safe_id as _safe_id,
)
from scenario_db.view.sample_data import build_sample_level0
from scenario_db.view.simulation_overlay import apply_simulation_overlay
from scenario_db.view.response import build_view_response as _response


# ---------------------------------------------------------------------------
# Sample scenario — Camera Recording FHD 30fps (matches design image)
# ---------------------------------------------------------------------------

def _n(nid: str, label: str, ntype: str, layer: str,
       x: float, y: float, **kwargs) -> NodeElement:
    data = NodeData(id=nid, label=label, type=ntype, layer=layer, **kwargs)
    return NodeElement(data=data, position={"x": x, "y": y})


def _e(eid: str, src: str, tgt: str, flow_type: str, **kwargs) -> EdgeElement:
    data = EdgeData(id=eid, source=src, target=tgt, flow_type=flow_type, **kwargs)
    return EdgeElement(data=data)




# ---------------------------------------------------------------------------
# Projection helpers (stubs for DB-backed projection)
# ---------------------------------------------------------------------------

def _deprecated_project_level0(scenario_id: str, variant_id: str, db=None) -> ViewResponse:
    """Project DB data into a Level 0 ViewResponse.

    Falls back to sample data when db is None (dashboard demo mode).
    """
    if db is None:
        return build_sample_level0()
    # TODO: query DB → assemble canonical graph → project to Level 0
    raise NotImplementedError("DB-backed Level 0 projection is Phase C work")


def _deprecated_project_level1(scenario_id: str, variant_id: str, db=None) -> ViewResponse:
    raise NotImplementedError("Level 1 IP DAG projection is Phase C work")


def _deprecated_project_level2(scenario_id: str, variant_id: str, expand: str, db=None) -> ViewResponse:
    raise NotImplementedError("Level 2 composite-IP drill-down is Phase C work")


# ---------------------------------------------------------------------------
# DB-backed projections
# ---------------------------------------------------------------------------

def project_level0(
    scenario_id: str,
    variant_id: str | None,
    db=None,
    mode: str = "architecture",
) -> ViewResponse:
    """Project scenario/variant DB data into Level 0 viewer data."""
    if db is None:
        return build_sample_level0()
    graph = _load_graph(db, scenario_id, variant_id)
    if mode == "resource":
        return _project_level0_resource_v2(graph, level=0)
    if mode == "topology":
        return _project_level0_topology_v2(graph, level=0)
    return _project_architecture(graph, level=0)


def project_level1(scenario_id: str, variant_id: str | None, db=None) -> ViewResponse:
    if db is None:
        return build_sample_level0()
    graph = _load_graph(db, scenario_id, variant_id)
    semantic = _project_semantic_level1(graph)
    if semantic is not None:
        return semantic
    return _project_reference_level1(graph)


def project_level2(scenario_id: str, variant_id: str | None, expand: str, db=None) -> ViewResponse:
    if db is None:
        return build_sample_level0()
    graph = _load_graph(db, scenario_id, variant_id)
    return _project_drilldown(graph, expand)






























def _load_graph(db, scenario_id: str, variant_id: str | None) -> CanonicalScenarioGraph:
    if variant_id:
        return load_canonical_graph(db, scenario_id, variant_id)
    return load_base_canonical_graph(db, scenario_id)


def _level0_projection_deps() -> Level0ProjectionDeps:
    return Level0ProjectionDeps(
        sw_stack_nodes=_sw_stack_nodes,
        architecture_resource_nodes=_architecture_resource_nodes,
        buffer_nodes_from_architecture_edges=_buffer_nodes_from_architecture_edges,
        architecture_edges=_architecture_edges,
        inferred_architecture_edges=_inferred_architecture_edges,
        sw_control_edges=_sw_control_edges,
        risk_edges=_risk_edges,
        response=_response,
        pipeline_ranks=_pipeline_ranks,
        node_element=_n,
        node_label=_node_label,
        pipeline_node_type=_pipeline_node_type,
        pipeline_node_layer=_pipeline_node_layer,
        capability_badges=_capability_badges,
        operation_summary=_operation_summary,
        node_detail_items=_node_detail_items,
        stage_for_node=_stage_for_node,
        memory_descriptor=_memory_descriptor,
        memory_placement=_memory_placement,
        buffer_detail_items=_buffer_detail_items,
        safe_id=_safe_id,
        buffer_label=_buffer_label,
        topology_edges=_topology_edges,
    )


def _project_architecture(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    return _level0_project_architecture(graph, level, _level0_projection_deps())


def _project_topology(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    return _level0_project_topology(graph, level, _level0_projection_deps())


def _project_level0_resource_v2(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    projection = project_level0_resource_view(graph)
    return _response(
        graph=graph,
        level=level,
        mode="resource",
        nodes=projection.nodes,
        edges=projection.edges,
        metadata=projection.metadata,
    )


def _project_level0_topology_v2(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    projection = project_level0_topology_view(graph)
    return _response(
        graph=graph,
        level=level,
        mode="topology",
        nodes=projection.nodes,
        edges=projection.edges,
        metadata=projection.metadata,
    )


def _project_semantic_level1(graph: CanonicalScenarioGraph) -> ViewResponse | None:
    from scenario_db.view.level1_semantic import project_semantic_level1

    return project_semantic_level1(graph)


def _reference_sizes(graph: CanonicalScenarioGraph) -> dict[str, str]:
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    overrides = getattr(graph.variant, "size_overrides", None) or {}
    sensor = anchors.get("sensor_full") or "4000x3000"
    record = overrides.get("record_out") or _resolution_to_size(design.get("resolution")) or anchors.get("record_out") or "1920x1080"
    preview = overrides.get("preview_out") or anchors.get("preview_out") or record
    fps = int(design.get("fps") or 30)
    return {
        "sensor_full": str(sensor),
        "record_out": str(record),
        "preview_out": str(preview),
        "sensor": str(sensor),
        "record": str(record),
        "preview": str(preview),
        "fps": str(fps),
        "codec": str(design.get("codec") or "H.265"),
    }


def _ref_task_node(
    node_id: str,
    label: str,
    x: float,
    y: float,
    *,
    layer: str = "hw",
    width: int = 132,
    height: int = 52,
    ip_ref: str | None = None,
    badges: list[str] | None = None,
    ops: OperationSummary | None = None,
    memory: MemoryDescriptor | None = None,
    placement: MemoryPlacement | None = None,
    detail_items: list[str] | None = None,
) -> NodeElement:
    return _n(
        node_id,
        label,
        "sw" if layer in {"app", "framework", "hal", "kernel"} else "ip",
        layer,
        x,
        y,
        ip_ref=ip_ref,
        summary_badges=["task"],
        capability_badges=badges or [],
        active_operations=ops,
        memory=memory,
        placement=placement,
        detail_items=detail_items or [],
        view_hints=ViewHints(lane=layer, stage="processing", width=width, height=height),
    )


def _format_view_text(template: Any, tokens: dict[str, str]) -> str:
    text = str(template or "")
    for key, value in tokens.items():
        text = text.replace("{" + key + "}", value)
    return text


def _token_value(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, str):
        return tokens.get(value, _format_view_text(value, tokens))
    return value


def _operation_from_spec(spec: dict[str, Any], tokens: dict[str, str]) -> OperationSummary | None:
    raw = spec.get("operations") or {}
    if not raw:
        return None
    return OperationSummary(
        crop=bool(raw.get("crop", False)),
        crop_ratio=raw.get("crop_ratio"),
        scale=bool(raw.get("scale", False)),
        scale_from=_token_value(raw.get("scale_from"), tokens),
        scale_to=_token_value(raw.get("scale_to"), tokens),
        rotate=raw.get("rotate"),
        compose=bool(raw.get("compose", False)),
        colorspace_convert=raw.get("colorspace_convert"),
    )


def _buffer_memory_from_spec(
    graph: CanonicalScenarioGraph,
    buffer_ref: str | None,
    tokens: dict[str, str],
) -> MemoryDescriptor | None:
    if not buffer_ref:
        return None
    spec = _buffer_spec(graph, buffer_ref)
    if not spec:
        return _memory_descriptor(graph, buffer_ref)
    size_ref = spec.get("size_ref")
    width, height = _parse_size(tokens.get(str(size_ref), str(size_ref)))
    return MemoryDescriptor(
        format=spec.get("format"),
        bitdepth=spec.get("bitdepth"),
        planes=spec.get("planes"),
        width=width,
        height=height,
        fps=int(tokens.get("fps", "30")),
        alignment=spec.get("alignment"),
        compression=None if spec.get("compression") == "none" else spec.get("compression"),
    )


def _buffer_placement_from_spec(graph: CanonicalScenarioGraph, buffer_ref: str | None) -> MemoryPlacement | None:
    if not buffer_ref:
        return None
    spec = _buffer_spec(graph, buffer_ref)
    if spec and spec.get("placement"):
        return MemoryPlacement(**spec["placement"])
    return _memory_placement(graph, buffer_ref)


def _buffer_spec(graph: CanonicalScenarioGraph, buffer_ref: str) -> dict[str, Any]:
    base = ((graph.scenario.pipeline or {}).get("buffers") or {}).get(buffer_ref) or {}
    override = (getattr(graph.variant, "buffer_overrides", None) or {}).get(buffer_ref) or {}
    return _deep_merge(base, override)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _node_detail_items(
    graph: CanonicalScenarioGraph,
    node_id: str | None,
    pipeline_node: dict[str, Any] | None = None,
) -> list[str]:
    if not node_id:
        return []
    config = (getattr(graph.variant, "node_configs", None) or {}).get(node_id) or {}
    details: list[str] = []
    if pipeline_node:
        role = pipeline_node.get("role")
        if role:
            details.append(f"Role: {role}")
    if not isinstance(config, dict) or not config:
        return details

    kind = config.get("kind") or config.get("type")
    if kind:
        details.append(f"Variant config: {kind}")
    mode = config.get("mode")
    if mode:
        details.append(f"Mode: {mode}")
    if kind == "sw_task" or config.get("processor") or config.get("duration_ms") is not None:
        details.append(_sw_task_summary(config))

    input_summary = _port_summary(config.get("inputs"))
    if input_summary:
        details.append("Inputs: " + input_summary)
    output_summary = _port_summary(config.get("outputs"))
    if output_summary:
        details.append("Outputs: " + output_summary)
    return details


def _task_node_detail_items(
    graph: CanonicalScenarioGraph,
    node_id: str,
    node_spec: dict[str, Any],
) -> list[str]:
    details = _node_detail_items(graph, node_id, node_spec)
    if node_spec.get("buffer"):
        details.extend(_buffer_detail_items(graph, str(node_spec["buffer"])))
    return details


def _edge_detail_items(
    graph: CanonicalScenarioGraph,
    edge: dict[str, Any],
    buffer_ref: str | None,
) -> list[str]:
    details: list[str] = []
    source = edge.get("from") or edge.get("source")
    target = edge.get("to") or edge.get("target")
    if source and target:
        details.append(f"Route: {source} -> {target}")
    edge_type = edge.get("type")
    if edge_type:
        details.append(f"Edge type: {edge_type}")
    if buffer_ref:
        details.extend(_buffer_detail_items(graph, buffer_ref))
    return details


def _buffer_detail_items(graph: CanonicalScenarioGraph, buffer_ref: str | None) -> list[str]:
    if not buffer_ref:
        return []
    spec = _buffer_spec(graph, buffer_ref)
    override = (getattr(graph.variant, "buffer_overrides", None) or {}).get(buffer_ref) or {}
    details: list[str] = []
    if override:
        details.append("Buffer override: variant-specific")
    if spec:
        bits = [
            spec.get("format"),
            _size_text(spec.get("size_ref") or spec.get("size")),
            f"{spec.get('bitdepth')}b" if spec.get("bitdepth") is not None else None,
            spec.get("compression"),
            spec.get("alignment"),
        ]
        summary = " / ".join(str(bit) for bit in bits if bit)
        if summary:
            details.append(f"Buffer: {summary}")
        placement = spec.get("placement") or {}
        if placement:
            details.append("Placement: " + _placement_summary(placement))
    return details


def _sw_task_summary(config: dict[str, Any]) -> str:
    bits = [
        config.get("name") or config.get("group") or "SW task",
        config.get("processor"),
        f"{config.get('duration_ms')}ms" if config.get("duration_ms") is not None else None,
    ]
    return "SW task: " + " / ".join(str(bit) for bit in bits if bit)


def _port_summary(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    items: list[str] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        bits = [
            item.get("port"),
            _size_text(item.get("size")),
            item.get("format"),
            f"{item.get('bitwidth')}b" if item.get("bitwidth") is not None else None,
            item.get("comp"),
        ]
        items.append(" ".join(str(bit) for bit in bits if bit))
    if len(value) > 3:
        items.append(f"+{len(value) - 3} more")
    return "; ".join(items) if items else None


def _size_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) >= 4:
        return f"{value[2]}x{value[3]}"
    if isinstance(value, dict):
        width = value.get("width")
        height = value.get("height")
        if width and height:
            return f"{width}x{height}"
    return None


def _placement_summary(placement: dict[str, Any]) -> str:
    if placement.get("llc_allocated") is True:
        mb = placement.get("llc_allocation_mb")
        policy = placement.get("llc_policy") or "llc"
        owner = placement.get("allocation_owner")
        return "LLC " + " ".join(str(part) for part in (f"{mb}MB" if mb else None, policy, owner) if part)
    return ", ".join(f"{key}={value}" for key, value in placement.items())


def _task_node_from_spec(
    graph: CanonicalScenarioGraph,
    spec: dict[str, Any],
    tokens: dict[str, str],
    override: dict[str, Any] | None = None,
) -> NodeElement:
    merged = dict(spec)
    if override:
        merged.update(override)
    layer = str(merged.get("layer") or "hw")
    return _ref_task_node(
        str(merged["id"]),
        _format_view_text(merged.get("label") or merged["id"], tokens),
        float(merged.get("x", 0)),
        float(merged.get("y", 0)),
        layer=layer,
        width=int(merged.get("width") or 132),
        height=int(merged.get("height") or 52),
        ip_ref=merged.get("ip_ref"),
        badges=list(merged.get("badges") or []),
        ops=_operation_from_spec(merged, tokens),
        memory=_buffer_memory_from_spec(graph, merged.get("buffer"), tokens),
        placement=_buffer_placement_from_spec(graph, merged.get("buffer")),
        detail_items=_task_node_detail_items(graph, str(merged["id"]), merged),
    )


def _flow_type_from_spec(value: Any) -> str:
    text = str(value or "M2M")
    if text in {"OTF", "vOTF", "M2M", "control", "risk"}:
        return text
    lowered = text.lower()
    if lowered == "otf":
        return "OTF"
    if lowered == "votf":
        return "vOTF"
    if lowered in {"sw", "control"}:
        return "control"
    return "M2M"


def _task_edges_from_spec(
    graph: CanonicalScenarioGraph,
    specs: list[dict[str, Any]],
    tokens: dict[str, str],
    prefix: str,
) -> list[EdgeElement]:
    edges: list[EdgeElement] = []
    for idx, spec in enumerate(specs):
        buffer_ref = spec.get("buffer")
        edges.append(
            _e(
                str(spec.get("id") or f"{prefix}-{idx}"),
                str(spec.get("from")),
                str(spec.get("to")),
                _flow_type_from_spec(spec.get("type")),
                label=_format_view_text(spec.get("label") or spec.get("type") or "", tokens),
                buffer_ref=buffer_ref,
                memory=_buffer_memory_from_spec(graph, buffer_ref, tokens),
                placement=_buffer_placement_from_spec(graph, buffer_ref),
                detail_items=_edge_detail_items(graph, spec, buffer_ref),
            )
        )
    return edges


def _visible_task_node_specs(
    graph: CanonicalScenarioGraph,
    specs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    disabled = set(((getattr(graph.variant, "routing_switch", None) or {}).get("disabled_nodes") or []))
    visible = [spec for spec in specs if str(spec.get("id")) not in disabled]
    return visible, {str(spec.get("id")) for spec in visible}


def _visible_task_edge_specs(
    graph: CanonicalScenarioGraph,
    specs: list[dict[str, Any]],
    visible_node_ids: set[str],
) -> list[dict[str, Any]]:
    routing = getattr(graph.variant, "routing_switch", None) or {}
    patch = getattr(graph.variant, "topology_patch", None) or {}
    remove_specs = [
        *(routing.get("disabled_edges") or []),
        *(patch.get("remove_edges") or []),
    ]
    return [
        spec
        for spec in specs
        if str(spec.get("from")) in visible_node_ids
        and str(spec.get("to")) in visible_node_ids
        and not _task_edge_removed(spec, remove_specs)
    ]


def _task_edge_removed(edge: dict[str, Any], remove_specs: list[Any]) -> bool:
    return any(isinstance(spec, dict) and _task_edge_matches(edge, spec) for spec in remove_specs)


def _task_edge_matches(edge: dict[str, Any], spec: dict[str, Any]) -> bool:
    spec_id = spec.get("id")
    if spec_id and spec_id == edge.get("id"):
        return True
    if edge.get("from") != spec.get("from") or edge.get("to") != spec.get("to"):
        return False
    for field in ("type", "buffer"):
        if spec.get(field) is not None and edge.get(field) is not None and edge.get(field) != spec.get(field):
            return False
    return True


def _project_task_graph_from_fixture(
    graph: CanonicalScenarioGraph,
    *,
    level: int,
    mode: str,
) -> ViewResponse | None:
    spec = (graph.scenario.pipeline or {}).get("task_graph") or {}
    task_nodes, visible_node_ids = _visible_task_node_specs(graph, spec.get("nodes") or [])
    if not task_nodes:
        return None
    tokens = _reference_sizes(graph)
    nodes = [_task_node_from_spec(graph, node_spec, tokens) for node_spec in task_nodes]
    edge_specs = _visible_task_edge_specs(graph, spec.get("edges") or [], visible_node_ids)
    edges = _task_edges_from_spec(graph, edge_specs, tokens, "task-edge")
    max_y = max((node.position["y"] for node in nodes), default=600)
    return _response(
        graph=graph,
        level=level,
        mode=mode,
        nodes=nodes,
        edges=edges,
        metadata={
            "canvas_w": 1100,
            "canvas_h": max(760, int(max_y + 160)),
            "layout": str(spec.get("layout") or "task-topology"),
        },
    )


def _project_level1_from_fixture(graph: CanonicalScenarioGraph) -> ViewResponse | None:
    level1 = (graph.scenario.pipeline or {}).get("level1_graph") or {}
    task_graph = (graph.scenario.pipeline or {}).get("task_graph") or {}
    task_nodes, visible_node_ids = _visible_task_node_specs(graph, task_graph.get("nodes") or [])
    if not level1 or not task_nodes:
        return None
    tokens = _reference_sizes(graph)
    overrides = level1.get("node_overrides") or {}
    nodes = [
        _group_box(
            str(group["id"]),
            _format_view_text(group.get("label") or group["id"], tokens),
            float(group.get("x", 0)),
            float(group.get("y", 0)),
            int(group.get("width") or 200),
            int(group.get("height") or 120),
        )
        for group in level1.get("groups") or []
    ]
    for node_spec in task_nodes:
        node_id = str(node_spec.get("id"))
        override = overrides.get(node_id)
        if override is None and not level1.get("nodes_from_task_graph", False):
            continue
        nodes.append(_task_node_from_spec(graph, node_spec, tokens, override))

    edge_specs = _visible_task_edge_specs(graph, task_graph.get("edges") or [], visible_node_ids)
    edges = _task_edges_from_spec(graph, edge_specs, tokens, "level1-edge")
    return _response(
        graph=graph,
        level=1,
        mode="level1-ip-detail",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1180, "canvas_h": 1370, "layout": "level1-reference"},
    )


def _group_box(node_id: str, label: str, x: float, y: float, width: int, height: int) -> NodeElement:
    return _n(
        node_id,
        label,
        "submodule",
        "meta",
        x,
        y,
        view_hints=ViewHints(width=width, height=height, emphasis="muted"),
    )


def _detail_node(
    node_id: str,
    label: str,
    node_type: str,
    layer: str,
    x: float,
    y: float,
    *,
    width: int = 132,
    height: int = 52,
    ip_ref: str | None = None,
    sw_ref: str | None = None,
    badges: list[str] | None = None,
    ops: OperationSummary | None = None,
    memory: MemoryDescriptor | None = None,
    placement: MemoryPlacement | None = None,
    dma_count: int | None = None,
    shared_resource: bool = False,
    warning: bool = False,
    detail_items: list[str] | None = None,
) -> NodeElement:
    return _n(
        node_id,
        label,
        node_type,
        layer,
        x,
        y,
        ip_ref=ip_ref,
        sw_ref=sw_ref,
        summary_badges=["task"],
        capability_badges=badges or [],
        active_operations=ops,
        memory=memory,
        placement=placement,
        dma_count=dma_count,
        shared_resource=shared_resource,
        warning=warning,
        detail_items=detail_items or [],
        view_hints=ViewHints(width=width, height=height),
    )


def _detail_buffer(
    graph: CanonicalScenarioGraph,
    node_id: str,
    label: str,
    buffer_ref: str,
    x: float,
    y: float,
    tokens: dict[str, str],
    *,
    width: int = 190,
    height: int = 58,
) -> NodeElement:
    memory = _buffer_memory_from_spec(graph, buffer_ref, tokens)
    placement = _buffer_placement_from_spec(graph, buffer_ref)
    suffix: list[str] = []
    if memory:
        fmt = memory.format or "buffer"
        size = f"{memory.width}x{memory.height}" if memory.width and memory.height else None
        suffix.extend([part for part in (fmt, size, memory.compression) if part])
    if placement and placement.llc_allocated:
        suffix.append(f"LLC {placement.llc_allocation_mb or '?'}MB")
    return _detail_node(
        node_id,
        f"{label}\n" + " | ".join(suffix),
        "buffer",
        "memory",
        x,
        y,
        width=width,
        height=height,
        memory=memory,
        placement=placement,
        detail_items=_buffer_detail_items(graph, buffer_ref),
    )


def _project_level2_reference(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse | None:
    normalized = str(expand or "").strip().lower()
    if normalized in {"camera", "cam", "csis", "isp", "camera-pipeline", "camera_pipeline"}:
        return _project_level2_camera(graph, "camera")
    if normalized in {"video", "codec", "mfc", "encode", "encoder"}:
        return _project_level2_video(graph, "video")
    if normalized in {"display", "dpu", "decon"}:
        return _project_level2_display(graph, "display")
    return None


def _project_level2_camera(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    tokens = _reference_sizes(graph)
    sensor = tokens["sensor_full"]
    record = tokens["record_out"]
    preview = tokens["preview_out"]
    fps = tokens["fps"]

    nodes = [
        _group_box("l2cam-grp-sw", "SW Control / Task Scheduling", 245, 220, 360, 320),
        _group_box("l2cam-grp-csis", "Camera Frontend (CSIS)", 705, 220, 430, 320),
        _group_box("l2cam-grp-isp", "ISP Processing Core", 680, 620, 760, 620),
        _group_box("l2cam-grp-dma", "DMA / SystemMMU / Memory Ports", 1160, 620, 420, 620),
        _group_box("l2cam-grp-memory", "Frame Buffers / Memory Placement", 710, 1135, 900, 250),
        _group_box("l2cam-grp-downstream", "Downstream Consumers", 1190, 1135, 360, 250),
        _detail_node("l2cam-app", "Camera App", "sw", "app", 160, 115, width=150, height=48),
        _detail_node("l2cam-fw", "CameraService", "sw", "framework", 160, 185, width=165, height=48),
        _detail_node("l2cam-hal", "Camera HAL", "sw", "hal", 160, 255, width=150, height=48),
        _detail_node("l2cam-v4l2", "V4L2 Camera Driver", "sw", "kernel", 160, 335, width=180, height=50),
        _detail_node("l2cam-postirta", "postIRTA\nCPU_MID_Cluster", "sw", "kernel", 330, 255, width=170, height=54),
        _detail_node("l2cam-postirta2", "postIRTA2\nCPU_MID_Cluster", "sw", "kernel", 330, 335, width=170, height=54),
        _detail_node("l2cam-sensor", f"Sensor\n{sensor}@{fps}fps", "ip", "hw", 560, 115, width=150, height=58),
        _detail_node("l2cam-csislink", f"CSIS_LINK\n{sensor}", "submodule", "hw", 705, 195, width=150, height=54, ip_ref="ip-csis-v8"),
        _detail_node("l2cam-csis", f"CSIS\n{sensor}", "submodule", "hw", 705, 285, width=150, height=54, ip_ref="ip-csis-v8"),
        _detail_node("l2cam-pdp", f"PDP\n{sensor}", "submodule", "hw", 400, 455, width=136, height=52),
        _detail_node("l2cam-prep", f"PREP\n{sensor}", "submodule", "hw", 580, 455, width=136, height=52),
        _detail_node(
            "l2cam-cstat",
            f"CSTAT\n{sensor}->{record}",
            "submodule",
            "hw",
            760,
            455,
            width=190,
            height=64,
            badges=["CROP", "SCALE"],
            ops=OperationSummary(crop=True, scale=True, scale_from=sensor, scale_to=record),
        ),
        _detail_node("l2cam-byrp", f"BYRP\n{sensor}", "submodule", "hw", 400, 575, width=136, height=52),
        _detail_node("l2cam-rgbp", f"RGBP\n{sensor}", "submodule", "hw", 580, 575, width=136, height=52),
        _detail_node(
            "l2cam-mlsc",
            f"MLSC\n{sensor}->{record}",
            "submodule",
            "hw",
            760,
            575,
            width=190,
            height=64,
            badges=["SCALE", "CSC"],
            ops=OperationSummary(scale=True, scale_from=sensor, scale_to=record, colorspace_convert="RAW->YUV"),
        ),
        _detail_node("l2cam-mtnr1", f"MTNR1\n{preview}", "submodule", "hw", 400, 725, width=136, height=52),
        _detail_node("l2cam-mtnr0", f"MTNR0\n{record}", "submodule", "hw", 580, 725, width=136, height=52),
        _detail_node("l2cam-msnr", f"MSNR\n{record}", "submodule", "hw", 760, 725, width=136, height=52),
        _detail_node("l2cam-yuvp", f"YUVP\n{record}", "submodule", "hw", 580, 865, width=136, height=52),
        _detail_node(
            "l2cam-mcsc",
            f"MCSC\n{record}/{preview}",
            "submodule",
            "hw",
            760,
            865,
            width=190,
            height=64,
            badges=["SCALE"],
            ops=OperationSummary(scale=True, scale_from=record, scale_to=preview),
        ),
        _detail_node("l2cam-dma-csis", "CSIS_WDMA\nBAYER_PACKED 12b", "dma_channel", "hw", 1070, 340, width=190, height=54, dma_count=1),
        _detail_node("l2cam-dma-comp", "COMP_RD0_RDMA\nRAW COMP read", "dma_channel", "hw", 1240, 465, width=190, height=54, dma_count=1),
        _detail_node("l2cam-dma-p0", "P0_WDMA\nRecord path", "dma_channel", "hw", 1070, 720, width=160, height=54, dma_count=1),
        _detail_node("l2cam-dma-p1", "P1_WDMA\nPreview path", "dma_channel", "hw", 1240, 720, width=160, height=54, dma_count=1),
        _detail_node("l2cam-sysmmu", "SYSMMU_CAM\nshared S2MPU path", "sysmmu", "hw", 1160, 895, width=200, height=58, shared_resource=True),
        _detail_buffer(graph, "l2cam-rawbuf", "RAW Bayer", "RAW_BAYER_MAIN", 430, 1125, tokens),
        _detail_buffer(graph, "l2cam-recbuf", "Encoder Input", "RECORD_BUF", 710, 1125, tokens),
        _detail_buffer(graph, "l2cam-prevbuf", "Preview", "PREVIEW_BUF", 990, 1125, tokens),
        _detail_node("l2cam-mfc", f"MFC\n{record}", "ip", "hw", 1120, 1125, width=130, height=58, ip_ref="ip-mfc-v14"),
        _detail_node("l2cam-dpu", f"DPU\n{preview}", "ip", "hw", 1280, 1125, width=130, height=58, ip_ref="ip-dpu-v9"),
    ]
    edges = [
        _e("l2cam-sw-0", "l2cam-app", "l2cam-fw", "control", label="SW"),
        _e("l2cam-sw-1", "l2cam-fw", "l2cam-hal", "control", label="Camera API"),
        _e("l2cam-sw-2", "l2cam-hal", "l2cam-v4l2", "control", label="V4L2"),
        _e("l2cam-sw-3", "l2cam-v4l2", "l2cam-csis", "control", label="subdev routing"),
        _e("l2cam-sw-4", "l2cam-mlsc", "l2cam-postirta", "control", label="SW"),
        _e("l2cam-sw-5", "l2cam-postirta", "l2cam-postirta2", "control", label="SW"),
        _e("l2cam-sw-6", "l2cam-postirta2", "l2cam-mtnr1", "control", label="TNR schedule"),
        _e("l2cam-sw-7", "l2cam-postirta2", "l2cam-mtnr0", "control", label="TNR schedule"),
        _e("l2cam-otf-0", "l2cam-sensor", "l2cam-csislink", "OTF", label="MIPI CSI"),
        _e("l2cam-otf-1", "l2cam-csislink", "l2cam-csis", "OTF", label="LINK->NFI_DEC"),
        _e("l2cam-otf-2", "l2cam-csis", "l2cam-pdp", "OTF", label="IBUF->REORDER"),
        _e("l2cam-otf-3", "l2cam-csis", "l2cam-prep", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-otf-4", "l2cam-prep", "l2cam-cstat", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-m2m-0", "l2cam-csis", "l2cam-dma-csis", "M2M", label=f"CSIS_WDMA | {sensor}", buffer_ref="RAW_BAYER_MAIN", memory=_buffer_memory_from_spec(graph, "RAW_BAYER_MAIN", tokens), placement=_buffer_placement_from_spec(graph, "RAW_BAYER_MAIN")),
        _e("l2cam-m2m-1", "l2cam-dma-csis", "l2cam-rawbuf", "M2M", label="write RAW"),
        _e("l2cam-m2m-2", "l2cam-rawbuf", "l2cam-dma-comp", "M2M", label="COMP_RD0_RDMA"),
        _e("l2cam-m2m-3", "l2cam-dma-comp", "l2cam-byrp", "M2M", label="read RAW COMP"),
        _e("l2cam-otf-5", "l2cam-byrp", "l2cam-rgbp", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-otf-6", "l2cam-rgbp", "l2cam-mlsc", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-otf-7", "l2cam-mtnr1", "l2cam-msnr", "OTF", label="L1/L2/L3/G4"),
        _e("l2cam-otf-8", "l2cam-mtnr0", "l2cam-msnr", "OTF", label="L0"),
        _e("l2cam-otf-9", "l2cam-msnr", "l2cam-yuvp", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-otf-10", "l2cam-yuvp", "l2cam-mcsc", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-m2m-4", "l2cam-mcsc", "l2cam-dma-p0", "M2M", label=f"P0_WDMA | {record} | YUV420 | 10b", buffer_ref="RECORD_BUF", memory=_buffer_memory_from_spec(graph, "RECORD_BUF", tokens), placement=_buffer_placement_from_spec(graph, "RECORD_BUF")),
        _e("l2cam-m2m-5", "l2cam-mcsc", "l2cam-dma-p1", "M2M", label=f"P1_WDMA | {preview} | YUV420 | 10b", buffer_ref="PREVIEW_BUF", memory=_buffer_memory_from_spec(graph, "PREVIEW_BUF", tokens), placement=_buffer_placement_from_spec(graph, "PREVIEW_BUF")),
        _e("l2cam-m2m-6", "l2cam-dma-p0", "l2cam-sysmmu", "M2M", label="SMMU translate"),
        _e("l2cam-m2m-7", "l2cam-dma-p1", "l2cam-sysmmu", "M2M", label="SMMU translate"),
        _e("l2cam-m2m-8", "l2cam-sysmmu", "l2cam-recbuf", "M2M", label="write record"),
        _e("l2cam-m2m-9", "l2cam-sysmmu", "l2cam-prevbuf", "M2M", label="write preview"),
        _e("l2cam-m2m-10", "l2cam-recbuf", "l2cam-mfc", "M2M", label="encoder input"),
        _e("l2cam-m2m-11", "l2cam-prevbuf", "l2cam-dpu", "M2M", label="display input"),
    ]
    return _response(
        graph=graph,
        level=2,
        mode="drilldown:camera",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1380, "canvas_h": 1290, "layout": "level2-camera-detail", "expand": expand},
    )


def _project_level2_video(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    tokens = _reference_sizes(graph)
    record = tokens["record_out"]
    codec = tokens["codec"]
    nodes = [
        _group_box("l2vid-grp-sw", "SW Encode Stack", 260, 220, 420, 330),
        _group_box("l2vid-grp-mfc", "MFC Hardware Pipeline", 760, 260, 560, 420),
        _group_box("l2vid-grp-memory", "DMA / SystemMMU / Bitstream Memory", 760, 720, 760, 300),
        _detail_node("l2vid-app", "Recorder App", "sw", "app", 150, 115, width=160, height=48),
        _detail_node("l2vid-fw", "MediaRecorder", "sw", "framework", 150, 195, width=170, height=48),
        _detail_node("l2vid-hal", "Codec2 HAL", "sw", "hal", 150, 275, width=155, height=48),
        _detail_node("l2vid-driver", "MFC Driver", "sw", "kernel", 150, 355, width=155, height=48),
        _detail_node("l2vid-mfc", f"MFC Frontend\n{codec}", "ip", "hw", 560, 165, width=160, height=60, ip_ref="ip-mfc-v14", badges=[codec, "ENC"]),
        _detail_node("l2vid-rdma", f"MFC_RDMA\n{record}", "dma_channel", "hw", 760, 165, width=155, height=56, dma_count=1),
        _detail_node("l2vid-core", f"MFC_CORE\n{codec} encode", "submodule", "hw", 760, 315, width=170, height=62, ip_ref="ip-mfc-v14"),
        _detail_node("l2vid-wdma", "MFC_WDMA\nbitstream write", "dma_channel", "hw", 960, 315, width=170, height=56, dma_count=1),
        _detail_node("l2vid-sysmmu", "SYSMMU_MFC\nLLC-aware mapping", "sysmmu", "hw", 760, 585, width=210, height=60, shared_resource=True),
        _detail_buffer(graph, "l2vid-recbuf", "Encoder Input", "RECORD_BUF", 520, 720, tokens, width=210),
        _detail_buffer(graph, "l2vid-bitstream", "Encoded Bitstream", "ENCODED_BITSTREAM", 880, 720, tokens, width=230),
    ]
    edges = [
        _e("l2vid-sw-0", "l2vid-app", "l2vid-fw", "control", label="Media API"),
        _e("l2vid-sw-1", "l2vid-fw", "l2vid-hal", "control", label="Codec2"),
        _e("l2vid-sw-2", "l2vid-hal", "l2vid-driver", "control", label="ioctl / queue"),
        _e("l2vid-sw-3", "l2vid-driver", "l2vid-mfc", "control", label="register programming"),
        _e("l2vid-m2m-0", "l2vid-recbuf", "l2vid-rdma", "M2M", label=f"read {record} YUV420", buffer_ref="RECORD_BUF", memory=_buffer_memory_from_spec(graph, "RECORD_BUF", tokens), placement=_buffer_placement_from_spec(graph, "RECORD_BUF")),
        _e("l2vid-otf-0", "l2vid-rdma", "l2vid-mfc", "OTF", label="input stream"),
        _e("l2vid-otf-1", "l2vid-mfc", "l2vid-core", "OTF", label="encode pipe"),
        _e("l2vid-otf-2", "l2vid-core", "l2vid-wdma", "OTF", label="coded output"),
        _e("l2vid-m2m-1", "l2vid-wdma", "l2vid-sysmmu", "M2M", label="SMMU translate"),
        _e("l2vid-m2m-2", "l2vid-sysmmu", "l2vid-bitstream", "M2M", label="write bitstream", buffer_ref="ENCODED_BITSTREAM", memory=_buffer_memory_from_spec(graph, "ENCODED_BITSTREAM", tokens), placement=_buffer_placement_from_spec(graph, "ENCODED_BITSTREAM")),
    ]
    return _response(
        graph=graph,
        level=2,
        mode="drilldown:video",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1180, "canvas_h": 920, "layout": "level2-video-detail", "expand": expand},
    )


def _project_level2_display(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    tokens = _reference_sizes(graph)
    preview = tokens["preview_out"]
    nodes = [
        _group_box("l2disp-grp-sw", "Display SW Stack", 260, 220, 420, 330),
        _group_box("l2disp-grp-dpu", "DPU / DECON / Panel Path", 760, 270, 560, 440),
        _group_box("l2disp-grp-memory", "DMA / SystemMMU / Display Buffer", 760, 750, 760, 300),
        _detail_node("l2disp-sf", "SurfaceFlinger", "sw", "framework", 150, 135, width=170, height=48),
        _detail_node("l2disp-hwc", "HW Composer", "sw", "hal", 150, 225, width=170, height=48),
        _detail_node("l2disp-drm", "DRM / KMS", "sw", "kernel", 150, 315, width=150, height=48),
        _detail_node("l2disp-rdma", f"DPU_RDMA\n{preview}", "dma_channel", "hw", 560, 210, width=160, height=56, dma_count=1),
        _detail_node("l2disp-decon", "DECON\ncompose", "submodule", "hw", 760, 210, width=160, height=56, ops=OperationSummary(compose=True)),
        _detail_node("l2disp-dpu", f"DPU\n{preview}", "ip", "hw", 760, 370, width=150, height=58, ip_ref="ip-dpu-v9", ops=OperationSummary(compose=True)),
        _detail_node("l2disp-dsi", "DSI / Panel\nscanout", "submodule", "hw", 960, 370, width=160, height=58),
        _detail_node("l2disp-sysmmu", "SYSMMU_DPU\nread path", "sysmmu", "hw", 760, 610, width=200, height=58, shared_resource=True),
        _detail_buffer(graph, "l2disp-prevbuf", "Preview Buffer", "PREVIEW_BUF", 560, 750, tokens, width=220),
        _detail_node("l2disp-panel", "Display Panel\nscanout endpoint", "ip", "hw", 960, 750, width=190, height=58),
    ]
    edges = [
        _e("l2disp-sw-0", "l2disp-sf", "l2disp-hwc", "control", label="composition request"),
        _e("l2disp-sw-1", "l2disp-hwc", "l2disp-drm", "control", label="atomic commit"),
        _e("l2disp-sw-2", "l2disp-drm", "l2disp-dpu", "control", label="KMS"),
        _e("l2disp-m2m-0", "l2disp-prevbuf", "l2disp-sysmmu", "M2M", label="read preview buffer", buffer_ref="PREVIEW_BUF", memory=_buffer_memory_from_spec(graph, "PREVIEW_BUF", tokens), placement=_buffer_placement_from_spec(graph, "PREVIEW_BUF")),
        _e("l2disp-m2m-1", "l2disp-sysmmu", "l2disp-rdma", "M2M", label="translated read"),
        _e("l2disp-otf-0", "l2disp-rdma", "l2disp-decon", "OTF", label="pixel stream"),
        _e("l2disp-otf-1", "l2disp-decon", "l2disp-dpu", "OTF", label="compose"),
        _e("l2disp-otf-2", "l2disp-dpu", "l2disp-dsi", "OTF", label="DSI"),
        _e("l2disp-otf-3", "l2disp-dsi", "l2disp-panel", "OTF", label="scanout"),
    ]
    return _response(
        graph=graph,
        level=2,
        mode="drilldown:display",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1180, "canvas_h": 950, "layout": "level2-display-detail", "expand": expand},
    )


def _project_reference_task_topology(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    """Reference task DAG shaped after the legacy projectA FHD30 topology view.

    The current canonical fixture is intentionally shallow, so this projection
    expands a camera-recording usecase into the task-level chain the legacy
    viewer made useful: HW tasks, SW/CPU tasks, OTF links, and M2M buffer edges.
    """
    from_fixture = _project_task_graph_from_fixture(graph, level=level, mode="topology")
    if from_fixture is not None:
        return from_fixture

    sz = _reference_sizes(graph)
    sensor = sz["sensor"]
    record = sz["record"]
    preview = sz["preview"]
    fps = sz["fps"]
    codec = sz["codec"]

    nodes = [
        _ref_task_node("t_sensor", f"t_sensor\n(Sensor)\n{sensor}@{fps}", 520, 70, width=150, height=60),
        _ref_task_node("t_csislink", f"t_csislink\n(CSIS_LINK)\n{sensor}", 520, 170),
        _ref_task_node("t_csis", f"t_csis\n(CSIS)\n{sensor}", 520, 270, ip_ref="ip-csis-v8"),
        _ref_task_node("t_pdp", f"t_pdp\n(PDP)\n{sensor}", 300, 390),
        _ref_task_node("t_prep", f"t_prep\n(PREP)\n{sensor}", 705, 390),
        _ref_task_node(
            "t_cstat",
            f"t_cstat\n(CSTAT)\n{sensor}->{record}",
            705,
            520,
            width=184,
            height=66,
            badges=["S", "C"],
            ops=OperationSummary(crop=True, scale=True, scale_from=sensor, scale_to=record),
        ),
        _ref_task_node("t_byrp", f"t_byrp\n(BYRP)\n{sensor}", 520, 405),
        _ref_task_node("t_rgbp", f"t_rgbp\n(RGBP)\n{sensor}", 520, 520),
        _ref_task_node(
            "t_mlsc",
            f"t_mlsc\n(MLSC)\n{sensor}->{record}",
            520,
            660,
            width=184,
            height=66,
            badges=["S", "C"],
            ops=OperationSummary(scale=True, scale_from=sensor, scale_to=record),
        ),
        _ref_task_node("t_postIRTA", "t_postIRTA\n(CPU_MID_Cluster)", 520, 805, layer="kernel", width=180, height=52),
        _ref_task_node("t_postIRTA2", "t_postIRTA2\n(CPU_MID_Cluster)", 520, 925, layer="kernel", width=180, height=52),
        _ref_task_node("t_mtnr1", f"t_mtnr1\n(MTNR1)\n{preview}", 390, 1060),
        _ref_task_node("t_mtnr0", f"t_mtnr0\n(MTNR0)\n{record}", 650, 1060),
        _ref_task_node("t_msnr", f"t_msnr\n(MSNR)\n{record}", 520, 1205),
        _ref_task_node("t_yuvp", f"t_yuvp\n(YUVP)\n{record}", 520, 1340),
        _ref_task_node("t_mcsc", f"t_mcsc\n(MCSC)\n{record}", 520, 1480, ops=OperationSummary(scale=True, scale_to=record)),
        _ref_task_node("t_codec2", "t_codec2\n(CPU_MID_Cluster)", 430, 1640, layer="kernel", width=180, height=52),
        _ref_task_node("t_hw_composer", "t_hw_composer\n(CPU_MID_Cluster)", 650, 1640, layer="kernel", width=190, height=52),
        _ref_task_node("t_mfc", f"t_mfc\n(MFC)\n{record}", 430, 1790, ip_ref="ip-mfc-v14"),
        _ref_task_node("t_dpu", f"t_dpu\n(DPU)\n{preview}", 650, 1790, ip_ref="ip-dpu-v9"),
    ]

    edges = [
        _e("eo-0", "t_sensor", "t_csislink", "OTF", label="OTF"),
        _e("eo-1", "t_csislink", "t_csis", "OTF", label="OTF: LINK->NFI_DEC"),
        _e("eo-2", "t_csis", "t_pdp", "OTF", label="OTF: IBUF->REORDER"),
        _e("eo-3", "t_csis", "t_prep", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("em-4", "t_csis", "t_byrp", "M2M", label=f"CSIS_WDMA->COMP_RD0_RDMA | {sensor} | BAYER_PACKED | 12bit | COMP"),
        _e("eo-5", "t_prep", "t_cstat", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("eo-6", "t_byrp", "t_rgbp", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("eo-7", "t_rgbp", "t_mlsc", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("esw-8", "t_mlsc", "t_postIRTA", "control", label="SW"),
        _e("esw-9", "t_postIRTA", "t_postIRTA2", "control", label="SW"),
        _e("esw-10", "t_postIRTA2", "t_mtnr1", "control", label="SW"),
        _e("esw-11", "t_postIRTA2", "t_mtnr0", "control", label="SW"),
        _e("eo-12", "t_mtnr0", "t_msnr", "OTF", label="OTF: L0_COUTFIFO->L0_CINFIFO"),
        _e("eo-13", "t_mtnr1", "t_msnr", "OTF", label="OTF: L1/L2/L3/G4 COUTFIFO->CINFIFO"),
        _e("eo-14", "t_msnr", "t_yuvp", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("eo-15", "t_yuvp", "t_mcsc", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("em-16", "t_mcsc", "t_codec2", "M2M", label=f"P0_WDMA->input | {record} | YUV420 | 10bit"),
        _e("em-17", "t_mcsc", "t_hw_composer", "M2M", label=f"P1_WDMA->input | {preview} | YUV420 | 10bit"),
        _e("esw-18", "t_codec2", "t_mfc", "control", label="SW"),
        _e("esw-19", "t_hw_composer", "t_dpu", "control", label="SW"),
    ]

    return _response(
        graph=graph,
        level=level,
        mode="task-topology",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1100, "canvas_h": 1880, "layout": "task-topology"},
    )


_LEVEL1_HIERARCHY_ORDER = {
    "Sensor": 0,
    "ISP": 1,
    "Compute": 2,
    "NPU": 3,
    "GPU": 4,
    "CODEC": 5,
    "DPU": 6,
    "Display": 7,
    "CPU/SW": 8,
    "Memory": 9,
    "Other": 99,
}

_LEVEL1_IP_GROUP_ORDER = {
    "Sensor": 0,
    "CSIS": 9,
    "CSIS/PDP": 10,
    "3AA/CSTAT": 20,
    "BYRP": 30,
    "RGBP": 40,
    "YUVSC": 50,
    "MTNR": 60,
    "MSNR": 70,
    "YUVP": 80,
    "MCSC": 90,
    "GDC": 100,
    "LME": 110,
    "ISP Core": 115,
    "SGPU": 120,
    "NPU": 130,
    "GPU": 140,
    "MFC": 150,
    "APV": 160,
    "DPU": 170,
    "Panel": 180,
    "CPU/SW": 190,
}
















































def _project_reference_level1(graph: CanonicalScenarioGraph) -> ViewResponse:
    """Reference Level 1 IP detail view shaped after the legacy grouped DAG."""
    from_fixture = _project_level1_from_fixture(graph)
    if from_fixture is not None:
        return from_fixture

    sz = _reference_sizes(graph)
    sensor = sz["sensor"]
    record = sz["record"]
    preview = sz["preview"]
    fps = sz["fps"]

    nodes = [
        _group_box("grp-sensor", "Sensor", 520, 85, 180, 100),
        _group_box("grp-isp", "ISP", 580, 470, 900, 620),
        _group_box("grp-cpu", "CPU", 580, 980, 520, 210),
        _group_box("grp-codec", "CODEC", 460, 1250, 190, 120),
        _group_box("grp-dpu", "DPU", 700, 1250, 190, 120),
        _ref_task_node("t_sensor", f"Sensor\n{sensor}@{fps}fps", 520, 110, width=136, height=56),
        _ref_task_node("t_csislink", f"CSIS_LINK\n{sensor}", 520, 255, width=126, height=50, ip_ref="ip-csis-v8"),
        _ref_task_node("t_csis", f"CSIS\n{sensor}", 520, 350, width=126, height=50, ip_ref="ip-csis-v8"),
        _ref_task_node("t_pdp", f"PDP\n{sensor}", 305, 470, width=126, height=50),
        _ref_task_node("t_prep", f"PREP\n{sensor}", 735, 470, width=126, height=50),
        _ref_task_node(
            "t_cstat",
            f"CSTAT\n{sensor}->{record}",
            735,
            590,
            width=170,
            height=64,
            badges=["S", "C"],
            ops=OperationSummary(crop=True, scale=True, scale_from=sensor, scale_to=record),
        ),
        _ref_task_node("t_byrp", f"BYRP\n{sensor}", 520, 470, width=126, height=50),
        _ref_task_node("t_rgbp", f"RGBP\n{sensor}", 520, 590, width=126, height=50),
        _ref_task_node(
            "t_mlsc",
            f"MLSC\n{sensor}->{record}",
            520,
            720,
            width=170,
            height=64,
            badges=["S", "C"],
            ops=OperationSummary(scale=True, scale_from=sensor, scale_to=record),
        ),
        _ref_task_node("t_mtnr1", f"MTNR1\n{preview}", 835, 280, width=126, height=50),
        _ref_task_node("t_mtnr0", f"MTNR0\n{record}", 1015, 280, width=126, height=50),
        _ref_task_node("t_msnr", f"MSNR\n{record}", 925, 430, width=126, height=50),
        _ref_task_node("t_yuvp", f"YUVP\n{record}", 925, 590, width=126, height=50),
        _ref_task_node("t_mcsc", f"MCSC\n{record}", 925, 710, width=126, height=50),
        _ref_task_node("t_postIRTA", "CPU_MID_Cluster", 390, 955, layer="kernel", width=150, height=46),
        _ref_task_node("t_postIRTA2", "CPU_MID_Cluster", 390, 1070, layer="kernel", width=150, height=46),
        _ref_task_node("t_codec2", "CPU_MID_Cluster", 580, 955, layer="kernel", width=150, height=46),
        _ref_task_node("t_hw_composer", "CPU_MID_Cluster", 770, 955, layer="kernel", width=160, height=46),
        _ref_task_node("t_mfc", f"MFC\n{record}", 460, 1305, ip_ref="ip-mfc-v14", width=130, height=58),
        _ref_task_node("t_dpu", f"DPU\n{preview}", 700, 1305, ip_ref="ip-dpu-v9", width=130, height=58),
    ]

    edges = [
        _e("l1-eo-0", "t_sensor", "t_csislink", "OTF", label="OTF"),
        _e("l1-eo-1", "t_csislink", "t_csis", "OTF", label="OTF: LINK->NFI_DEC"),
        _e("l1-eo-2", "t_csis", "t_pdp", "OTF", label="OTF: IBUF->REORDER"),
        _e("l1-eo-3", "t_csis", "t_prep", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-em-4", "t_csis", "t_byrp", "M2M", label=f"CSIS_WDMA->COMP_RD0_RDMA | {sensor} | BAYER_PACKED | 12bit | COMP"),
        _e("l1-eo-5", "t_prep", "t_cstat", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-eo-6", "t_byrp", "t_rgbp", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-eo-7", "t_rgbp", "t_mlsc", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-esw-8", "t_mlsc", "t_postIRTA", "control", label="SW"),
        _e("l1-esw-9", "t_postIRTA", "t_postIRTA2", "control", label="SW"),
        _e("l1-esw-10", "t_postIRTA2", "t_mtnr1", "control", label="SW"),
        _e("l1-esw-11", "t_postIRTA2", "t_mtnr0", "control", label="SW"),
        _e("l1-eo-12", "t_mtnr0", "t_msnr", "OTF", label="OTF: L0_COUTFIFO->L0_CINFIFO"),
        _e("l1-eo-13", "t_mtnr1", "t_msnr", "OTF", label="OTF: L1/L2/L3/G4 COUTFIFO->CINFIFO"),
        _e("l1-eo-14", "t_msnr", "t_yuvp", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-eo-15", "t_yuvp", "t_mcsc", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-em-16", "t_mcsc", "t_codec2", "M2M", label=f"P0_WDMA->input | {record} | YUV420 | 10bit"),
        _e("l1-em-17", "t_mcsc", "t_hw_composer", "M2M", label=f"P1_WDMA->input | {preview} | YUV420 | 10bit"),
        _e("l1-esw-18", "t_codec2", "t_mfc", "control", label="SW"),
        _e("l1-esw-19", "t_hw_composer", "t_dpu", "control", label="SW"),
    ]

    return _response(
        graph=graph,
        level=1,
        mode="level1-ip-detail",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1180, "canvas_h": 1370, "layout": "level1-reference"},
    )


_LEVEL2_ALIAS_GROUPS = {
    "camera": "camera",
    "cam": "camera",
    "isp": "camera",
    "camera_pipeline": "camera",
    "camera-pipeline": "camera",
    "video": "video",
    "codec": "video",
    "mfc": "video",
    "encode": "video",
    "display": "display",
    "dpu": "display",
}

_LEVEL2_BLOCK_BY_IP_GROUP = {
    "CSIS": "CSIS",
    "CSIS/PDP": "CSISPDP",
    "3AA/CSTAT": "3AA",
    "BYRP": "BYRP",
    "RGBP": "RGBP",
    "YUVSC": "YUVSC",
    "MTNR": "MTNR",
    "MSNR": "MSNR",
    "YUVP": "YUVP",
    "MCSC": "MCSC",
    "GDC": "GDC",
    "LME": "LME",
    "MFC": "MFC",
    "APV": "APV",
    "DPU": "DPU",
    "SGPU": "SGPU",
    "GPU": "GPU",
    "NPU": "NPU",
}

_LEVEL2_REQUIRED_DATA = [
    "capabilities.properties.modules for DMA/CIN/COUT module nodes",
    "capabilities.properties.subblocks or hierarchy.submodules for functional blocks",
    "capabilities.properties.internal_edges and scenario pipeline edges for module routing",
    "pipeline.buffers or variant.buffer_overrides for buffer format, compression, and LLC placement",
]


def _project_drilldown(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    from scenario_db.view.level2_semantic import project_drilldown

    return project_drilldown(graph, expand)


def _project_semantic_level2(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse | None:
    from scenario_db.view.level2_semantic import project_semantic_level2

    return project_semantic_level2(graph, expand)









def _sw_stack_nodes(graph: CanonicalScenarioGraph) -> list[NodeElement]:
    """Build scenario-specific SW overview nodes.

    This is intentionally not a full Android stack model.  It shows only the
    stack families implied by scenario metadata and active HW resources so
    non-camera scenarios do not inherit Camera HAL/V4L2 by default.
    """
    categories = {str(value).lower() for value in (graph.scenario.metadata_ or {}).get("category", [])}
    domains = {str(value).lower() for value in (graph.scenario.metadata_ or {}).get("domain", [])}
    resource_kinds = {_architecture_resource_kind(graph, node) for node in graph.pipeline_nodes}
    tags = categories | domains | resource_kinds
    if _camera_overview_uses_display(graph):
        tags.add("camera")
    specs: list[tuple[str, str, str, str, str, int]] = []

    def add(node_id: str, label: str, layer: str, stage: str, order: int) -> None:
        spec = (node_id, label, "sw", layer, stage, order)
        if spec not in specs:
            specs.append(spec)

    if "camera" in tags or "sensor" in tags or "isp" in tags:
        add("sw-camera-app", "Camera App", "app", "capture", 0)
        add("sw-camera-fw", "CameraService", "framework", "capture", 0)
        add("sw-camera-hal", "Camera HAL", "hal", "capture", 0)
        add("sw-camera-driver", "V4L2 Camera Driver", "kernel", "capture", 0)

    if "audio" in tags:
        add("sw-audio-app", "Audio App", "app", "capture", 0)
        add("sw-audio-fw", "AudioFlinger", "framework", "processing", 0)
        add("sw-audio-hal", "Audio HAL", "hal", "processing", 0)
        add("sw-audio-driver", "ALSA / PCM Driver", "kernel", "processing", 0)

    if "video" in tags or "video_playback" in tags or "mfc" in tags or "codec" in tags:
        label = "Camera App" if "camera" in tags else "Player App"
        framework = "MediaRecorder" if "camera" in tags else "MediaExtractor"
        if "camera" not in tags:
            add("sw-media-app", label, "app", "processing", 1)
        add("sw-media-fw", framework, "framework", "processing", 1)
        add("sw-codec-hal", "Codec2 HAL", "hal", "encode", 0)
        add("sw-codec-driver", "MFC Driver", "kernel", "encode", 0)

    if "camera" in tags or "display" in tags or "dpu" in tags or "panel" in tags:
        add("sw-surface", "SurfaceFlinger", "framework", "display", 0)
        add("sw-hwc", "HWC / Display HAL", "hal", "display", 0)
        add("sw-drm", "DRM / KMS", "kernel", "display", 0)

    if "game" in tags or "gpu" in tags:
        add("sw-game-app", "Game App", "app", "processing", 0)
        add("sw-graphics-fw", "Graphics Framework", "framework", "processing", 2)
        add("sw-gpu-hal", "GPU HAL", "hal", "processing", 1)
        add("sw-gpu-driver", "GPU Driver", "kernel", "processing", 1)

    return [
        _n(
            node_id,
            label,
            node_type,
            layer,
            STAGE_X.get(stage, STAGE_X["processing"]),
            LANE_Y[layer],
            detail_items=[f"Scenario SW stack: {label}"],
            view_hints=ViewHints(lane=layer, stage=stage, order=order),
        )
        for node_id, label, node_type, layer, stage, order in specs
    ]


def _architecture_resource_nodes(
    graph: CanonicalScenarioGraph,
    stage_orders: dict[tuple[str, str], int],
) -> tuple[list[NodeElement], dict[str, str]]:
    groups: dict[str, dict[str, Any]] = {}
    node_map: dict[str, str] = {}
    disabled_nodes = _disabled_node_ids(graph)

    for pipeline_node in graph.pipeline_nodes:
        node_id = pipeline_node.get("id")
        if not node_id:
            continue
        if str(node_id) in disabled_nodes:
            continue
        if _is_explicit_sw_task(graph, pipeline_node):
            layer = _sw_layer_for_node(pipeline_node)
            stage = _stage_for_node(node_id, pipeline_node)
            order = _next_order(stage_orders, layer, stage)
            view_id = f"sw-task-{_safe_id(node_id)}"
            groups[view_id] = {
                "id": view_id,
                "label": _node_label(node_id, pipeline_node),
                "layer": layer,
                "type": "sw",
                "stage": stage,
                "order": order,
                "members": [pipeline_node],
                "detail_items": _node_detail_items(graph, node_id, pipeline_node),
            }
            node_map[str(node_id)] = view_id
            continue

        kind = _architecture_resource_kind(graph, pipeline_node)
        view_id = f"res-{kind}"
        node_map[str(node_id)] = view_id
        group_layer = "external" if kind in {"sensor", "panel"} else ("memory" if kind == "memory" else "hw")
        group = groups.setdefault(
            view_id,
            {
                "id": view_id,
                "label": _architecture_resource_label(kind),
                "layer": group_layer,
                "type": "ip" if kind not in {"memory"} else "buffer",
                "stage": _architecture_resource_stage(kind, node_id, pipeline_node),
                "members": [],
                "capability_badges": [],
                "detail_items": [],
            },
        )
        group["members"].append(pipeline_node)
        for badge in _capability_badges(graph, pipeline_node):
            if badge not in group["capability_badges"]:
                group["capability_badges"].append(badge)

    if _camera_overview_uses_display(graph):
        _ensure_inferred_resource_group(groups, "sensor", "external")
        _ensure_inferred_resource_group(groups, "dpu", "hw")
        _ensure_inferred_resource_group(groups, "panel", "external")

    nodes: list[NodeElement] = []
    for group in groups.values():
        members = group["members"]
        layer = group["layer"]
        stage = group["stage"]
        order = group.get("order")
        if order is None:
            order = _next_order(stage_orders, layer, stage)
        detail_items = list(group.get("detail_items") or [])
        if members:
            detail_items.append(
                "Members: "
                + ", ".join(str(member.get("id")) for member in members[:8])
                + (f" +{len(members) - 8}" if len(members) > 8 else "")
            )
        representative = members[0] if members else {}
        nodes.append(
            _n(
                group["id"],
                group["label"],
                group["type"],
                layer,
                STAGE_X.get(stage, STAGE_X["processing"]) + (int(order) * 115),
                LANE_Y[layer],
                ip_ref=representative.get("ip_ref"),
                summary_badges=[f"{len(members)} nodes"] if len(members) > 1 else [],
                capability_badges=list(group.get("capability_badges") or [])[:6],
                active_operations=_operation_summary(graph, representative.get("id"), representative) if representative else None,
                detail_items=detail_items,
                collapsed_children_count=max(0, len(members) - 1),
                view_hints=ViewHints(lane=layer, stage=stage, order=int(order)),
            )
        )
    return nodes, node_map


def _ensure_inferred_resource_group(groups: dict[str, dict[str, Any]], kind: str, layer: str) -> None:
    view_id = f"res-{kind}"
    if view_id in groups:
        return
    groups[view_id] = {
        "id": view_id,
        "label": _architecture_resource_label(kind),
        "layer": layer,
        "type": "ip",
        "stage": _architecture_resource_stage(kind, None, {}),
        "members": [],
        "capability_badges": ["inferred"],
        "detail_items": ["Inferred camera display path for Level 0 overview."],
    }


def _architecture_edges(graph: CanonicalScenarioGraph, node_map: dict[str, str]) -> list[EdgeElement]:
    edges: list[EdgeElement] = []
    remove_specs = _disabled_edge_specs(graph)
    for idx, edge in enumerate(graph.pipeline_edges):
        if _task_edge_removed(edge, remove_specs):
            continue
        source = node_map.get(str(edge.get("from")))
        target = node_map.get(str(edge.get("to")))
        if not source or not target or source == target:
            continue
        flow_type = _edge_flow_type(edge)
        buffer_ref = edge.get("buffer")
        if buffer_ref:
            # Level 0 must still show the direct HW pipeline relationship.
            # The buffer edges provide memory detail; this summary edge keeps
            # HW-to-HW connectivity visible in the architecture overview.
            edges.append(
                _e(
                    f"e-{idx}-hw-summary",
                    source,
                    target,
                    flow_type,
                    buffer_ref=buffer_ref,
                    label=f"{flow_type} path",
                    detail_items=_edge_detail_items(graph, edge, buffer_ref),
                )
            )
            buffer_id = _architecture_buffer_id(buffer_ref)
            edges.append(_e(f"e-{idx}-src-buf", source, buffer_id, flow_type, buffer_ref=buffer_ref, detail_items=_edge_detail_items(graph, edge, buffer_ref)))
            edges.append(_e(f"e-{idx}-buf-tgt", buffer_id, target, flow_type, buffer_ref=buffer_ref, detail_items=_edge_detail_items(graph, edge, buffer_ref)))
        else:
            edges.append(_e(f"e-{idx}-{source}-{target}", source, target, flow_type, detail_items=_edge_detail_items(graph, edge, None)))
    return edges


def _inferred_architecture_edges(graph: CanonicalScenarioGraph, node_ids: set[str]) -> list[EdgeElement]:
    if not _camera_overview_uses_display(graph):
        return []

    edges: list[EdgeElement] = []
    if "res-sensor" in node_ids:
        target = next((node_id for node_id in ("res-camera_frontend", "res-isp") if node_id in node_ids), None)
        has_declared_sensor_path = any(
            _architecture_resource_kind(graph, source_node) == "sensor"
            for edge in graph.pipeline_edges
            if (source_node := _find_pipeline_node(graph, edge.get("from")))
        )
        if target and not has_declared_sensor_path:
            edges.append(
                _e(
                    "e-inferred-sensor-input",
                    "res-sensor",
                    target,
                    "OTF",
                    label="sensor in",
                    detail_items=["Inferred camera sensor input for Level 0 overview."],
                )
            )

    if "res-dpu" not in node_ids:
        return edges

    has_declared_dpu_path = any(
        _architecture_resource_kind(graph, target_node) == "dpu"
        for edge in graph.pipeline_edges
        if (target_node := _find_pipeline_node(graph, edge.get("to")))
    )
    if not has_declared_dpu_path:
        source = next((node_id for node_id in ("res-isp", "res-camera_frontend", "res-mfc") if node_id in node_ids), None)
        if source:
            edges.append(
                _e(
                    "e-inferred-camera-display",
                    source,
                    "res-dpu",
                    "M2M",
                    label="display path",
                    detail_items=["Inferred camera preview/display path for Level 0 overview."],
                )
            )

    has_declared_panel_path = any(
        _architecture_resource_kind(graph, source_node) == "dpu" and _architecture_resource_kind(graph, target_node) == "panel"
        for edge in graph.pipeline_edges
        if (source_node := _find_pipeline_node(graph, edge.get("from"))) and (target_node := _find_pipeline_node(graph, edge.get("to")))
    )
    if "res-panel" in node_ids and not has_declared_panel_path:
        edges.append(
            _e(
                "e-inferred-dpu-panel",
                "res-dpu",
                "res-panel",
                "OTF",
                label="display out",
                detail_items=["Inferred panel output for Level 0 overview."],
            )
        )
    return edges


def _topology_edges(graph: CanonicalScenarioGraph) -> list[EdgeElement]:
    edges: list[EdgeElement] = []
    for idx, edge in enumerate(graph.pipeline_edges):
        source = f"ip-{edge.get('from')}"
        target = f"ip-{edge.get('to')}"
        flow_type = _edge_flow_type(edge)
        buffer_ref = edge.get("buffer")
        if buffer_ref:
            buffer_id = f"buf-{_safe_id(buffer_ref)}"
            details = _edge_detail_items(graph, edge, buffer_ref)
            edges.append(_e(f"e-topo-{idx}-src-buf", source, buffer_id, flow_type, buffer_ref=buffer_ref, detail_items=details))
            edges.append(_e(f"e-topo-{idx}-buf-tgt", buffer_id, target, flow_type, buffer_ref=buffer_ref, detail_items=details))
        else:
            edges.append(_e(f"e-topo-{idx}", source, target, flow_type, detail_items=_edge_detail_items(graph, edge, None)))
    return edges


def _buffer_nodes_from_architecture_edges(
    graph: CanonicalScenarioGraph,
    node_map: dict[str, str],
    stage_orders: dict[tuple[str, str], int],
) -> list[NodeElement]:
    nodes: list[NodeElement] = []
    seen: set[str] = set()
    for edge in graph.pipeline_edges:
        buffer_ref = edge.get("buffer")
        if not buffer_ref or buffer_ref in seen:
            continue
        source = node_map.get(str(edge.get("from")))
        target = node_map.get(str(edge.get("to")))
        if not source or not target or source == target:
            continue
        seen.add(buffer_ref)
        target_node = _find_pipeline_node(graph, edge.get("to"))
        source_node = _find_pipeline_node(graph, edge.get("from"))
        stage = _stage_for_node(edge.get("to"), target_node or source_node or {})
        order = _next_order(stage_orders, "memory", stage)
        nodes.append(
            _n(
                _architecture_buffer_id(buffer_ref),
                _buffer_label(buffer_ref),
                "buffer",
                "memory",
                STAGE_X.get(stage, STAGE_X["processing"]) + (order * 170),
                LANE_Y["memory"],
                memory=_memory_descriptor(graph, buffer_ref),
                placement=_memory_placement(graph, buffer_ref),
                detail_items=_buffer_detail_items(graph, buffer_ref),
                view_hints=ViewHints(lane="memory", stage=stage, order=order),
            )
        )
    return nodes


def _buffer_nodes_from_edges(
    graph: CanonicalScenarioGraph,
    stage_orders: dict[tuple[str, str], int],
) -> list[NodeElement]:
    nodes: list[NodeElement] = []
    seen: set[str] = set()
    for edge in graph.pipeline_edges:
        buffer_ref = edge.get("buffer")
        if not buffer_ref or buffer_ref in seen:
            continue
        seen.add(buffer_ref)
        source_node = _find_pipeline_node(graph, edge.get("from"))
        target_node = _find_pipeline_node(graph, edge.get("to"))
        stage = _stage_for_node(edge.get("to"), target_node or source_node or {})
        order = _next_order(stage_orders, "memory", stage)
        nodes.append(
            _n(
                f"buf-{_safe_id(buffer_ref)}",
                _buffer_label(buffer_ref),
                "buffer",
                "memory",
                STAGE_X.get(stage, STAGE_X["processing"]) + (order * 170),
                LANE_Y["memory"],
                memory=_memory_descriptor(graph, buffer_ref),
                placement=_memory_placement(graph, buffer_ref),
                detail_items=_buffer_detail_items(graph, buffer_ref),
                view_hints=ViewHints(lane="memory", stage=stage, order=order),
            )
        )
    return nodes


def _sw_control_edges(
    graph: CanonicalScenarioGraph,
    node_map: dict[str, str],
    node_ids: set[str],
) -> list[EdgeElement]:
    edges: list[EdgeElement] = []

    def add(edge_id: str, source: str, target: str, label: str | None = None) -> None:
        if source in node_ids and target in node_ids:
            edges.append(_e(edge_id, source, target, "control", label=label))

    add("e-sw-camera-0", "sw-camera-app", "sw-camera-fw", "Camera API")
    add("e-sw-camera-1", "sw-camera-fw", "sw-camera-hal", "HAL call")
    add("e-sw-camera-2", "sw-camera-hal", "sw-camera-driver", "V4L2")
    if "res-sensor" in node_ids:
        add("e-sw-camera-sensor", "sw-camera-driver", "res-sensor", "subdev")
    elif "res-isp" in node_ids:
        add("e-sw-camera-isp", "sw-camera-driver", "res-isp", "subdev")

    add("e-sw-audio-0", "sw-audio-app", "sw-audio-fw", "AudioTrack")
    add("e-sw-audio-1", "sw-audio-fw", "sw-audio-hal", "Audio HAL")
    add("e-sw-audio-2", "sw-audio-hal", "sw-audio-driver", "PCM")

    media_app_source = "sw-camera-app" if "sw-camera-app" in node_ids else "sw-media-app"
    add("e-sw-media-0", media_app_source, "sw-media-fw", "Media API")
    add("e-sw-media-1", "sw-media-fw", "sw-codec-hal", "Codec2")
    add("e-sw-media-2", "sw-codec-hal", "sw-codec-driver", "V4L2 M2M")
    add("e-sw-media-mfc", "sw-codec-driver", "res-mfc", "driver")
    add("e-sw-media-apv", "sw-codec-driver", "res-apv", "driver")

    add("e-sw-display-0", "sw-surface", "sw-hwc", "composition")
    add("e-sw-display-1", "sw-hwc", "sw-drm", "KMS")
    add("e-sw-display-dpu", "sw-drm", "res-dpu", "atomic")

    add("e-sw-game-0", "sw-game-app", "sw-graphics-fw", "render")
    add("e-sw-game-1", "sw-graphics-fw", "sw-gpu-hal", "EGL/Vulkan")
    add("e-sw-game-2", "sw-gpu-hal", "sw-gpu-driver", "ioctl")
    add("e-sw-game-gpu", "sw-gpu-driver", "res-gpu", "driver")

    for pipeline_node in graph.pipeline_nodes:
        node_id = pipeline_node.get("id")
        if not node_id:
            continue
        view_id = node_map.get(str(node_id))
        if not view_id or view_id not in node_ids:
            continue
        role = str(pipeline_node.get("role") or "").lower()
        if role in {"sw_task", "eis", "m2m_scaler", "audio_decode", "demux", "dsp_offload"}:
            add(f"e-sw-task-{_safe_id(node_id)}", "sw-camera-driver" if "sw-camera-driver" in node_ids else "sw-media-fw", view_id, "SW task")

    return edges


def _risk_edges(graph: CanonicalScenarioGraph, node_map: dict[str, str] | None = None) -> list[EdgeElement]:
    gate = run_review_gate(graph)
    matched_issue_ids = {matched.issue_id for matched in gate.matched_issues}
    affected_ip_refs: set[str] = set()
    for issue in graph.issues:
        if issue.id not in matched_issue_ids:
            continue
        for affected in issue.affects_ip or []:
            ip_ref = affected.get("ip_ref")
            if ip_ref:
                affected_ip_refs.add(ip_ref)

    edges: list[EdgeElement] = []
    for pipeline_node in graph.pipeline_nodes:
        if pipeline_node.get("ip_ref") not in affected_ip_refs:
            continue
        node_id = pipeline_node.get("id")
        view_id = (node_map or {}).get(str(node_id)) or f"ip-{node_id}"
        edges.append(_e(f"e-risk-{node_id}", view_id, view_id, "risk", label="Known issue"))
    return edges






def _architecture_resource_kind(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> str:
    text = (
        f"{pipeline_node.get('id', '')} {pipeline_node.get('ip_ref', '')} "
        f"{pipeline_node.get('role', '')} {pipeline_node.get('node_type', '')}"
    ).lower()
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    category = str(getattr(ip_row, "category", "") or "").lower()
    if "sensor" in text or category == "sensor":
        return "sensor"
    if "panel" in text or "display_output" in text:
        return "panel"
    if any(token in text for token in ("dpu", "decon", "display_controller")) or category == "display":
        return "dpu"
    if any(token in text for token in ("csis", "csi", "pdp")):
        return "camera_frontend"
    if any(token in text for token in ("isp", "3aa", "byrp", "rgbp", "yuv", "mcsc", "mtnr", "msnr", "lme", "gdc")) or category == "camera":
        return "isp"
    if "apv" in text:
        return "apv"
    if "jpeg" in text:
        return "jpeg"
    if any(token in text for token in ("mfc", "codec", "enc", "dec")) or category == "codec":
        return "mfc"
    if "gpu" in text or category == "gpu":
        return "gpu"
    if "npu" in text or category == "npu":
        return "npu"
    if category == "memory":
        return "memory"
    if category:
        return category
    return _safe_id(str(pipeline_node.get("id") or "hw"))


def _architecture_resource_label(kind: str) -> str:
    labels = {
        "sensor": "Sensor Module",
        "camera_frontend": "Camera Frontend",
        "isp": "ISP",
        "mfc": "MFC",
        "apv": "APV",
        "jpeg": "JPEG",
        "dpu": "DPU",
        "panel": "Display Module",
        "gpu": "GPU",
        "npu": "NPU",
        "memory": "Memory Resource",
        "cpu": "CPU / SW Resource",
    }
    return labels.get(kind, kind.replace("_", " ").title())


def _architecture_resource_stage(kind: str, node_id: str | None, pipeline_node: dict[str, Any]) -> str:
    if kind in {"sensor", "camera_frontend"}:
        return "capture"
    if kind in {"mfc", "apv", "jpeg"}:
        return "encode"
    if kind in {"dpu", "panel", "gpu"}:
        return "display"
    return _stage_for_node(node_id, pipeline_node)


def _architecture_buffer_id(buffer_ref: str) -> str:
    return f"buf-arch-{_safe_id(buffer_ref)}"


def _disabled_node_ids(graph: CanonicalScenarioGraph) -> set[str]:
    return set(((getattr(graph.variant, "routing_switch", None) or {}).get("disabled_nodes") or []))


def _disabled_edge_specs(graph: CanonicalScenarioGraph) -> list[Any]:
    routing = getattr(graph.variant, "routing_switch", None) or {}
    patch = getattr(graph.variant, "topology_patch", None) or {}
    return [
        *(routing.get("disabled_edges") or []),
        *(patch.get("remove_edges") or []),
    ]


def _camera_overview_uses_display(graph: CanonicalScenarioGraph) -> bool:
    disabled_nodes = _disabled_node_ids(graph)
    if disabled_nodes:
        declared_nodes = (getattr(graph.scenario, "pipeline", {}) or {}).get("nodes") or []
        for node in declared_nodes:
            if node.get("id") in disabled_nodes and _architecture_resource_kind(graph, node) in {"dpu", "panel"}:
                return False

    metadata = graph.scenario.metadata_ or {}
    tags = {str(value).lower() for value in metadata.get("category", [])}
    tags.update(str(value).lower() for value in metadata.get("domain", []))
    tags.add(str(getattr(graph.scenario, "id", "") or "").lower())
    tags.add(str(metadata.get("name", "") or "").lower())
    return any("camera" in tag for tag in tags)


def _is_explicit_sw_task(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> bool:
    role = str(pipeline_node.get("role") or "").lower()
    node_type = str(pipeline_node.get("node_type") or pipeline_node.get("kind") or "").lower()
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    category = str(getattr(ip_row, "category", "") or "").lower()
    if node_type in {"sw", "task", "cpu"}:
        return True
    if category != "cpu":
        return False
    return role in {
        "source",
        "sw_task",
        "eis",
        "m2m_scaler",
        "audio_decode",
        "dsp_offload",
        "audio_hal",
        "audio_output",
        "bt_output",
        "demux",
    }


def _sw_layer_for_node(pipeline_node: dict[str, Any]) -> str:
    text = f"{pipeline_node.get('id', '')} {pipeline_node.get('role', '')}".lower()
    if any(token in text for token in ("app", "source", "network", "storage")):
        return "app"
    if any(token in text for token in ("hal", "audio_hal")):
        return "hal"
    if any(token in text for token in ("driver", "v4l2", "drm", "kms", "dsp", "offload", "eis", "m2m_scaler")):
        return "kernel"
    return "framework"


def _capability_badges(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> list[str]:
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    if not ip_row:
        return []
    supported = (ip_row.capabilities or {}).get("supported_features") or {}
    badges: list[str] = []
    if supported.get("hdr_formats"):
        badges.extend(str(v) for v in supported["hdr_formats"][:2])
    if supported.get("compression"):
        badges.extend(str(v) for v in supported["compression"][:1])
    if supported.get("bitdepth"):
        badges.append(f"{max(supported['bitdepth'])}b")
    ops = _operation_summary(graph, pipeline_node.get("id", ""), pipeline_node)
    if ops and ops.crop:
        badges.append("CROP")
    if ops and ops.scale:
        badges.append("SCALE")
    if ops and ops.rotate is not None:
        badges.append("ROTATE")
    return badges[:5]


def _operation_summary(
    graph: CanonicalScenarioGraph,
    node_id: str,
    pipeline_node: dict[str, Any],
) -> OperationSummary | None:
    lowered = f"{node_id} {pipeline_node.get('ip_ref', '')}".lower()
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    overrides = getattr(graph.variant, "size_overrides", None) or {}
    input_size = anchors.get("sensor_full")
    output_size = overrides.get("record_out") or anchors.get("record_out")

    if any(token in lowered for token in ("isp", "mcsc", "mlsc", "tnr", "dns")):
        return OperationSummary(
            crop=bool(design.get("zoom") or "isp" in lowered),
            scale=bool(input_size and output_size and input_size != output_size),
            scale_from=input_size,
            scale_to=output_size,
            colorspace_convert="RAW->YUV" if "isp" in lowered else None,
        )
    if any(token in lowered for token in ("gdc", "rot", "dpu")):
        return OperationSummary(rotate=0 if "dpu" in lowered else 90, compose="dpu" in lowered)
    return None


def _memory_descriptor(graph: CanonicalScenarioGraph, buffer_ref: str) -> MemoryDescriptor:
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    overrides = getattr(graph.variant, "size_overrides", None) or {}
    size = overrides.get("record_out") or anchors.get("record_out")
    width, height = _parse_size(size)
    codec = design.get("codec")
    is_bitstream = "bitstream" in buffer_ref.lower() or "enc" in buffer_ref.lower()
    return MemoryDescriptor(
        format=str(codec) if is_bitstream and codec else _format_for_buffer(buffer_ref),
        bitdepth=10 if design.get("hdr") not in (None, "SDR") else 8,
        planes=1 if is_bitstream or "raw" in buffer_ref.lower() else 2,
        width=width,
        height=height,
        fps=int(design.get("fps") or 30),
        alignment="64B",
        compression=_compression_for_buffer(graph),
    )


def _memory_placement(graph: CanonicalScenarioGraph, buffer_ref: str) -> MemoryPlacement:
    allocations = (graph.variant.ip_requirements or {}).get("llc", {}).get("required_allocations") or {}
    owner = None
    allocation_mb = None
    for key, value in allocations.items():
        owner = str(key)
        allocation_mb = _parse_mb(value)
        if str(key).lower() in buffer_ref.lower() or str(key).lower() in {"mfc", "isp.tnr"}:
            break
    return MemoryPlacement(
        llc_allocated=bool(allocations),
        llc_allocation_mb=allocation_mb,
        llc_policy="dedicated" if allocations else "none",
        allocation_owner=owner,
        expected_bw_reduction_gbps=2.0 if allocations else None,
    )


def _pipeline_ranks(graph: CanonicalScenarioGraph) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for idx, node in enumerate(graph.pipeline_nodes):
        node_id = node.get("id")
        if node_id:
            ranks[node_id] = idx
    changed = True
    while changed:
        changed = False
        for edge in graph.pipeline_edges:
            source = edge.get("from")
            target = edge.get("to")
            if source in ranks and target in ranks and ranks[target] <= ranks[source]:
                ranks[target] = ranks[source] + 1
                changed = True
    return ranks


def _stage_for_node(node_id: str | None, pipeline_node: dict[str, Any]) -> str:
    text = f"{node_id or ''} {pipeline_node.get('ip_ref', '')} {pipeline_node.get('role', '')}".lower()
    if any(token in text for token in ("sensor", "csis", "pdp", "csi")):
        return "capture"
    if any(token in text for token in ("mfc", "codec", "enc")):
        return "encode"
    if any(token in text for token in ("dpu", "display", "drm")):
        return "display"
    return "processing"


def _edge_flow_type(edge: dict[str, Any]) -> str:
    flow_type = str(edge.get("type") or "M2M")
    if flow_type in {"OTF", "vOTF", "M2M", "control", "risk"}:
        return flow_type
    lowered = flow_type.lower()
    if lowered == "votf":
        return "vOTF"
    if lowered == "otf":
        return "OTF"
    if lowered == "m2m":
        return "M2M"
    return "M2M"






def _find_pipeline_node(graph: CanonicalScenarioGraph, node_id: str | None) -> dict[str, Any] | None:
    for node in graph.pipeline_nodes:
        if node.get("id") == node_id:
            return node
    return None


def _find_pipeline_node_by_ip_ref(graph: CanonicalScenarioGraph, ip_ref: str | None) -> dict[str, Any] | None:
    for node in graph.pipeline_nodes:
        if node.get("ip_ref") == ip_ref:
            return node
    return None


def _edges_touching_node(graph: CanonicalScenarioGraph, node_id: str | None) -> list[dict[str, Any]]:
    return [edge for edge in graph.pipeline_edges if edge.get("from") == node_id or edge.get("to") == node_id]


def _first_hw_node(graph: CanonicalScenarioGraph, tokens: tuple[str, ...]) -> str | None:
    for node in graph.pipeline_nodes:
        text = f"{node.get('id', '')} {node.get('ip_ref', '')}".lower()
        if any(token in text for token in tokens):
            return node.get("id")
    return None


def _is_memory_ip(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> bool:
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    return bool(ip_row and ip_row.category == "memory")


def _pipeline_node_layer(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> str:
    explicit = str(pipeline_node.get("layer") or "").lower()
    if explicit in {"app", "framework", "hal", "kernel", "hw", "memory"}:
        return explicit
    node_type = str(pipeline_node.get("node_type") or pipeline_node.get("kind") or "").lower()
    if node_type in {"sw", "task", "cpu"}:
        return _sw_layer_for_node(pipeline_node)
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    if str(getattr(ip_row, "category", "") or "").lower() == "cpu":
        return _sw_layer_for_node(pipeline_node)
    if _is_memory_ip(graph, pipeline_node):
        return "memory"
    return "hw"


def _pipeline_node_type(layer: str) -> str:
    if layer in {"app", "framework", "hal", "kernel"}:
        return "sw"
    if layer == "memory":
        return "buffer"
    return "ip"


def _node_label(node_id: str, pipeline_node: dict[str, Any]) -> str:
    label = pipeline_node.get("label") or node_id
    return str(label).replace("_", " ").upper()


def _buffer_label(buffer_ref: str) -> str:
    return str(buffer_ref).replace("_", " ").title()




def _next_order(stage_orders: dict[tuple[str, str], int], layer: str, stage: str) -> int:
    key = (layer, stage)
    order = stage_orders.get(key, 0)
    stage_orders[key] = order + 1
    return order






def _parse_mb(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    try:
        if text.endswith("mb"):
            return float(text[:-2])
        return float(text)
    except ValueError:
        return None


def _format_for_buffer(buffer_ref: str) -> str:
    lowered = buffer_ref.lower()
    if "raw" in lowered:
        return "RAW10"
    if "preview" in lowered:
        return "NV12"
    if "record" in lowered:
        return "NV12"
    return "YUV"


def _compression_for_buffer(graph: CanonicalScenarioGraph) -> str | None:
    for ip_row in graph.ip_catalog.values():
        compression = ((ip_row.capabilities or {}).get("supported_features") or {}).get("compression")
        if compression:
            return compression[0]
    return None


def _dma_count_for_node(graph: CanonicalScenarioGraph, node_id: str | None) -> int:
    memory_edges = [edge for edge in _edges_touching_node(graph, node_id) if edge.get("type") == "M2M"]
    return max(1, len(memory_edges))
