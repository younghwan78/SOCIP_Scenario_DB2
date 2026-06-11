"""View projection service.

build_canonical_graph() → project_level0() → ViewResponse

Sample data matches the "Video Recording — FHD 30fps" scenario from the
design draft. Real DB integration is wired via the FastAPI router; the
dashboard can also call this module directly without an HTTP round-trip.
"""
from __future__ import annotations

import logging
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
from scenario_db.view.elements import _e, _n
from scenario_db.view.buffers import (
    _buffer_detail_items,
    _buffer_label,
    _buffer_memory_from_spec,
    _buffer_placement_from_spec,
    _memory_descriptor,
    _memory_placement,
    _reference_sizes,
)
from scenario_db.view.pipeline import (
    _edge_detail_items,
    _edge_flow_type,
    _find_pipeline_node,
    _node_detail_items,
    _pipeline_node_layer,
    _pipeline_node_type,
    _stage_for_node,
    _sw_layer_for_node,
    _task_edge_removed,
    _task_node_detail_items,
)
from scenario_db.view.semantic_constants import (
    _LEVEL1_HIERARCHY_ORDER,
    _LEVEL1_IP_GROUP_ORDER,
    _LEVEL2_ALIAS_GROUPS,
    _LEVEL2_BLOCK_BY_IP_GROUP,
    _LEVEL2_REQUIRED_DATA,
)
from scenario_db.view.simulation_overlay import apply_simulation_overlay
from scenario_db.view.response import build_view_response as _response

logger = logging.getLogger(__name__)


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
    _require_db(db)
    graph = _load_graph(db, scenario_id, variant_id)
    if mode == "resource":
        return _project_level0_resource_v2(graph, level=0)
    if mode == "topology":
        return _project_level0_topology_v2(graph, level=0)
    return _project_architecture(graph, level=0)


def project_level1(scenario_id: str, variant_id: str | None, db=None) -> ViewResponse:
    _require_db(db)
    graph = _load_graph(db, scenario_id, variant_id)
    semantic = _project_semantic_level1(graph)
    if semantic is not None:
        return semantic
    return _project_reference_level1(graph)


def project_level2(scenario_id: str, variant_id: str | None, expand: str, db=None) -> ViewResponse:
    _require_db(db)
    graph = _load_graph(db, scenario_id, variant_id)
    return _project_drilldown(graph, expand)


def _require_db(db) -> None:
    if db is None:
        raise ValueError("db session is required for view projection; use scenario_db.view.demo.sample_data for demo fallback")


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


def _project_reference_level1(graph: CanonicalScenarioGraph) -> ViewResponse:
    from scenario_db.view.reference import project_reference_level1

    return project_reference_level1(graph)


def _project_reference_task_topology(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    from scenario_db.view.reference import project_reference_task_topology

    return project_reference_task_topology(graph, level)


def _project_level2_reference(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse | None:
    from scenario_db.view.reference import project_level2_reference

    return project_level2_reference(graph, expand)


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
    # Schema-declared resource_kind wins over token heuristics (review 5.3).
    explicit_kind = str(pipeline_node.get("resource_kind") or "").lower()
    if explicit_kind:
        return explicit_kind
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


def _pipeline_ranks(graph: CanonicalScenarioGraph) -> dict[str, int]:
    pipeline_edges = graph.pipeline_edges
    ranks: dict[str, int] = {}
    for idx, node in enumerate(graph.pipeline_nodes):
        node_id = node.get("id")
        if node_id:
            ranks[node_id] = idx
    # Bellman-Ford-style relaxation: a DAG converges within len(ranks) - 1
    # rounds, so the bound only triggers when the pipeline contains a cycle.
    for _ in range(max(len(ranks), 1)):
        changed = False
        for edge in pipeline_edges:
            source = edge.get("from")
            target = edge.get("to")
            if source in ranks and target in ranks and ranks[target] <= ranks[source]:
                ranks[target] = ranks[source] + 1
                changed = True
        if not changed:
            return ranks
    logger.warning(
        "Pipeline ranks did not converge (cycle suspected): %s/%s",
        getattr(graph, "scenario_id", "?"),
        getattr(graph, "variant_id", "?"),
    )
    return ranks


def _first_hw_node(graph: CanonicalScenarioGraph, tokens: tuple[str, ...]) -> str | None:
    for node in graph.pipeline_nodes:
        text = f"{node.get('id', '')} {node.get('ip_ref', '')}".lower()
        if any(token in text for token in tokens):
            return node.get("id")
    return None


def _node_label(node_id: str, pipeline_node: dict[str, Any]) -> str:
    label = pipeline_node.get("label") or node_id
    return str(label).replace("_", " ").upper()


def _next_order(stage_orders: dict[tuple[str, str], int], layer: str, stage: str) -> int:
    key = (layer, stage)
    order = stage_orders.get(key, 0)
    stage_orders[key] = order + 1
    return order
