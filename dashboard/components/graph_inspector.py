"""Pure data builders for the Pipeline Viewer graph inspector."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Iterable

from scenario_db.api.schemas.view import EdgeData, NodeData, RiskCard, ViewResponse


LAYOUT_NODE_TYPES = {"lane_bg", "lane_label", "stage_header"}


@dataclass(frozen=True)
class InspectorRow:
    label: str
    value: str


@dataclass(frozen=True)
class InspectorSection:
    title: str
    rows: list[InspectorRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class InspectorPanel:
    title: str
    description: str
    sections: list[InspectorSection] = field(default_factory=list)


@dataclass(frozen=True)
class InspectorOption:
    id: str
    label: str


def build_graph_overview(view: ViewResponse) -> InspectorPanel:
    summary = view.summary
    rows = [
        InspectorRow("Scenario", summary.name),
        InspectorRow("Variant", summary.variant_id),
        InspectorRow("Level", str(view.level)),
    ]
    if view.mode:
        rows.append(InspectorRow("Mode", view.mode))
    expand = view.metadata.get("expand")
    if expand:
        rows.append(InspectorRow("Expand", str(expand)))
    rows.extend(
        [
            InspectorRow("Nodes", str(len(view.nodes))),
            InspectorRow("Edges", str(len(view.edges))),
        ]
    )
    if _has_visual_timing_context(view):
        if _valid(summary.resolution):
            rows.append(InspectorRow("Resolution", summary.resolution))
        if summary.fps:
            rows.append(InspectorRow("Frame Rate", f"{summary.fps:g} fps"))
        if summary.period_ms:
            rows.append(InspectorRow("Period", f"{summary.period_ms:g} ms"))
        if summary.budget_ms:
            rows.append(InspectorRow("Budget", f"{summary.budget_ms:g} ms"))

    sections = [
        InspectorSection("Scenario", rows=rows),
        _overview_structure_section(view),
        _risk_section(view.risks),
        _simulation_overview_section(view),
    ]
    if view.metadata.get("level2_available") is False:
        sections.insert(1, _unavailable_section(view))
    return InspectorPanel(
        title="Graph Overview",
        description="Scenario-level context for the currently loaded graph.",
        sections=[section for section in sections if section.rows or section.notes],
    )


def inspector_heading_html(title: str = "Graph Inspector") -> str:
    return f'<div class="inspector-panel-heading">{escape(title)}</div>'


def inspector_view_source(level: int, primary: ViewResponse, topology: ViewResponse) -> ViewResponse:
    """Use the rendered graph as the node/edge source for the side inspector."""
    if level == 0:
        return topology
    return primary


def build_node_inspector(view: ViewResponse, node_id: str) -> InspectorPanel:
    node = _node_map(view).get(node_id)
    if node is None:
        return InspectorPanel(
            title="Node not found",
            description=f"No node with id '{node_id}' exists in the current graph.",
            sections=[],
        )

    sections = [
        _node_identity_section(node),
        _node_classification_section(node),
        _node_operation_section(node),
        _node_memory_section(node),
        _node_buffer_io_section(view, node),
        _node_simulation_section(node),
        _risk_section(_risks_for_node(view.risks, node)),
        _node_details_section(node),
    ]
    return InspectorPanel(
        title=_first_line(node.label),
        description=f"Selected node '{node.id}' from the current graph.",
        sections=[section for section in sections if section.rows or section.notes],
    )


def build_edge_inspector(view: ViewResponse, edge_id: str) -> InspectorPanel:
    edge = _edge_map(view).get(edge_id)
    if edge is None:
        return InspectorPanel(
            title="Edge not found",
            description=f"No edge with id '{edge_id}' exists in the current graph.",
            sections=[],
        )
    nodes = _node_map(view)
    source = _node_label(nodes.get(edge.source)) or edge.source
    target = _node_label(nodes.get(edge.target)) or edge.target
    rows = [
        InspectorRow("Flow", edge.flow_type),
        InspectorRow("Source", source),
        InspectorRow("Target", target),
    ]
    _append(rows, "Latency", edge.latency_class)
    _append(rows, "Buffer", edge.buffer_ref)
    _append(rows, "Producer", edge.producer)
    _append(rows, "Consumer", edge.consumer)
    _append(rows, "Memory", _memory_text(edge.memory))
    _append(rows, "LLC", _llc_text(edge.placement))
    _append(rows, "Simulation", _edge_sim_text(edge))

    sections = [InspectorSection("Route", rows=rows), _edge_details_section(edge)]
    return InspectorPanel(
        title=f"{source} -> {target}",
        description=f"Selected edge '{edge.id}' from the current graph.",
        sections=[section for section in sections if section.rows or section.notes],
    )


def node_options(view: ViewResponse) -> list[InspectorOption]:
    return [
        InspectorOption(id=node.data.id, label=_option_label(node.data))
        for node in view.nodes
        if node.data.type not in LAYOUT_NODE_TYPES
    ]


def edge_options(view: ViewResponse) -> list[InspectorOption]:
    nodes = _node_map(view)
    options = []
    for edge in view.edges:
        source = _node_label(nodes.get(edge.data.source)) or edge.data.source
        target = _node_label(nodes.get(edge.data.target)) or edge.data.target
        label = f"{source} -> {target}"
        if edge.data.buffer_ref:
            label = f"{label} ({edge.data.buffer_ref})"
        options.append(InspectorOption(id=edge.data.id, label=label))
    return options


def _node_identity_section(node: NodeData) -> InspectorSection:
    rows = [
        InspectorRow("Type", node.type),
        InspectorRow("Layer", node.layer),
    ]
    _append(rows, "IP", node.ip_ref)
    _append(rows, "SW", node.sw_ref)
    return InspectorSection("Identity", rows=rows)


def _node_classification_section(node: NodeData) -> InspectorSection:
    rows: list[InspectorRow] = []
    _append(rows, "Hierarchy", node.hierarchy_group)
    _append(rows, "IP Block", node.ip_group)
    _append(rows, "DVFS", node.dvfs_group)
    _append(rows, "Role HW", node.role_hw_name)
    _append(rows, "Module", node.module_ref)
    _append(rows, "Module Kind", node.module_kind)
    _append(rows, "Direction", node.module_direction)
    _append(rows, "Status", node.module_status)
    _append(rows, "Port", node.port_ref)
    if node.summary_badges:
        rows.append(InspectorRow("Summary", ", ".join(node.summary_badges[:6])))
    if node.capability_badges:
        rows.append(InspectorRow("Capabilities", ", ".join(node.capability_badges[:8])))
    return InspectorSection("Classification", rows=rows)


def _node_operation_section(node: NodeData) -> InspectorSection:
    rows: list[InspectorRow] = []
    _append(rows, "Operations", _operation_text(node))
    return InspectorSection("Operations", rows=rows)


def _node_memory_section(node: NodeData) -> InspectorSection:
    rows: list[InspectorRow] = []
    _append(rows, "Memory", _memory_text(node.memory))
    _append(rows, "LLC", _llc_text(node.placement))
    return InspectorSection("Memory", rows=rows)


def _node_buffer_io_section(view: ViewResponse, node: NodeData) -> InspectorSection:
    notes: list[str] = []
    for edge in view.edges:
        data = edge.data
        if data.target == node.id:
            text = f"Input: {data.buffer_ref or data.id}"
            if data.producer:
                text = f"{text} from {data.producer}"
            notes.append(text)
        elif data.source == node.id:
            text = f"Output: {data.buffer_ref or data.id}"
            if data.consumer:
                text = f"{text} to {data.consumer}"
            notes.append(text)
    notes.extend(node.detail_items)
    return InspectorSection("Buffer I/O", notes=_unique(notes))


def _node_simulation_section(node: NodeData) -> InspectorSection:
    rows: list[InspectorRow] = []
    _append(rows, "Simulation", _node_sim_text(node))
    if node.sim_overlay and node.sim_overlay.evidence_id:
        rows.append(InspectorRow("Evidence", node.sim_overlay.evidence_id))
    return InspectorSection("Simulation", rows=rows)


def _node_details_section(node: NodeData) -> InspectorSection:
    rows: list[InspectorRow] = []
    if node.shared_resource:
        rows.append(InspectorRow("Shared", "yes"))
    if node.dma_count is not None:
        rows.append(InspectorRow("DMA Count", str(node.dma_count)))
    if node.warning:
        rows.append(InspectorRow("Warning", node.severity or "active"))
    return InspectorSection("Details", rows=rows)


def _edge_details_section(edge: EdgeData) -> InspectorSection:
    rows: list[InspectorRow] = []
    if edge.label:
        rows.append(InspectorRow("Label", edge.label))
    return InspectorSection("Details", rows=rows, notes=list(edge.detail_items))


def _overview_structure_section(view: ViewResponse) -> InspectorSection:
    rows: list[InspectorRow] = []
    counts: dict[str, int] = {}
    for node in view.nodes:
        if node.data.type in LAYOUT_NODE_TYPES:
            continue
        key = node.data.hierarchy_group or node.data.ip_group or node.data.layer or node.data.type
        counts[key] = counts.get(key, 0) + 1
    for key in sorted(counts):
        rows.append(InspectorRow(key, str(counts[key])))
    return InspectorSection("Structure", rows=rows)


def _unavailable_section(view: ViewResponse) -> InspectorSection:
    notes = [str(item) for item in view.metadata.get("unavailable_reasons") or []]
    notes.extend(str(item) for item in view.metadata.get("required_data") or [])
    return InspectorSection("Unavailable", notes=notes)


def _risk_section(risks: Iterable[RiskCard]) -> InspectorSection:
    notes = [f"{risk.severity}: {risk.title} - {risk.impact}" for risk in risks]
    return InspectorSection("Risks", notes=notes or ["No active risk cards."])


def _simulation_overview_section(view: ViewResponse) -> InspectorSection:
    rows: list[InspectorRow] = []
    sim_nodes = [node.data for node in view.nodes if node.data.sim_overlay is not None]
    if sim_nodes:
        rows.append(InspectorRow("Node overlays", str(len(sim_nodes))))
    sim_edges = [edge.data for edge in view.edges if edge.data.sim_overlay is not None]
    if sim_edges:
        rows.append(InspectorRow("Edge overlays", str(len(sim_edges))))
    if "simulation" in view.overlays_available:
        rows.append(InspectorRow("Status", "loaded"))
    return InspectorSection("Simulation Overlay", rows=rows, notes=[] if rows else ["No simulation overlay loaded."])


def _risks_for_node(risks: list[RiskCard], node: NodeData) -> list[RiskCard]:
    if node.matched_issues:
        wanted = set(node.matched_issues)
        return [risk for risk in risks if risk.id in wanted]
    label = _first_line(node.label).lower()
    keys = {value.lower() for value in [node.id, node.ip_ref, node.ip_group, node.role_hw_name] if value}
    keys.add(label)
    return [
        risk
        for risk in risks
        if risk.component.lower() in keys or risk.component.lower() in label
    ]


def _node_map(view: ViewResponse) -> dict[str, NodeData]:
    return {node.data.id: node.data for node in view.nodes}


def _edge_map(view: ViewResponse) -> dict[str, EdgeData]:
    return {edge.data.id: edge.data for edge in view.edges}


def _node_label(node: NodeData | None) -> str | None:
    if node is None:
        return None
    return _first_line(node.label)


def _option_label(node: NodeData) -> str:
    label = _first_line(node.label)
    if node.type == "buffer":
        return f"{label} [buffer]"
    if node.module_kind:
        return f"{label} [{node.module_kind}]"
    if node.ip_group and node.ip_group.lower() != label.lower():
        return f"{label} [{node.ip_group}]"
    return label


def _operation_text(node: NodeData) -> str | None:
    ops = node.active_operations
    if ops is None:
        return None
    labels: list[str] = []
    if ops.crop:
        labels.append("Crop")
    if ops.scale:
        label = "Scale"
        if ops.scale_from and ops.scale_to:
            label = f"{label} {ops.scale_from} -> {ops.scale_to}"
        labels.append(label)
    if ops.rotate is not None:
        labels.append(f"Rotate {ops.rotate}")
    if ops.colorspace_convert:
        labels.append(f"CSC {ops.colorspace_convert}")
    if ops.compose:
        labels.append("Compose")
    return ", ".join(labels) if labels else None


def _memory_text(memory) -> str | None:
    if memory is None:
        return None
    parts: list[str] = []
    _add(parts, memory.format)
    if memory.width and memory.height:
        parts.append(f"{memory.width}x{memory.height}")
    if memory.fps:
        parts.append(f"{memory.fps:g}fps")
    if memory.bitdepth:
        parts.append(f"{memory.bitdepth:g}b")
    _add(parts, memory.compression)
    if memory.size_bytes:
        parts.append(f"{int(memory.size_bytes)} B")
    return " / ".join(parts) if parts else None


def _llc_text(placement) -> str | None:
    if placement is None or not placement.llc_allocated:
        return None
    text = placement.llc_policy or "allocated"
    if placement.llc_allocation_mb:
        text = f"{text} {placement.llc_allocation_mb:g}MB"
    if placement.allocation_owner:
        text = f"{text} by {placement.allocation_owner}"
    return text


def _node_sim_text(node: NodeData) -> str | None:
    overlay = node.sim_overlay
    if overlay is None:
        return None
    parts: list[str] = []
    if overlay.power_mw is not None:
        parts.append(f"{overlay.power_mw:g}mW")
    if overlay.set_clock_mhz is not None:
        parts.append(f"{overlay.set_clock_mhz:g}MHz")
    if overlay.hw_time_ms is not None:
        parts.append(f"{overlay.hw_time_ms:g}ms")
    if overlay.feasible is False:
        parts.append("not feasible")
    return " / ".join(parts) if parts else None


def _edge_sim_text(edge: EdgeData) -> str | None:
    overlay = edge.sim_overlay
    if overlay is None:
        return None
    parts: list[str] = []
    if overlay.bw_mbs is not None:
        parts.append(f"{overlay.bw_mbs:g}MB/s")
    if overlay.bw_power_mw is not None:
        parts.append(f"{overlay.bw_power_mw:g}mW")
    if overlay.bw_mbs_worst is not None:
        parts.append(f"worst {overlay.bw_mbs_worst:g}MB/s")
    return " / ".join(parts) if parts else None


def _has_visual_timing_context(view: ViewResponse) -> bool:
    overview = view.level0_resource_overview
    if overview is not None:
        subsystems = {row.subsystem.lower() for row in overview.rows}
        if overview.sensors:
            return True
        return bool(subsystems & {"camera", "video", "display", "game", "ai"})

    semantic_tokens: set[str] = set()
    for node in view.nodes:
        semantic_tokens.update(item.lower() for item in node.data.summary_badges)
        for value in [node.data.hierarchy_group, node.data.ip_group, node.data.role_hw_name]:
            if value:
                semantic_tokens.update(value.lower().replace("/", " ").split())
    if semantic_tokens & {"camera", "video", "display", "game", "ai", "isp", "dpu", "gpu", "npu"}:
        return True

    text = f"{view.summary.name} {view.scenario_id} {view.variant_id}".lower()
    if "audio" in text and not any(key in text for key in ["camera", "video", "display", "game", "ai"]):
        return False
    return any(key in text for key in ["camera", "video", "display", "game", "ai"])


def _append(rows: list[InspectorRow], label: str, value: object | None) -> None:
    if value is None or value == "":
        return
    rows.append(InspectorRow(label, str(value)))


def _add(values: list[str], value: object | None) -> None:
    if value is None or value == "":
        return
    values.append(str(value))


def _valid(value: str | None) -> bool:
    return bool(value and value.lower() not in {"unknown", "n/a", "-"})


def _first_line(value: str) -> str:
    return value.splitlines()[0].strip()


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values
