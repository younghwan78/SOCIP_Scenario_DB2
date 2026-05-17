"""Level 0 v2 resource-flow projection helpers."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from scenario_db.api.schemas.view import (
    DisplayCompositionSummary,
    DisplayLayerSummary,
    IoSummary,
    Level0MetricBreakdown,
    Level0ResourceOverview,
    ResourceOverviewRow,
    SensorEndpointSummary,
)
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph


def build_resource_overview(graph: CanonicalScenarioGraph) -> Level0ResourceOverview:
    """Build a resource-first Level 0 overview from the effective graph."""

    nodes = list(graph.pipeline_nodes)
    edges = list(graph.pipeline_edges)
    ordered_nodes = _topological_nodes(nodes, edges)
    rows = [
        _row_for_node(graph, node, index + 1, edges)
        for index, node in enumerate(ordered_nodes)
    ]
    return Level0ResourceOverview(
        rows=rows,
        metric_breakdown=_metric_breakdown(rows),
        sensors=_sensor_summaries(graph, rows, edges),
        displays=_display_summaries(graph, rows),
        notes=[],
    )


# Active graph ordering


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
    buffer_refs = [str(edge.get("buffer")) for edge in outgoing if edge.get("buffer")]
    return ResourceOverviewRow(
        sequence_index=sequence_index,
        node_id=node_id,
        label=_node_label(node),
        resource_domain=_resource_domain(kind, node),
        resource_kind=kind,
        subsystem=_subsystem(kind, graph, node),
        role=node.get("role"),
        input=_io_from_buffers(graph, [str(edge.get("buffer")) for edge in _incoming_edges(node_id, edges) if edge.get("buffer")]),
        output=_io_from_buffers(graph, buffer_refs),
        flow=_flow_summary(outgoing),
        buffer_refs=buffer_refs,
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


def _detail_items(node: dict[str, Any], buffer_refs: list[str]) -> list[str]:
    details = []
    if role := node.get("role"):
        details.append(f"Role: {role}")
    if buffer_refs:
        details.append("Buffers: " + ", ".join(buffer_refs))
    return details


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
        compression=spec.get("compression"),
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
        compression=output.get("compression"),
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
