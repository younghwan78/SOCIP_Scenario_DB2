"""Level 0 v2 resource-flow projection helpers."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from scenario_db.api.schemas.view import (
    BufferHandoffSummary,
    DisplayCompositionSummary,
    DisplayLayerSummary,
    EdgeData,
    EdgeElement,
    IoSummary,
    Level0MetricBreakdown,
    Level0ResourceOverview,
    MemoryDescriptor,
    MemoryPlacement,
    NodeData,
    NodeElement,
    OperationSummary,
    ResourceOverviewRow,
    SensorEndpointSummary,
    ViewHints,
)
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.buffers import display_compression
from scenario_db.graph_checks import (
    edge_source as _edge_source,
    edge_target as _edge_target,
)


@dataclass(frozen=True)
class Level0ViewProjection:
    nodes: list[NodeElement]
    edges: list[EdgeElement]
    metadata: dict[str, Any]


def build_resource_overview(graph: CanonicalScenarioGraph) -> Level0ResourceOverview:
    """Build a resource-first Level 0 overview from the effective graph."""

    nodes = _visible_resource_nodes(graph)
    edges = _level0_edges(graph)
    ordered_nodes = _topological_nodes(nodes, edges)
    rows = [
        _row_for_node(graph, node, index + 1, edges)
        for index, node in enumerate(ordered_nodes)
    ]
    return Level0ResourceOverview(
        rows=rows,
        buffers=_buffer_handoffs(graph, rows, edges),
        metric_breakdown=_metric_breakdown(rows),
        sensors=_sensor_summaries(graph, rows, edges),
        displays=_display_summaries(graph, rows),
        notes=[],
    )


def project_level0_resource_view(graph: CanonicalScenarioGraph) -> Level0ViewProjection:
    """Project the Level 0 resource dashboard payload.

    The graph canvas is intentionally empty for this mode; the consumer should
    render `level0_resource_overview` as the primary resource table and metric
    summary.
    """

    nodes = _visible_resource_nodes(graph)
    edges = _level0_edges(graph)
    return Level0ViewProjection(
        nodes=[],
        edges=[],
        metadata={
            "canvas_w": 1180,
            "canvas_h": 520,
            "layout": "level0-resource-overview",
            "active_node_count": len(nodes),
            "active_edge_count": len(edges),
        },
    )


def project_level0_topology_view(graph: CanonicalScenarioGraph) -> Level0ViewProjection:
    """Project active scenario nodes plus explicit buffer handoff nodes."""

    edges = _level0_edges(graph)
    ordered_nodes = _topological_nodes(_visible_resource_nodes(graph), edges)
    ranks = {str(node.get("id")): index for index, node in enumerate(ordered_nodes) if node.get("id")}
    node_map: dict[str, str] = {}
    nodes: list[NodeElement] = []
    for index, pipeline_node in enumerate(ordered_nodes):
        node_id = str(pipeline_node.get("id") or "")
        if not node_id:
            continue
        view_id = f"ip-{node_id}"
        node_map[node_id] = view_id
        layer = _topology_layer(graph, pipeline_node)
        kind = _resource_kind(graph, pipeline_node)
        outgoing = _outgoing_edges(node_id, edges)
        ops = _topology_operation_summary(graph, node_id, pipeline_node)
        nodes.append(
            NodeElement(
                data=NodeData(
                    id=view_id,
                    label=_node_label(pipeline_node),
                    type=_topology_node_type(layer),
                    layer=layer,
                    ip_ref=pipeline_node.get("ip_ref"),
                    summary_badges=_topology_summary_badges(graph, pipeline_node, ops),
                    capability_badges=_badges(kind, outgoing, [str(edge.get("buffer")) for edge in outgoing if edge.get("buffer")]),
                    active_operations=ops,
                    detail_items=_detail_items(
                        pipeline_node,
                        [str(edge.get("buffer")) for edge in outgoing if edge.get("buffer")],
                    ),
                    view_hints=ViewHints(
                        lane=layer,
                        stage=_topology_stage(kind, pipeline_node),
                        order=index,
                        width=150,
                        height=58,
                    ),
                ),
                position={"x": _topology_x(layer), "y": 85 + index * 112},
            )
        )

    nodes.extend(_topology_buffer_nodes(graph, ranks, edges))
    edges = _topology_edges(graph, node_map)
    return Level0ViewProjection(
        nodes=nodes,
        edges=edges,
        metadata={
            "canvas_w": 1120,
            "canvas_h": max(640, 180 + len(nodes) * 92),
            "layout": "level0-resource-topology",
            "active_node_count": len(ordered_nodes),
            "active_edge_count": len(_level0_edges(graph)),
            "buffer_node_count": sum(1 for node in nodes if node.data.type == "buffer"),
        },
    )


def _topology_buffer_nodes(
    graph: CanonicalScenarioGraph,
    ranks: dict[str, int],
    edges: list[dict[str, Any]],
) -> list[NodeElement]:
    nodes: list[NodeElement] = []
    seen: set[str] = set()
    for index, edge in enumerate(edges):
        buffer_ref = edge.get("buffer")
        if not buffer_ref:
            continue
        buffer_ref = str(buffer_ref)
        if buffer_ref in seen:
            continue
        seen.add(buffer_ref)
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        source_rank = ranks.get(source, index)
        target_rank = ranks.get(target, source_rank + 1)
        y = 85 + ((source_rank + target_rank) / 2) * 112
        placement = _memory_placement(graph, buffer_ref)
        nodes.append(
            NodeElement(
                data=NodeData(
                    id=_buffer_node_id(buffer_ref),
                    label=_buffer_label(buffer_ref),
                    type="buffer",
                    layer="memory",
                    memory=_memory_descriptor(graph, buffer_ref),
                    placement=placement,
                    summary_badges=["LLC"] if placement and placement.llc_allocated else [],
                    detail_items=_buffer_detail_items(graph, buffer_ref),
                    view_hints=ViewHints(lane="memory", stage="processing", order=index, width=210, height=60),
                ),
                position={"x": _topology_x("memory"), "y": y},
            )
        )
    return nodes


def _topology_edges(graph: CanonicalScenarioGraph, node_map: dict[str, str]) -> list[EdgeElement]:
    edges: list[EdgeElement] = []
    for index, edge in enumerate(_level0_edges(graph)):
        source = node_map.get(str(_edge_source(edge) or ""))
        target = node_map.get(str(_edge_target(edge) or ""))
        if not source or not target:
            continue
        flow_type = _flow_type(edge)
        buffer_ref = edge.get("buffer")
        if buffer_ref:
            buffer_ref = str(buffer_ref)
            buffer_id = _buffer_node_id(buffer_ref)
            details = _edge_detail_items(graph, edge, buffer_ref)
            memory = _memory_descriptor(graph, buffer_ref)
            placement = _memory_placement(graph, buffer_ref)
            edges.append(
                EdgeElement(
                    data=EdgeData(
                        id=f"e-topo-{index}-src-buf",
                        source=source,
                        target=buffer_id,
                        flow_type=flow_type,
                        buffer_ref=buffer_ref,
                        producer=str(_edge_source(edge) or ""),
                        consumer=str(_edge_target(edge) or ""),
                        memory=memory,
                        placement=placement,
                        detail_items=details,
                    )
                )
            )
            edges.append(
                EdgeElement(
                    data=EdgeData(
                        id=f"e-topo-{index}-buf-tgt",
                        source=buffer_id,
                        target=target,
                        flow_type=flow_type,
                        buffer_ref=buffer_ref,
                        producer=str(_edge_source(edge) or ""),
                        consumer=str(_edge_target(edge) or ""),
                        memory=memory,
                        placement=placement,
                        detail_items=details,
                    )
                )
            )
            continue
        edges.append(
            EdgeElement(
                data=EdgeData(
                    id=f"e-topo-{index}",
                    source=source,
                    target=target,
                    flow_type=flow_type,
                    detail_items=_edge_detail_items(graph, edge, None),
                )
            )
        )
    return edges


# Active graph ordering


def _visible_resource_nodes(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    return [node for node in graph.pipeline_nodes if not _is_memory_resource_node(graph, node)]


def _is_memory_resource_node(graph: CanonicalScenarioGraph, node: dict[str, Any]) -> bool:
    text = _node_text(node)
    return _resource_kind(graph, node) == "memory" or "llc" in text


def _level0_edges(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    """Return effective edges after collapsing LLC/memory nodes into buffers."""

    memory_node_ids = {
        str(node.get("id"))
        for node in graph.pipeline_nodes
        if node.get("id") and _is_memory_resource_node(graph, node)
    }
    if not memory_node_ids:
        return list(graph.pipeline_edges)

    outgoing_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.pipeline_edges:
        source = str(_edge_source(edge) or "")
        outgoing_by_source[source].append(edge)

    collapsed: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any, Any]] = set()
    for edge in graph.pipeline_edges:
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        if source in memory_node_ids:
            continue
        if target not in memory_node_ids:
            _append_edge_once(collapsed, seen, edge)
            continue
        buffer_ref = edge.get("buffer")
        downstream = [
            next_edge
            for next_edge in outgoing_by_source.get(target, [])
            if next_edge.get("buffer") == buffer_ref
        ]
        for next_edge in downstream:
            consumer = _edge_target(next_edge)
            if consumer in memory_node_ids:
                continue
            merged = dict(edge)
            merged["to"] = consumer
            merged.pop("target", None)
            _append_edge_once(collapsed, seen, merged)
    return collapsed


def _append_edge_once(
    edges: list[dict[str, Any]],
    seen: set[tuple[Any, Any, Any, Any]],
    edge: dict[str, Any],
) -> None:
    key = (_edge_source(edge), _edge_target(edge), edge.get("type"), edge.get("buffer"))
    if key in seen:
        return
    seen.add(key)
    edges.append(edge)


def _topological_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    original_order = {str(node.get("id")): index for index, node in enumerate(nodes) if node.get("id")}
    indegree: dict[str, int] = {node_id: 0 for node_id in by_id}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = str(edge.get("from") or edge.get("source") or "")
        target = str(edge.get("to") or edge.get("target") or "")
        if source not in by_id or target not in by_id:
            continue
        outgoing[source].append(target)
        indegree[target] += 1

    queue = deque(sorted((node_id for node_id, count in indegree.items() if count == 0), key=original_order.get))
    ordered: list[str] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for target in sorted(outgoing[node_id], key=original_order.get):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    if len(ordered) != len(by_id):
        ordered = sorted(by_id, key=original_order.get)
    return [by_id[node_id] for node_id in ordered]


# Row construction


def _row_for_node(
    graph: CanonicalScenarioGraph,
    node: dict[str, Any],
    sequence_index: int,
    edges: list[dict[str, Any]],
) -> ResourceOverviewRow:
    node_id = str(node.get("id"))
    kind = _resource_kind(graph, node)
    outgoing = _outgoing_edges(node_id, edges)
    incoming_buffer_refs = [str(edge.get("buffer")) for edge in _incoming_edges(node_id, edges) if edge.get("buffer")]
    buffer_refs = [str(edge.get("buffer")) for edge in outgoing if edge.get("buffer")]
    return ResourceOverviewRow(
        sequence_index=sequence_index,
        node_id=node_id,
        label=_node_label(node),
        resource_domain=_resource_domain(kind, node),
        resource_kind=kind,
        subsystem=_subsystem(kind, graph, node),
        role=node.get("role"),
        input=_io_from_buffers(graph, incoming_buffer_refs),
        output=_io_from_buffers(graph, buffer_refs),
        flow=_flow_summary(outgoing),
        buffer_refs=buffer_refs,
        input_buffer_refs=incoming_buffer_refs,
        badges=_badges(kind, outgoing, buffer_refs),
        detail_items=_detail_items(node, buffer_refs),
    )


def _incoming_edges(node_id: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [edge for edge in edges if str(edge.get("to") or edge.get("target") or "") == node_id]


def _outgoing_edges(node_id: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [edge for edge in edges if str(edge.get("from") or edge.get("source") or "") == node_id]


def _flow_summary(edges: list[dict[str, Any]]) -> str:
    flows = {_flow_type(edge) for edge in edges}
    if not flows:
        return "none"
    if len(flows) == 1:
        return next(iter(flows))
    return "mixed"


def _flow_type(edge: dict[str, Any]) -> str:
    raw = str(edge.get("type") or "M2M")
    if raw.lower() == "votf":
        return "vOTF"
    if raw.upper() == "OTF":
        return "OTF"
    if raw.upper() == "M2M":
        return "M2M"
    if raw.lower() == "control":
        return "control"
    if raw.lower() == "risk":
        return "risk"
    return "M2M"


# Classification


def _resource_kind(graph: CanonicalScenarioGraph, node: dict[str, Any]) -> str:
    # Schema-declared resource_kind wins over token heuristics (review 5.3).
    explicit_kind = str(node.get("resource_kind") or "").lower()
    if explicit_kind:
        return explicit_kind
    text = _node_text(node)
    category = _ip_category(graph, node)
    if "panel" in text or "display_output" in text:
        return "panel"
    if "sensor" in text or category == "sensor":
        return "sensor"
    if "gpu" in text or category == "gpu":
        return "gpu"
    if "npu" in text or category == "npu":
        return "npu"
    if any(token in text for token in ("dpu", "decon", "display_controller")) or category == "display":
        return "dpu"
    if any(token in text for token in ("mfc", "codec", "decoder", "encoder")) or category == "codec":
        return "mfc"
    if "audio" in text or "speaker" in text or "mic" in text:
        return "audio"
    if category == "cpu" or any(token in text for token in ("cpu", "demux", "source", "network", "storage", "task")):
        return "cpu_task"
    return category or _safe_id(str(node.get("id") or "resource"))


def _resource_domain(kind: str, node: dict[str, Any]) -> str:
    role = str(node.get("role") or "").lower()
    if kind in {"sensor"} or role in {"source"}:
        return "external_source"
    if kind in {"panel"} or role in {"display_output", "audio_output", "sink"}:
        return "external_sink"
    if kind == "memory":
        return "memory"
    return "soc_resource"


def _subsystem(kind: str, graph: CanonicalScenarioGraph, node: dict[str, Any]) -> str:
    if kind in {"sensor", "isp"}:
        return "camera"
    if kind == "mfc":
        return "video"
    if kind in {"gpu", "dpu", "panel"}:
        return "display"
    if kind == "npu":
        return "ai"
    if kind == "audio":
        return "audio"
    categories = {str(value).lower() for value in (getattr(graph.scenario, "metadata_", None) or {}).get("category", [])}
    for candidate in ("game", "camera", "video_playback", "video", "audio", "display"):
        if candidate in categories:
            return "video" if candidate == "video_playback" else candidate
    return "compute" if kind == "cpu_task" else kind


def _ip_category(graph: CanonicalScenarioGraph, node: dict[str, Any]) -> str:
    ip_ref = node.get("ip_ref")
    ip_row = graph.ip_catalog.get(ip_ref or "")
    return str(getattr(ip_row, "category", "") or "").lower()


def _node_text(node: dict[str, Any]) -> str:
    return " ".join(str(node.get(key) or "") for key in ("id", "label", "ip_ref", "role", "node_type", "kind")).lower()


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or node.get("id") or "resource").replace("_", " ").upper()


def _badges(kind: str, outgoing: list[dict[str, Any]], buffer_refs: list[str]) -> list[str]:
    labels = {"cpu_task": "CPU", "mfc": "MFC", "dpu": "DPU", "gpu": "GPU", "npu": "NPU", "panel": "EXT"}
    badges = [labels.get(kind, kind.upper())]
    for flow in sorted({_flow_type(edge) for edge in outgoing}):
        if flow not in badges:
            badges.append(flow)
    if buffer_refs:
        badges.append("BUF")
    return badges


def _topology_summary_badges(
    graph: CanonicalScenarioGraph,
    node: dict[str, Any],
    ops: OperationSummary | None,
) -> list[str]:
    kind = _resource_kind(graph, node)
    badges = [_subsystem(kind, graph, node)]
    if _topology_node_type(_topology_layer(graph, node)) == "sw":
        badges.append("<sw>")
    if ops:
        if ops.crop:
            badges.append("Crop")
        if ops.scale:
            badges.append("Scale")
        if ops.rotate is not None:
            badges.append("Rotate")
    return badges


def _topology_operation_summary(
    graph: CanonicalScenarioGraph,
    node_id: str,
    node: dict[str, Any],
) -> OperationSummary | None:
    config = (getattr(graph.variant, "node_configs", None) or {}).get(node_id) or {}
    raw_ops = config.get("operations") if isinstance(config, dict) else None
    if raw_ops is None:
        raw_ops = node.get("operations") if isinstance(node, dict) else None
    if isinstance(raw_ops, dict):
        summary = OperationSummary(
            crop=bool(raw_ops.get("crop")),
            scale=bool(raw_ops.get("scale")),
            scale_from=raw_ops.get("scale_from"),
            scale_to=raw_ops.get("scale_to"),
            rotate=raw_ops.get("rotate"),
            colorspace_convert=raw_ops.get("colorspace_convert"),
        )
        if any((summary.crop, summary.scale, summary.rotate is not None, summary.colorspace_convert)):
            return summary

    return None


def _detail_items(node: dict[str, Any], buffer_refs: list[str]) -> list[str]:
    details = []
    if role := node.get("role"):
        details.append(f"Role: {role}")
    if buffer_refs:
        details.append("Buffers: " + ", ".join(buffer_refs))
    return details


# Topology payload helpers


def _topology_layer(graph: CanonicalScenarioGraph, node: dict[str, Any]) -> str:
    explicit = str(node.get("layer") or "").lower()
    if explicit in {"app", "framework", "hal", "kernel", "external", "hw", "memory"}:
        return explicit
    node_type = str(node.get("node_type") or node.get("kind") or "").lower()
    if node_type in {"sw", "task"}:
        return _sw_layer_for_node(node)
    kind = _resource_kind(graph, node)
    if kind in {"sensor", "panel"}:
        return "external"
    if kind == "cpu_task":
        return _sw_layer_for_node(node)
    return "hw"


def _sw_layer_for_node(node: dict[str, Any]) -> str:
    text = f"{node.get('id', '')} {node.get('role', '')}".lower()
    if any(token in text for token in ("app", "source", "network", "storage")):
        return "app"
    if "hal" in text:
        return "hal"
    if any(token in text for token in ("driver", "v4l2", "drm", "kms", "dsp", "offload")):
        return "kernel"
    return "framework"


def _topology_node_type(layer: str) -> str:
    if layer in {"app", "framework", "hal", "kernel"}:
        return "sw"
    if layer == "memory":
        return "buffer"
    return "ip"


def _topology_stage(kind: str, node: dict[str, Any]) -> str:
    text = f"{node.get('id', '')} {node.get('ip_ref', '')} {node.get('role', '')}".lower()
    if kind == "sensor" or any(token in text for token in ("sensor", "csis", "csi", "pdp")):
        return "capture"
    if kind == "mfc" or any(token in text for token in ("codec", "enc", "dec")):
        return "encode"
    if kind in {"gpu", "dpu", "panel"}:
        return "display"
    return "processing"


def _topology_x(layer: str) -> int:
    return {
        "external": 120,
        "app": 230,
        "framework": 350,
        "hal": 470,
        "kernel": 590,
        "hw": 560,
        "memory": 800,
    }.get(layer, 560)


def _buffer_node_id(buffer_ref: str) -> str:
    return f"buf-{_safe_id(buffer_ref)}"


def _buffer_label(buffer_ref: str) -> str:
    return str(buffer_ref).replace("_", " ").title()


def _memory_descriptor(graph: CanonicalScenarioGraph, buffer_ref: str) -> MemoryDescriptor:
    spec = _buffer_spec(graph, buffer_ref)
    width, height = _buffer_size(graph, spec)
    design = getattr(graph.variant, "design_conditions", None) or {}
    return MemoryDescriptor(
        format=spec.get("format"),
        bitdepth=_as_int(spec.get("bitdepth")),
        planes=_as_int(spec.get("planes")),
        width=width,
        height=height,
        fps=_as_int(design.get("fps") or design.get("target_fps")),
        stride_bytes=_as_int(spec.get("stride_bytes")),
        size_bytes=_as_int(spec.get("size_bytes")),
        alignment=spec.get("alignment"),
        compression=display_compression(spec.get("compression")),
    )


def _memory_placement(graph: CanonicalScenarioGraph, buffer_ref: str) -> MemoryPlacement | None:
    spec = _buffer_spec(graph, buffer_ref)
    placement = spec.get("placement")
    if isinstance(placement, dict):
        return MemoryPlacement(**placement)
    return None


def _buffer_size(graph: CanonicalScenarioGraph, spec: dict[str, Any]) -> tuple[int | None, int | None]:
    size_value = spec.get("size")
    if size_value:
        return _parse_output_size(size_value)
    size_ref = spec.get("size_ref")
    if size_ref:
        overrides = getattr(graph.variant, "size_overrides", None) or {}
        anchors = ((getattr(graph.scenario, "size_profile", None) or {}).get("anchors") or {})
        aliases = {
            "record": "record_out",
            "preview": "preview_out",
            "sensor": "sensor_full",
        }
        ref = aliases.get(str(size_ref), str(size_ref))
        return _parse_size_label(overrides.get(ref) or anchors.get(ref) or anchors.get(str(size_ref)))
    return _parse_size_label(_default_size_label(graph, spec))
    return None, None


def _buffer_detail_items(graph: CanonicalScenarioGraph, buffer_ref: str) -> list[str]:
    spec = _buffer_spec(graph, buffer_ref)
    details = [f"Buffer: {buffer_ref}"]
    if not spec:
        return details
    bits = [
        spec.get("format"),
        spec.get("size") or spec.get("size_ref"),
        f"{spec.get('bitdepth')}b" if spec.get("bitdepth") is not None else None,
        display_compression(spec.get("compression")),
        spec.get("alignment"),
    ]
    summary = " / ".join(str(bit) for bit in bits if bit)
    if summary:
        details.append(summary)
    placement = _memory_placement(graph, buffer_ref)
    if placement and placement.llc_allocated:
        details.append(f"LLC allocation: {_llc_text(placement)}")
    return details


def _edge_detail_items(
    graph: CanonicalScenarioGraph,
    edge: dict[str, Any],
    buffer_ref: str | None,
) -> list[str]:
    details = []
    source = _edge_source(edge)
    target = _edge_target(edge)
    if source and target:
        details.append(f"Route: {source} -> {target}")
    if edge.get("type"):
        details.append(f"Edge type: {edge['type']}")
    if buffer_ref:
        details.extend(_buffer_detail_items(graph, buffer_ref))
    return details


def _buffer_handoffs(
    graph: CanonicalScenarioGraph,
    rows: list[ResourceOverviewRow],
    edges: list[dict[str, Any]],
) -> list[BufferHandoffSummary]:
    row_by_node = {row.node_id: row for row in rows}
    by_buffer: dict[str, dict[str, Any]] = {}
    for edge in edges:
        buffer_ref = edge.get("buffer")
        if not buffer_ref:
            continue
        buffer_ref = str(buffer_ref)
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        item = by_buffer.setdefault(
            buffer_ref,
            {"producer": source, "consumers": [], "subsystem": (row_by_node.get(source) or row_by_node.get(target)).subsystem if (row_by_node.get(source) or row_by_node.get(target)) else "memory"},
        )
        if not item.get("producer"):
            item["producer"] = source
        if target and target not in item["consumers"]:
            item["consumers"].append(target)

    result: list[BufferHandoffSummary] = []
    for buffer_ref, item in by_buffer.items():
        spec = _buffer_spec(graph, buffer_ref)
        placement = _memory_placement(graph, buffer_ref)
        result.append(
            BufferHandoffSummary(
                buffer_ref=buffer_ref,
                subsystem=str(item["subsystem"]),
                producer_node_id=item.get("producer"),
                consumer_node_ids=list(item.get("consumers") or []),
                size_label=_buffer_size_label(graph, spec),
                format=spec.get("format"),
                bitdepth=_as_int(spec.get("bitdepth") or spec.get("bitwidth")),
                compression=display_compression(spec.get("compression")),
                comp_ratio=_as_float(spec.get("comp_ratio") or spec.get("compression_ratio")),
                llc_allocated=bool(placement and placement.llc_allocated),
                llc_policy=placement.llc_policy if placement else None,
                llc_allocation_mb=placement.llc_allocation_mb if placement else None,
            )
        )
    return result


def _buffer_size_label(graph: CanonicalScenarioGraph, spec: dict[str, Any]) -> str | None:
    if spec.get("size"):
        width, height = _parse_output_size(spec["size"])
        return f"{width}x{height}" if width and height else str(spec["size"])
    size_ref = spec.get("size_ref")
    if size_ref:
        width, height = _buffer_size(graph, spec)
        return f"{width}x{height}" if width and height else str(size_ref)
    width = spec.get("width")
    height = spec.get("height")
    if width and height:
        return f"{width}x{height}"
    return _default_size_label(graph, spec)


def _default_size_label(graph: CanonicalScenarioGraph, spec: dict[str, Any]) -> str | None:
    size_profile = getattr(graph.scenario, "size_profile", None) or {}
    anchors = size_profile.get("anchors") or {}
    overrides = getattr(graph.variant, "size_overrides", None) or {}
    format_text = str(spec.get("format") or "").lower()
    if "raw" in format_text or "bayer" in format_text:
        keys = ("sensor_full", "sensor", "record_out", "preview_out")
    else:
        keys = ("record_out", "preview_out", "display_out", "sensor_full")
    for key in keys:
        label = overrides.get(key) or anchors.get(key)
        width, height = _parse_size_label(label)
        if width and height:
            return f"{width}x{height}"
    return _variant_resolution_label(graph)


def _variant_resolution_label(graph: CanonicalScenarioGraph) -> str | None:
    design = getattr(graph.variant, "design_conditions", None) or {}
    resolution = design.get("resolution") or design.get("display_resolution") or design.get("target_resolution")
    if not resolution:
        return None
    width, height = _parse_size_label(resolution)
    if width and height:
        return f"{width}x{height}"
    mapping = {
        "HD": "1280x720",
        "FHD": "1920x1080",
        "FHD+": "1080x2340",
        "QHD": "2560x1440",
        "QHD+": "1440x3200",
        "UHD": "3840x2160",
        "4K": "3840x2160",
        "8K": "7680x4320",
    }
    return mapping.get(str(resolution).upper())


def _llc_text(placement: MemoryPlacement) -> str:
    mb = f" {placement.llc_allocation_mb:g}MB" if placement.llc_allocation_mb else ""
    return f"LLC {placement.llc_policy}{mb}".strip()


# IO and display summaries


def _io_from_buffers(graph: CanonicalScenarioGraph, buffer_refs: list[str]) -> IoSummary | None:
    if not buffer_refs:
        return None
    spec = _buffer_spec(graph, buffer_refs[0])
    if not spec:
        return IoSummary(size_label=buffer_refs[0])
    return IoSummary(
        format=spec.get("format"),
        bitdepth=spec.get("bitdepth"),
        compression=display_compression(spec.get("compression")),
        size_label=str(spec.get("size") or spec.get("size_ref") or buffer_refs[0]),
    )


def _buffer_spec(graph: CanonicalScenarioGraph, buffer_ref: str) -> dict[str, Any]:
    base = ((getattr(graph.scenario, "pipeline", None) or {}).get("buffers") or {}).get(buffer_ref) or {}
    override = (getattr(graph.variant, "buffer_overrides", None) or {}).get(buffer_ref) or {}
    merged = dict(base)
    merged.update(override)
    return merged


def _sensor_summaries(
    graph: CanonicalScenarioGraph,
    rows: list[ResourceOverviewRow],
    edges: list[dict[str, Any]],
) -> list[SensorEndpointSummary]:
    nodes_by_id = {str(node.get("id")): node for node in graph.pipeline_nodes if node.get("id")}
    configs = getattr(graph.variant, "node_configs", None) or {}
    design = getattr(graph.variant, "design_conditions", None) or {}
    sensors: list[SensorEndpointSummary] = []
    for row in rows:
        if row.resource_kind != "sensor":
            continue
        node = nodes_by_id.get(row.node_id, {})
        config = configs.get(row.node_id) or {}
        sensors.append(
            SensorEndpointSummary(
                node_id=row.node_id,
                sensor_mode=config.get("selected_mode") or design.get("sensor_mode"),
                module_ref=str(node.get("ip_ref")) if node.get("ip_ref") else None,
                output=_sensor_output(graph, config),
                downstream=[
                    str(edge.get("to") or edge.get("target"))
                    for edge in _outgoing_edges(row.node_id, edges)
                    if edge.get("to") or edge.get("target")
                ],
            )
        )
    return sensors


def _sensor_output(graph: CanonicalScenarioGraph, config: dict[str, Any]) -> IoSummary | None:
    design = getattr(graph.variant, "design_conditions", None) or {}
    output = (config.get("outputs") or [{}])[0]
    width, height = _parse_output_size(output.get("size"))
    if width is None or height is None:
        width, height = _parse_size_label(
            ((getattr(graph.scenario, "size_profile", None) or {}).get("anchors") or {}).get("sensor_full")
        )
    return IoSummary(
        width=width,
        height=height,
        fps=design.get("fps") or design.get("target_fps"),
        format=output.get("format"),
        bitdepth=output.get("bitdepth") or output.get("bitwidth"),
        compression=display_compression(output.get("compression")),
        size_label=f"{width}x{height}" if width and height else None,
    )


def _parse_output_size(value: Any) -> tuple[int | None, int | None]:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        return _as_int(value[2]), _as_int(value[3])
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _as_int(value[0]), _as_int(value[1])
    if isinstance(value, str):
        return _parse_size_label(value)
    return None, None


def _parse_size_label(value: Any) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    parts = str(value).lower().replace(" ", "").split("x", 1)
    if len(parts) != 2:
        return None, None
    return _as_int(parts[0]), _as_int(parts[1])


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_summaries(graph: CanonicalScenarioGraph, rows: list[ResourceOverviewRow]) -> list[DisplayCompositionSummary]:
    design = getattr(graph.variant, "design_conditions", None) or {}
    display_rows = [row for row in rows if row.resource_kind in {"dpu", "panel"}]
    if not display_rows and not design.get("dpu_composer") and not design.get("dpu_layer_count"):
        return []
    node_id = next((row.node_id for row in display_rows if row.resource_kind == "dpu"), display_rows[0].node_id if display_rows else "display")
    return [
        DisplayCompositionSummary(
            node_id=node_id,
            composer=design.get("dpu_composer"),
            layer_count=design.get("dpu_layer_count"),
            panel_mode=_panel_mode(graph),
            output=None,
            layers=_display_layers(graph, node_id),
        )
    ]


def _display_layers(graph: CanonicalScenarioGraph, dpu_node_id: str) -> list[DisplayLayerSummary]:
    design = getattr(graph.variant, "design_conditions", None) or {}
    configs = getattr(graph.variant, "node_configs", None) or {}
    dpu_config = configs.get(dpu_node_id) or {}
    specs = (
        design.get("display_layers")
        or design.get("composition_layers")
        or dpu_config.get("display_layers")
        or dpu_config.get("composition_layers")
        or dpu_config.get("layers")
        or []
    )
    layers: list[DisplayLayerSummary] = []
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            continue
        layers.append(
            DisplayLayerSummary(
                name=str(spec.get("name") or spec.get("id") or f"Layer {index + 1}"),
                buffer_ref=spec.get("buffer_ref") or spec.get("buffer"),
                format=spec.get("format"),
                src_frame=spec.get("src_frame") or _frame_text(spec.get("src")),
                dst_frame=spec.get("dst_frame") or _frame_text(spec.get("dst")),
                transform=spec.get("transform"),
                alpha=spec.get("alpha"),
            )
        )
    return layers


def _frame_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        return f"{value[0]},{value[1]} {value[2]}x{value[3]}"
    if isinstance(value, dict):
        x = value.get("x", 0)
        y = value.get("y", 0)
        width = value.get("width")
        height = value.get("height")
        if width is not None and height is not None:
            return f"{x},{y} {width}x{height}"
    return None


def _panel_mode(graph: CanonicalScenarioGraph) -> str | None:
    panel_node_ids = [
        str(node.get("id"))
        for node in graph.pipeline_nodes
        if node.get("id") and _resource_kind(graph, node) == "panel"
    ]
    configs = getattr(graph.variant, "node_configs", None) or {}
    for node_id in panel_node_ids:
        selected_mode = (configs.get(node_id) or {}).get("selected_mode")
        if selected_mode:
            return str(selected_mode)
    design = getattr(graph.variant, "design_conditions", None) or {}
    if design.get("panel_fps_hz"):
        return f"{design['panel_fps_hz']}Hz"
    return None


# Metrics


def _metric_breakdown(rows: list[ResourceOverviewRow]) -> list[Level0MetricBreakdown]:
    counts: dict[str, int] = defaultdict(int)
    warnings: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.subsystem] += 1
        if row.status in {"warning", "blocked"}:
            warnings[row.subsystem] += 1
    return [
        Level0MetricBreakdown(subsystem=subsystem, node_count=count, warning_count=warnings[subsystem])
        for subsystem, count in sorted(counts.items())
    ]


def _safe_id(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value)).strip("-")
