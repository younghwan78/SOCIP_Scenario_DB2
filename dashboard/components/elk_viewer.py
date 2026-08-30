"""ELK/SVG renderer for ScenarioDB pipeline views.

The backend keeps returning the existing ViewResponse projection.  This module
turns that projection into an ELK compound graph and renders it as an SVG
diagram in Streamlit.  Level 0 architecture is intentionally transformed into
App/Framework/HAL/Kernel/HW/Memory hierarchy groups; topology and drill-down
views keep their current graph content and use the same renderer.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

from dashboard.components.viewer_theme import EDGE_COLOR, LAYER_GRADIENT
from scenario_db.api.schemas.view import EdgeElement, NodeElement, ViewResponse

ALL_LAYERS = ["app", "framework", "hal", "kernel", "external", "hw", "memory"]
ALL_EDGE_TYPES = ["OTF", "vOTF", "M2M", "control", "risk"]

LAYER_LABELS = {
    "app": "App",
    "framework": "Framework",
    "hal": "HAL",
    "kernel": "Kernel",
    "external": "External",
    "hw": "HW",
    "memory": "Memory",
}

LAYER_TINT = {
    "app": "#F3ECFF",
    "framework": "#ECF2FF",
    "hal": "#E9FBF8",
    "kernel": "#F2ECFF",
    "external": "#F8FAFC",
    "hw": "#FFF4E8",
    "memory": "#E9FBF6",
    "meta": "#F8FAFC",
}

TYPE_STYLE = {
    "sw": {"fill": "#FFFFFF", "stroke": "#64748B", "text": "#1F2937"},
    "ip": {"fill": "#FED7AA", "stroke": "#F97316", "text": "#7C2D12"},
    "external": {"fill": "#F8FAFC", "stroke": "#64748B", "text": "#334155"},
    "isp": {"fill": "#FFEDD5", "stroke": "#F97316", "text": "#7C2D12"},
    "codec": {"fill": "#F5F3FF", "stroke": "#7C3AED", "text": "#4C1D95"},
    "display": {"fill": "#E8F1EF", "stroke": "#2F6F68", "text": "#174D47"},
    "accelerator": {"fill": "#ECFDF5", "stroke": "#059669", "text": "#064E3B"},
    "submodule": {"fill": "#E8F1EF", "stroke": "#3D8A82", "text": "#174D47"},
    "dma_group": {"fill": "#FFEDD5", "stroke": "#F97316", "text": "#7C2D12"},
    "dma_channel": {"fill": "#FFF7ED", "stroke": "#FB923C", "text": "#7C2D12"},
    "sysmmu": {"fill": "#E2E8F0", "stroke": "#64748B", "text": "#334155"},
    "buffer": {"fill": "#CCFBF1", "stroke": "#0F766E", "text": "#064E3B"},
    "group": {"fill": "#F8FAFC", "stroke": "#CBD5E1", "text": "#334155"},
}

SUBSYSTEM_STYLE = {
    "camera": {"fill": "#FFE4D6", "stroke": "#C2410C", "text": "#7C2D12"},
    "video": {"fill": "#F1EAFE", "stroke": "#7C3AED", "text": "#4C1D95"},
    "display": {"fill": "#E0F2FE", "stroke": "#0284C7", "text": "#075985"},
    "ai": {"fill": "#FCE7F3", "stroke": "#DB2777", "text": "#831843"},
    "game": {"fill": "#FEF3C7", "stroke": "#D97706", "text": "#78350F"},
    "audio": {"fill": "#EDE9FE", "stroke": "#6D28D9", "text": "#4C1D95"},
    "compute": {"fill": "#F1F5F9", "stroke": "#475569", "text": "#1E293B"},
}

LLC_BUFFER_STYLE = {"fill": "#DCFCE7", "stroke": "#16A34A", "text": "#064E3B"}

MODULE_KIND_STYLE = {
    "rdma": {"fill": "#EEF2FF", "stroke": "#4F46E5", "text": "#312E81"},
    "wdma": {"fill": "#FFF7ED", "stroke": "#EA580C", "text": "#7C2D12"},
    "dma": {"fill": "#F5F3FF", "stroke": "#7C3AED", "text": "#4C1D95"},
    "cin": {"fill": "#E0F2FE", "stroke": "#0284C7", "text": "#075985"},
    "cout": {"fill": "#ECFDF5", "stroke": "#059669", "text": "#064E3B"},
    "port": {"fill": "#F8FAFC", "stroke": "#64748B", "text": "#334155"},
    "module": {"fill": "#F8FAFC", "stroke": "#64748B", "text": "#334155"},
}

HIERARCHY_GROUP_STYLE = {
    "Sensor": {"fill": "#EFF6FF", "stroke": "#60A5FA", "text": "#1E3A8A"},
    "ISP": {"fill": "#ECFDF5", "stroke": "#34D399", "text": "#064E3B"},
    "Compute": {"fill": "#F0FDF4", "stroke": "#22C55E", "text": "#14532D"},
    "CODEC": {"fill": "#FFF7ED", "stroke": "#FB923C", "text": "#7C2D12"},
    "DPU": {"fill": "#E0F2FE", "stroke": "#38BDF8", "text": "#075985"},
    "Display": {"fill": "#E0F2FE", "stroke": "#38BDF8", "text": "#075985"},
    "GPU": {"fill": "#F0FDFA", "stroke": "#14B8A6", "text": "#134E4A"},
    "NPU": {"fill": "#FCE7F3", "stroke": "#DB2777", "text": "#831843"},
    "CPU/SW": {"fill": "#F8FAFC", "stroke": "#64748B", "text": "#334155"},
    "Memory": {"fill": "#FEFCE8", "stroke": "#CA8A04", "text": "#713F12"},
}

IP_GROUP_STYLE = {
    "CSIS": {"fill": "#E0F2FE", "stroke": "#0284C7", "text": "#075985"},
    "CSIS/PDP": {"fill": "#DBEAFE", "stroke": "#2563EB", "text": "#1E3A8A"},
    "3AA/CSTAT": {"fill": "#E0E7FF", "stroke": "#4F46E5", "text": "#312E81"},
    "BYRP": {"fill": "#D9F99D", "stroke": "#65A30D", "text": "#365314"},
    "RGBP": {"fill": "#FFE4E6", "stroke": "#E11D48", "text": "#881337"},
    "YUVSC": {"fill": "#FEF3C7", "stroke": "#D97706", "text": "#78350F"},
    "MTNR": {"fill": "#EDE9FE", "stroke": "#7C3AED", "text": "#4C1D95"},
    "MSNR": {"fill": "#FCE7F3", "stroke": "#DB2777", "text": "#831843"},
    "YUVP": {"fill": "#E0F2FE", "stroke": "#0284C7", "text": "#075985"},
    "MCSC": {"fill": "#F5F3FF", "stroke": "#7C3AED", "text": "#4C1D95"},
    "GDC": {"fill": "#FAE8FF", "stroke": "#C026D3", "text": "#701A75"},
    "LME": {"fill": "#FFE4E6", "stroke": "#E11D48", "text": "#881337"},
    "ISP Core": {"fill": "#DCFCE7", "stroke": "#16A34A", "text": "#14532D"},
    "SGPU": {"fill": "#D1FAE5", "stroke": "#059669", "text": "#064E3B"},
    "MFC": {"fill": "#FFEDD5", "stroke": "#EA580C", "text": "#7C2D12"},
    "APV": {"fill": "#FEF3C7", "stroke": "#D97706", "text": "#78350F"},
    "DPU": {"fill": "#E0F2FE", "stroke": "#0284C7", "text": "#075985"},
    "Panel": {"fill": "#F0F9FF", "stroke": "#0EA5E9", "text": "#075985"},
    "GPU": {"fill": "#CCFBF1", "stroke": "#0F766E", "text": "#134E4A"},
    "NPU": {"fill": "#FCE7F3", "stroke": "#DB2777", "text": "#831843"},
    "CPU/SW": {"fill": "#F1F5F9", "stroke": "#475569", "text": "#1E293B"},
    "Sensor": {"fill": "#DBEAFE", "stroke": "#2563EB", "text": "#1E3A8A"},
}

DEFAULT_SIZE = {
    "sw": (165, 52),
    "ip": (150, 58),
    "submodule": (150, 54),
    "dma_group": (185, 60),
    "dma_channel": (205, 56),
    "sysmmu": (185, 56),
    "buffer": (210, 60),
}


def render_elk_view(
    view: ViewResponse,
    *,
    canvas_height: int | None = None,
    title: str | None = None,
) -> None:
    """Render a ViewResponse using ELK orthogonal routing.

    The live embed references the ELK runtime through Streamlit static serving
    when available, so the ~1.6MB library is fetched and cached once by the
    browser instead of being inlined into every iframe on every rerun.
    """
    height = canvas_height or int(view.metadata.get("canvas_h") or 900)
    html_text = build_elk_view_html(
        view,
        canvas_height=height,
        title=title,
        inline_runtime=not _static_elk_available(),
    )
    components.html(html_text, height=height + 52, scrolling=False)


def build_elk_view_html(
    view: ViewResponse,
    *,
    canvas_height: int | None = None,
    title: str | None = None,
    inline_runtime: bool = True,
) -> str:
    """Return standalone ELK/SVG HTML for Streamlit embedding or export.

    ``inline_runtime=True`` (default) embeds the ELK library so the document is
    self-contained — required for HTML export. Pass ``False`` to reference the
    library via the Streamlit static route instead.
    """
    graph, meta = build_elk_graph(view)
    height = canvas_height or int(view.metadata.get("canvas_h") or 900)
    return _html(graph, meta, title or "ScenarioDB View", height, inline_runtime=inline_runtime)


def build_elk_graph(view: ViewResponse) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build an ELK graph and rendering metadata from a ViewResponse.

    This function is intentionally testable without Streamlit/browser runtime.
    """
    layout = str(view.metadata.get("layout") or "")
    if layout == "layered-lanes":
        graph, meta = _build_layered_architecture(view)
    else:
        graph, meta = _build_grouped_graph(view)
    _apply_io_size_subtitles(view, meta)
    _apply_module_state_colors(view, meta)
    _dedupe_buffer_edge_labels(view, graph)
    return graph, meta


# Legacy Level 2 module color language: DMA tint encodes the active
# compression/LLC state so the memory strategy reads at a glance.
MODULE_STATE_COLORS: dict[str, tuple[str, str]] = {
    "comp_llc": ("#F8BBD0", "#C2185B"),  # pink — compression + LLC
    "comp": ("#FFE0B2", "#E65100"),      # orange — compression only
    "llc": ("#E1BEE7", "#7B1FA2"),       # purple — LLC only
    "rdma": ("#D2E3FC", "#1967D2"),      # pastel blue — read DMA
    "wdma": ("#FEEFC3", "#B06000"),      # pastel amber — write DMA
    "cin": ("#CEEAD6", "#137333"),       # pastel green — input FIFO
    "cout": ("#E8DAEF", "#7B1FA2"),      # pastel purple — output FIFO
}

_DMA_MODULE_KINDS = {"rdma", "wdma", "dma"}


def _compression_active(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return bool(text) and text not in {"COMP_OFF", "OFF", "NONE", "DISABLE", "DISABLED"}


def _apply_module_state_colors(view: ViewResponse, meta: dict[str, Any]) -> None:
    """Tint Level 2 I/O module nodes by their active memory strategy."""

    comp_nodes: set[str] = set()
    llc_nodes: set[str] = set()
    for edge in view.edges:
        endpoints = (edge.data.source, edge.data.target)
        if edge.data.memory and _compression_active(edge.data.memory.compression):
            comp_nodes.update(endpoints)
        if edge.data.placement and edge.data.placement.llc_allocated:
            llc_nodes.update(endpoints)

    for node in view.nodes:
        node_meta = meta.get(node.data.id)
        kind = str(node.data.module_kind or "").lower()
        if not node_meta or not kind:
            continue
        if kind in {"cin", "cout"}:
            fill, stroke = MODULE_STATE_COLORS[kind]
        elif kind in _DMA_MODULE_KINDS:
            has_comp = node.data.id in comp_nodes
            has_llc = node.data.id in llc_nodes
            if has_comp and has_llc:
                fill, stroke = MODULE_STATE_COLORS["comp_llc"]
            elif has_comp:
                fill, stroke = MODULE_STATE_COLORS["comp"]
            elif has_llc:
                fill, stroke = MODULE_STATE_COLORS["llc"]
            elif kind == "rdma" or node.data.module_direction == "input":
                fill, stroke = MODULE_STATE_COLORS["rdma"]
            else:
                fill, stroke = MODULE_STATE_COLORS["wdma"]
        else:
            continue
        node_meta["fill"] = fill
        node_meta["stroke"] = stroke


def _dedupe_buffer_edge_labels(view: ViewResponse, graph: dict[str, Any]) -> None:
    """Collapse transfer descriptors on edges that touch a buffer node.

    In views where buffers render as nodes (Level 0 topology), the buffer node
    already carries the full memory descriptor; repeating it on both adjacent
    edges is noise, so those edges fall back to their flow-type chip.
    """

    buffer_ids = {node.data.id for node in view.nodes if node.data.type == "buffer"}
    if not buffer_ids:
        return
    flow_by_edge = {edge.data.id: edge.data for edge in view.edges}

    def walk(container: dict[str, Any]) -> None:
        for edge in container.get("edges", []):
            data = flow_by_edge.get(edge.get("id"))
            if not data:
                continue
            if data.source in buffer_ids or data.target in buffer_ids:
                chip = "SW" if data.flow_type == "control" else data.flow_type
                for label in edge.get("labels", []):
                    label["text"] = chip
                    label["width"] = max(38, len(chip) * 6 + 14)
        for child in container.get("children", []):
            walk(child)

    walk(graph)


def _apply_io_size_subtitles(view: ViewResponse, meta: dict[str, Any]) -> None:
    """Annotate HW/SW leaf nodes with their IO size, legacy-view style.

    Sizes seed from edge memory descriptors and from explicit scale
    operations, then propagate along streaming (OTF/vOTF) edges — an OTF hop
    keeps the size unless the consumer scales. Nodes whose input and output
    sizes differ render as ``in→out``.
    """

    in_size: dict[str, tuple[int, int]] = {}
    out_size: dict[str, tuple[int, int]] = {}

    def parse(value: Any) -> tuple[int, int] | None:
        parts = str(value or "").lower().replace(" ", "").split("x", 1)
        if len(parts) != 2:
            return None
        try:
            width, height = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        return (width, height) if width and height else None

    for node in view.nodes:
        op = node.data.active_operations
        if op and op.scale:
            scale_from = parse(op.scale_from)
            scale_to = parse(op.scale_to)
            if scale_from:
                in_size[node.data.id] = scale_from
            if scale_to:
                out_size[node.data.id] = scale_to

    for edge in view.edges:
        mem = edge.data.memory
        if mem and mem.width and mem.height:
            size = (mem.width, mem.height)
            out_size.setdefault(edge.data.source, size)
            in_size.setdefault(edge.data.target, size)

    streaming_edges = [edge.data for edge in view.edges if edge.data.flow_type in {"OTF", "vOTF"}]
    for _ in range(max(1, len(view.nodes))):
        changed = False
        for data in streaming_edges:
            source_out = out_size.get(data.source)
            if source_out and data.target not in in_size:
                in_size[data.target] = source_out
                changed = True
            if data.target in in_size and data.target not in out_size:
                out_size[data.target] = in_size[data.target]
                changed = True
            target_in = in_size.get(data.target)
            if target_in and data.source not in out_size:
                out_size[data.source] = target_in
                changed = True
        if not changed:
            break

    for node in view.nodes:
        node_id = node.data.id
        node_meta = meta.get(node_id)
        if not node_meta or node_meta.get("subtitle"):
            continue
        if node.data.type not in {"ip", "submodule", "sw", "dma_channel"}:
            continue
        into = in_size.get(node_id)
        out = out_size.get(node_id)
        if into and out and into != out:
            node_meta["subtitle"] = f"{into[0]}x{into[1]}→{out[0]}x{out[1]}"
            op_badges = node_meta.setdefault("op_badges", [])
            if "S" not in op_badges:
                op_badges.append("S")
        elif out or into:
            size = out or into
            node_meta["subtitle"] = f"{size[0]}x{size[1]}"


def _build_layered_architecture(view: ViewResponse) -> tuple[dict[str, Any], dict[str, Any]]:
    meta: dict[str, Any] = {"__view__": _view_meta(view)}
    nodes_by_layer: dict[str, list[NodeElement]] = defaultdict(list)
    for node in _functional_nodes(view.nodes):
        layer = node.data.layer if node.data.layer in ALL_LAYERS else "hw"
        nodes_by_layer[layer].append(node)

    groups_by_layer: dict[str, dict[str, Any]] = {}
    widths = {
        "app": 300,
        "framework": 430,
        "hal": 430,
        "kernel": 430,
        "external": 330,
        "hw": 430,
        "memory": 430,
    }
    for layer in ALL_LAYERS:
        layer_nodes = _sort_nodes(nodes_by_layer.get(layer, []))
        if not layer_nodes or layer not in widths:
            continue
        group, _ = _manual_layer_group(
            layer,
            layer_nodes,
            meta,
            x=0,
            y=0,
            width=widths[layer],
            columns=_manual_layer_columns(layer, len(layer_nodes)),
        )
        groups_by_layer[layer] = group

    groups, positions, graph_width, graph_height = _position_layer_rows(groups_by_layer)

    edges = _manual_edges(view.edges, meta, positions)
    graph = {
        "id": "root",
        "manualLayout": True,
        "width": graph_width,
        "height": graph_height,
        "layoutOptions": {"elk.algorithm": "manual"},
        "children": groups,
        "edges": edges,
    }
    return graph, meta


def _build_grouped_graph(view: ViewResponse) -> tuple[dict[str, Any], dict[str, Any]]:
    meta: dict[str, Any] = {"__view__": _view_meta(view)}
    group_nodes = [node for node in view.nodes if _is_group_box(node)]
    leaf_nodes = [node for node in _functional_nodes(view.nodes) if not _is_group_box(node)]
    group_by_id = {node.data.id: node for node in group_nodes}
    children_by_group: dict[str, list[NodeElement]] = defaultdict(list)

    assigned_groups: set[str] = set()
    for group in group_nodes:
        parent = group.data.parent
        if parent and parent in group_by_id:
            children_by_group[parent].append(group)
            assigned_groups.add(group.data.id)

    assigned: set[str] = set()
    for node in leaf_nodes:
        parent = node.data.parent
        if parent and parent in group_by_id:
            children_by_group[parent].append(node)
            assigned.add(node.data.id)

    # Legacy/reference views do not always carry semantic parent IDs.  Keep the
    # coordinate containment fallback for those, but prefer explicit ownership.
    for group in _sort_nodes(group_nodes):
        contained = [node for node in leaf_nodes if node.data.id not in assigned and _inside_group(group, node)]
        if not contained:
            continue
        children_by_group[group.data.id].extend(contained)
        assigned.update(node.data.id for node in contained)

    children: list[dict[str, Any]] = []
    for group in _sort_nodes([node for node in group_nodes if node.data.id not in assigned_groups]):
        if not children_by_group.get(group.data.id):
            continue
        children.append(
            _elk_group_from_node(group, _group_children(group.data.id, children_by_group, meta), meta, direction="DOWN")
        )

    for node in _sort_nodes([node for node in leaf_nodes if node.data.id not in assigned]):
        children.append(_elk_leaf(node, meta))

    graph = _elk_root(
        children=children,
        edges=_elk_edges(view.edges, meta),
        direction="DOWN",
        spacing=54,
        node_node=36,
        hierarchy=True,
    )
    return graph, meta


def _group_children(
    group_id: str,
    children_by_group: dict[str, list[NodeElement]],
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for child in _sort_nodes(children_by_group.get(group_id, [])):
        if _is_group_box(child):
            nested = _group_children(child.data.id, children_by_group, meta)
            if nested:
                children.append(_elk_group_from_node(child, nested, meta, direction="DOWN"))
            continue
        children.append(_elk_leaf(child, meta))
    return children


def _elk_root(
    *,
    children: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    direction: str,
    spacing: int,
    node_node: int,
    hierarchy: bool,
) -> dict[str, Any]:
    return {
        "id": "root",
        "layoutOptions": {
            "elk.algorithm": "layered",
            "elk.direction": direction,
            "elk.edgeRouting": "ORTHOGONAL",
            "elk.layered.spacing.nodeNodeBetweenLayers": str(spacing),
            "elk.spacing.nodeNode": str(node_node),
            "elk.hierarchyHandling": "INCLUDE_CHILDREN" if hierarchy else "SEPARATE_CHILDREN",
            "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
            "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
            "elk.layered.mergeEdges": "false",
            "elk.layered.unnecessaryBendpoints": "true",
        },
        "children": children,
        "edges": edges,
    }


def _elk_group(
    node_id: str,
    label: str,
    layer: str,
    children: list[dict[str, Any]],
    meta: dict[str, Any],
    *,
    direction: str,
    group_node: NodeElement | None = None,
) -> dict[str, Any]:
    width = max(260, sum(int(child.get("width", 120)) for child in children) // max(len(children), 1) + 80)
    height = 110 + (len(children) * 6)
    style = _style_for_group(group_node, layer)
    meta[node_id] = {
        "id": node_id,
        "label": label,
        "type": "group",
        "layer": layer,
        "fill": style["fill"],
        "stroke": style["stroke"],
        "text": style["text"],
        "semantic_group": group_node.data.hierarchy_group if group_node else None,
        "ip_group": group_node.data.ip_group if group_node else None,
        "details": _group_details(group_node),
    }
    return {
        "id": node_id,
        "width": width,
        "height": height,
        "labels": [{"text": label}],
        "layoutOptions": {
            "elk.algorithm": "layered",
            "elk.direction": direction,
            "elk.edgeRouting": "ORTHOGONAL",
            "elk.spacing.nodeNode": "32",
            "elk.layered.spacing.nodeNodeBetweenLayers": "42",
            "elk.padding": "[top=44,left=34,bottom=30,right=34]",
        },
        "children": children,
        "edges": [],
    }


def _elk_group_from_node(
    group: NodeElement,
    children: list[dict[str, Any]],
    meta: dict[str, Any],
    *,
    direction: str,
) -> dict[str, Any]:
    return _elk_group(
        group.data.id,
        group.data.label,
        group.data.layer,
        children,
        meta,
        direction=direction,
        group_node=group,
    )


def _style_for_group(group_node: NodeElement | None, layer: str) -> dict[str, str]:
    if group_node is None:
        return {"fill": LAYER_TINT.get(layer, "#F8FAFC"), "stroke": _layer_stroke(layer), "text": "#334155"}
    data = group_node.data
    if data.ip_group:
        return IP_GROUP_STYLE.get(data.ip_group, HIERARCHY_GROUP_STYLE.get(data.hierarchy_group or "", TYPE_STYLE["group"]))
    if data.hierarchy_group:
        return HIERARCHY_GROUP_STYLE.get(data.hierarchy_group, TYPE_STYLE["group"])
    return {"fill": LAYER_TINT.get(layer, "#F8FAFC"), "stroke": _layer_stroke(layer), "text": "#334155"}


def _group_details(group_node: NodeElement | None) -> list[str]:
    if group_node is None:
        return []
    data = group_node.data
    details: list[str] = []
    if data.hierarchy_group:
        details.append(f"Hierarchy: {data.hierarchy_group}")
    if data.ip_group:
        details.append(f"IP block: {data.ip_group}")
    details.extend(data.detail_items)
    return details


def _manual_layer_columns(layer: str, count: int) -> int:
    return 1


def _position_layer_rows(
    groups_by_layer: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]], int, int]:
    """Place Level 0 groups from measured sizes, not fixed coordinates.

    Scenario families have different counts of SW tasks, HW blocks, and buffers.
    Fixed coordinates inevitably overlap for some scenarios, so row placement is
    computed from each group's actual width/height after its children are laid
    out.
    """
    rows = [
        ["app", "framework"],
        ["hal", "kernel"],
        ["external", "hw", "memory"],
    ]
    left = 48
    top = 18
    row_gap = 72
    col_gap = 84
    groups: list[dict[str, Any]] = []
    positions: dict[str, dict[str, float]] = {}
    y = top
    graph_width = 0

    for row in rows:
        present = [groups_by_layer[layer] for layer in row if layer in groups_by_layer]
        if not present:
            continue
        x = left
        row_height = max(int(group.get("height", 0)) for group in present)
        for group in present:
            group["x"] = x
            group["y"] = y
            groups.append(group)
            positions.update(_group_global_positions(group))
            x += int(group.get("width", 0)) + col_gap
        graph_width = max(graph_width, x - col_gap + left)
        y += row_height + row_gap

    graph_height = y + 70
    return groups, positions, max(1500, graph_width), max(900, graph_height)


def _group_global_positions(group: dict[str, Any]) -> dict[str, dict[str, float]]:
    gx = float(group.get("x", 0))
    gy = float(group.get("y", 0))
    positions: dict[str, dict[str, float]] = {}
    for child in group.get("children", []):
        positions[child["id"]] = {
            "x": gx + float(child.get("x", 0)),
            "y": gy + float(child.get("y", 0)),
            "width": float(child.get("width", 0)),
            "height": float(child.get("height", 0)),
        }
    return positions


def _manual_layer_group(
    layer: str,
    nodes: list[NodeElement],
    meta: dict[str, Any],
    *,
    x: int,
    y: int,
    width: int,
    columns: int,
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    children: list[dict[str, Any]] = []
    positions: dict[str, dict[str, float]] = {}
    pad_x = 28
    pad_top = 44
    gap_x = 0
    gap_y = 53
    cell_w = max(118, (width - (pad_x * 2) - (gap_x * (columns - 1))) // columns)
    max_h = 0
    max_w = width
    step_x = min(170, max(104, width // 4))
    stair = [0, step_x, step_x * 2, step_x, 0]
    for idx, node in enumerate(nodes):
        leaf = _elk_leaf(node, meta)
        row = idx // columns
        col = idx % columns
        if layer == "memory":
            leaf["width"] = min(max(int(leaf.get("width", 150)), 220), cell_w)
            leaf["height"] = 64
        else:
            leaf["width"] = min(int(leaf.get("width", 150)), cell_w)
            leaf["height"] = min(int(leaf.get("height", 52)), 48)
        used_w = (cell_w * columns) + (gap_x * (columns - 1))
        start_x = max(pad_x, (width - used_w) // 2)
        leaf["x"] = start_x + col * (cell_w + gap_x) + stair[idx % len(stair)]
        leaf["y"] = pad_top + row * (int(leaf.get("height", 48)) + gap_y)
        children.append(leaf)
        positions[node.data.id] = {
            "x": x + float(leaf["x"]),
            "y": y + float(leaf["y"]),
            "width": float(leaf["width"]),
            "height": float(leaf["height"]),
        }
        max_h = max(max_h, int(leaf["y"]) + int(leaf["height"]) + 26)
        max_w = max(max_w, int(leaf["x"]) + int(leaf["width"]) + pad_x)
    height = max(118, max_h)
    width = max(width, max_w)
    meta[f"layer-{layer}"] = {
        "id": f"layer-{layer}",
        "label": LAYER_LABELS[layer],
        "type": "group",
        "layer": layer,
        "fill": LAYER_TINT.get(layer, "#F8FAFC"),
        "stroke": _layer_stroke(layer),
        "text": "#334155",
        "details": [],
    }
    return (
        {
            "id": f"layer-{layer}",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "labels": [{"text": LAYER_LABELS[layer]}],
            "children": children,
            "edges": [],
        },
        positions,
    )


def _manual_edges(
    edges: list[EdgeElement],
    meta: dict[str, Any],
    positions: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    parallel_counts: dict[tuple[str, str], int] = defaultdict(int)
    flow_lane_counts: dict[str, int] = defaultdict(int)
    lane_offsets = [0, 22, -22, 44, -44, 66, -66]
    for edge in edges:
        data = edge.data
        source = positions.get(data.source)
        target = positions.get(data.target)
        if not source or not target:
            continue
        meta[data.id] = _edge_meta(edge)
        label = _edge_display_label(data, meta[data.id])
        pair = (data.source, data.target)
        parallel_counts[pair] += 1
        flow_key = data.flow_type if data.flow_type in {"M2M", "control", "OTF", "vOTF"} else "other"
        flow_lane_counts[flow_key] += 1
        lane_offset = lane_offsets[(flow_lane_counts[flow_key] - 1) % len(lane_offsets)]
        parallel_offset = (parallel_counts[pair] - 1) * 14
        offset = lane_offset + parallel_offset
        section, label_x, label_y = _manual_edge_section(source, target, data.flow_type, offset)
        out.append(
            {
                "id": data.id,
                "sources": [data.source],
                "targets": [data.target],
                "sections": [section],
                "labels": [{"text": label, "x": label_x, "y": label_y, "width": max(38, min(260, len(label) * 6 + 14)), "height": 18}],
            }
        )
    return out


def _manual_edge_section(
    source: dict[str, float],
    target: dict[str, float],
    flow_type: str,
    offset: float,
) -> tuple[dict[str, Any], float, float]:
    source_side, target_side = _choose_anchor_sides(source, target, flow_type)
    start = _anchor_point(source, source_side)
    end = _anchor_point(target, target_side)
    stub = 34 + min(34, abs(offset) * 0.25)
    start_outer = _move_from_side(start, source_side, stub)
    end_outer = _move_from_side(end, target_side, stub)

    if source_side in {"left", "right"} and target_side in {"left", "right"}:
        mid_x = (start_outer["x"] + end_outer["x"]) / 2 + offset * 0.35
        bends = [
            start_outer,
            {"x": mid_x, "y": start_outer["y"]},
            {"x": mid_x, "y": end_outer["y"]},
            end_outer,
        ]
        label_x = mid_x - 18
        label_y = (start_outer["y"] + end_outer["y"]) / 2 - 18
    elif source_side in {"top", "bottom"} and target_side in {"top", "bottom"}:
        facing_vertical = (source_side, target_side) in {("bottom", "top"), ("top", "bottom")}
        if facing_vertical:
            # Facing top/bottom anchors often have short gaps.  Do not push
            # stubs past each other; route through the gap between the nodes.
            min_y = min(start["y"], end["y"])
            max_y = max(start["y"], end["y"])
            raw_mid = (start["y"] + end["y"]) / 2 + _vertical_lane_bias(flow_type, offset)
            if max_y - min_y > 20:
                mid_y = min(max(raw_mid, min_y + 8), max_y - 8)
            else:
                mid_y = (start["y"] + end["y"]) / 2
            bends = [
                {"x": start["x"], "y": mid_y},
                {"x": end["x"], "y": mid_y},
            ]
        else:
            mid_y = (start_outer["y"] + end_outer["y"]) / 2 + _vertical_lane_bias(flow_type, offset)
            bends = [
                start_outer,
                {"x": start_outer["x"], "y": mid_y},
                {"x": end_outer["x"], "y": mid_y},
                end_outer,
            ]
        label_x = (start["x"] + end["x"]) / 2 - 18
        label_y = mid_y - 18
    else:
        elbow_a = {"x": start_outer["x"], "y": end_outer["y"]}
        elbow_b = {"x": end_outer["x"], "y": end_outer["y"]}
        if source_side in {"top", "bottom"}:
            elbow_a = {"x": start_outer["x"], "y": start_outer["y"] + (end_outer["y"] - start_outer["y"]) * 0.55}
            elbow_b = {"x": end_outer["x"], "y": elbow_a["y"]}
        bends = [start_outer, elbow_a, elbow_b, end_outer]
        label_x = (elbow_a["x"] + elbow_b["x"]) / 2 - 18
        label_y = (elbow_a["y"] + elbow_b["y"]) / 2 - 18

    return (
        {
            "startPoint": start,
            "bendPoints": _dedupe_points(bends, start, end),
            "endPoint": end,
        },
        label_x,
        label_y,
    )


def _choose_anchor_sides(source: dict[str, float], target: dict[str, float], flow_type: str) -> tuple[str, str]:
    scx, scy = _rect_center(source)
    tcx, tcy = _rect_center(target)
    dx = tcx - scx
    dy = tcy - scy
    if flow_type in {"OTF", "vOTF"} and abs(dy) >= max(24, abs(dx) * 0.65):
        return ("bottom", "top") if dy >= 0 else ("top", "bottom")
    if flow_type == "M2M" or abs(dx) >= abs(dy) * 0.72:
        return ("right", "left") if dx >= 0 else ("left", "right")
    return ("bottom", "top") if dy >= 0 else ("top", "bottom")


def _rect_center(rect: dict[str, float]) -> tuple[float, float]:
    return rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2


def _anchor_point(rect: dict[str, float], side: str) -> dict[str, float]:
    cx, cy = _rect_center(rect)
    if side == "left":
        return {"x": rect["x"], "y": cy}
    if side == "right":
        return {"x": rect["x"] + rect["width"], "y": cy}
    if side == "top":
        return {"x": cx, "y": rect["y"]}
    return {"x": cx, "y": rect["y"] + rect["height"]}


def _move_from_side(point: dict[str, float], side: str, distance: float) -> dict[str, float]:
    if side == "left":
        return {"x": point["x"] - distance, "y": point["y"]}
    if side == "right":
        return {"x": point["x"] + distance, "y": point["y"]}
    if side == "top":
        return {"x": point["x"], "y": point["y"] - distance}
    return {"x": point["x"], "y": point["y"] + distance}


def _vertical_lane_bias(flow_type: str, offset: float) -> float:
    if flow_type == "control":
        return -abs(offset) * 0.35
    if flow_type == "M2M":
        return abs(offset) * 0.35
    return offset * 0.2


def _dedupe_points(
    bend_points: list[dict[str, float]],
    start: dict[str, float],
    end: dict[str, float],
) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    last = start
    for point in bend_points:
        if abs(point["x"] - last["x"]) < 0.1 and abs(point["y"] - last["y"]) < 0.1:
            continue
        if abs(point["x"] - end["x"]) < 0.1 and abs(point["y"] - end["y"]) < 0.1:
            continue
        out.append(point)
        last = point
    return out


def _elk_row_group(
    node_id: str,
    children: list[dict[str, Any]],
    meta: dict[str, Any],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Invisible compound row used only to keep selected Level 0 layers horizontal."""
    width = max(360, sum(int(child.get("width", 260)) for child in children) + 84)
    height = max(140, max(int(child.get("height", 120)) for child in children) + 70)
    child_order_edges = _layer_order_edges([child["id"] for child in children], meta, prefix=f"__{node_id}_order")
    meta[node_id] = {
        "id": node_id,
        "label": "",
        "type": "layout_row",
        "layer": "meta",
        "hidden": True,
        "fill": "transparent",
        "stroke": "transparent",
        "text": "transparent",
        "details": [],
    }
    return {
        "id": node_id,
        "width": width,
        "height": height,
        "labels": [],
        "layoutOptions": {
            "elk.algorithm": "layered",
            "elk.direction": "RIGHT",
            "elk.edgeRouting": "ORTHOGONAL",
            "elk.spacing.nodeNode": "34",
            "elk.layered.spacing.nodeNodeBetweenLayers": "48",
            "elk.padding": "[top=14,left=10,bottom=14,right=10]",
        },
        "children": children,
        "edges": edges + child_order_edges,
    }


def _elk_leaf(node: NodeElement, meta: dict[str, Any]) -> dict[str, Any]:
    width, height = _node_size(node)
    meta[node.data.id] = _node_meta(node)
    return {
        "id": node.data.id,
        "width": width,
        "height": height,
        "labels": [{"text": node.data.label}],
    }


def _elk_edges(edges: list[EdgeElement], meta: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for edge in edges:
        data = edge.data
        meta[data.id] = _edge_meta(edge)
        label = _edge_display_label(data, meta[data.id])
        out.append(
            {
                "id": data.id,
                "sources": [data.source],
                "targets": [data.target],
                "labels": [{"text": label, "width": max(38, min(300, len(label) * 6 + 14)), "height": 18}],
            }
        )
    return out


def _edge_display_label(data: Any, edge_meta: dict[str, Any]) -> str:
    """On-diagram edge text: the enriched transfer descriptor when available,
    otherwise the backend label, with control edges shown as SW."""

    descriptor = _edge_descriptor_label(data)
    if descriptor:
        return descriptor
    if data.label:
        return str(data.label)
    if data.flow_type == "control":
        return "SW"
    return str(edge_meta.get("label") or data.flow_type)


def _layer_order_edges(layer_group_ids: list[str], meta: dict[str, Any], *, prefix: str = "__layer_order") -> list[dict[str, Any]]:
    """Invisible edges keep Level 0 groups in App->...->Memory order."""
    edges: list[dict[str, Any]] = []
    for idx, (source, target) in enumerate(zip(layer_group_ids, layer_group_ids[1:])):
        edge_id = f"{prefix}_{idx}"
        meta[edge_id] = {"id": edge_id, "type": "edge", "hidden": True}
        edges.append({"id": edge_id, "sources": [source], "targets": [target]})
    return edges


def _functional_nodes(nodes: list[NodeElement]) -> list[NodeElement]:
    return [node for node in nodes if node.data.type not in {"lane_bg", "lane_label", "stage_header"}]


def _sort_nodes(nodes: list[NodeElement]) -> list[NodeElement]:
    return sorted(
        nodes,
        key=lambda node: (
            node.data.view_hints.order if node.data.view_hints else 0,
            float(node.position.get("y", 0)),
            float(node.position.get("x", 0)),
            node.data.id,
        ),
    )


def _is_group_box(node: NodeElement) -> bool:
    return node.data.layer == "meta" and node.data.type == "submodule" and node.data.id.startswith(("grp-", "l2"))


def _inside_group(group: NodeElement, node: NodeElement) -> bool:
    hints = group.data.view_hints
    if hints is None or hints.width is None or hints.height is None:
        return False
    gx = float(group.position.get("x", 0))
    gy = float(group.position.get("y", 0))
    x = float(node.position.get("x", 0))
    y = float(node.position.get("y", 0))
    return (gx - hints.width / 2) <= x <= (gx + hints.width / 2) and (gy - hints.height / 2) <= y <= (gy + hints.height / 2)


def _node_size(node: NodeElement) -> tuple[int, int]:
    hints = node.data.view_hints
    default = DEFAULT_SIZE.get(node.data.type, (150, 54))
    return int(hints.width if hints and hints.width else default[0]), int(hints.height if hints and hints.height else default[1])


def _node_meta(node: NodeElement) -> dict[str, Any]:
    data = node.data
    style = _style_for_node(node)
    details: list[str] = []
    subtitle = ""
    details.extend(data.detail_items)
    if data.ip_ref:
        details.append(f"IP: {data.ip_ref}")
    if data.hierarchy_group:
        details.append(f"Hierarchy: {data.hierarchy_group}")
    if data.ip_group:
        details.append(f"IP block: {data.ip_group}")
    if data.role_hw_name:
        details.append(f"Role HW: {data.role_hw_name}")
    if data.dvfs_group:
        details.append(f"DVFS group: {data.dvfs_group}")
    if data.module_ref:
        details.append(f"Module: {data.module_ref}")
    if data.module_kind:
        details.append(f"Module kind: {data.module_kind}")
        if not subtitle:
            subtitle = data.module_kind.upper()
    if data.module_direction:
        details.append(f"Direction: {data.module_direction}")
        subtitle = f"{data.module_direction} / {subtitle}" if subtitle else data.module_direction
    if data.module_status:
        details.append(f"Status: {data.module_status}")
    if data.port_ref:
        details.append(f"Port: {data.port_ref}")
    if data.capability_badges:
        details.append("Capabilities: " + ", ".join(data.capability_badges[:6]))
    if data.summary_badges:
        details.append("Summary: " + ", ".join(data.summary_badges[:6]))
    if data.active_operations:
        op = data.active_operations
        ops = []
        op_labels = []
        if op.crop:
            ops.append("crop")
            op_labels.append("Crop")
        if op.scale:
            ops.append(f"scale {op.scale_from or ''}->{op.scale_to or ''}".strip())
            op_labels.append("Scale")
        if op.rotate is not None:
            ops.append(f"rotate {op.rotate}")
            op_labels.append("Rotate")
        if op.colorspace_convert:
            ops.append(f"csc {op.colorspace_convert}")
        if ops:
            details.append("Ops: " + ", ".join(ops))
            if not subtitle:
                # Legacy views showed the scale as an inline size transition
                # (4000x2252→1920x1080) rather than the word "Scale".
                if op.scale and op.scale_from and op.scale_to:
                    subtitle = f"{op.scale_from}→{op.scale_to}"
                else:
                    subtitle = " / ".join(op_labels)
    if data.memory:
        mem = data.memory
        size_label = _format_size_bytes(mem.size_bytes)
        mem_bits = [
            mem.format,
            f"{mem.width}x{mem.height}" if mem.width and mem.height else None,
            f"{mem.fps}fps" if mem.fps else None,
            f"{mem.bitdepth}b" if mem.bitdepth else None,
            mem.compression,
            size_label,
        ]
        subtitle = " / ".join(str(bit) for bit in mem_bits if bit)
        details.append("Memory: " + subtitle)
    if data.placement and data.placement.llc_allocated:
        placement = data.placement
        llc = _llc_text(placement)
        details.append(f"LLC: {llc}")
        if data.type == "buffer":
            subtitle = f"{subtitle} / {llc}" if subtitle else llc
    if data.sim_overlay:
        overlay = data.sim_overlay
        sim_bits = [
            _format_number(overlay.power_mw, "mW"),
            _format_number(overlay.set_clock_mhz, "MHz"),
            _format_number(overlay.set_voltage_mv, "mV"),
            _format_number(overlay.hw_time_ms, "ms"),
        ]
        details.append("Simulation: " + " / ".join(bit for bit in sim_bits if bit))
        if not subtitle:
            subtitle = " / ".join(bit for bit in sim_bits[:2] if bit)
    if data.type == "buffer" and not subtitle:
        subtitle = _fallback_buffer_subtitle(data.detail_items, data.ip_ref)
    if data.type == "sw" and not subtitle:
        subtitle = "<sw>"
    warning = data.warning or bool(data.sim_overlay and not data.sim_overlay.feasible)
    op_badges: list[str] = []
    if data.active_operations:
        if data.active_operations.scale:
            op_badges.append("S")
        if data.active_operations.crop:
            op_badges.append("C")
        if data.active_operations.rotate is not None:
            op_badges.append("R")
    disabled = str(data.module_status or "").lower() in {"disabled", "off", "inactive", "unused"}
    return {
        "id": data.id,
        "label": data.label,
        "type": data.type,
        "layer": data.layer,
        "fill": style["fill"],
        "stroke": style["stroke"],
        "text": style["text"],
        "badges": data.summary_badges[:4],
        "op_badges": op_badges,
        "disabled": disabled,
        "subtitle": subtitle,
        "details": details,
        "semantic_group": data.hierarchy_group,
        "ip_group": data.ip_group,
        "dvfs_group": data.dvfs_group,
        "role_hw_name": data.role_hw_name,
        "module_ref": data.module_ref,
        "module_kind": data.module_kind,
        "module_direction": data.module_direction,
        "module_status": data.module_status,
        "port_ref": data.port_ref,
        "warning": warning,
        "severity": data.severity,
    }


def _format_size_bytes(size_bytes: int | None) -> str | None:
    if not size_bytes:
        return None
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MiB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f}KiB"
    return f"{size_bytes}B"


def _format_number(value: float | None, suffix: str) -> str | None:
    if value is None:
        return None
    return f"{value:g}{suffix}"


def _llc_text(placement: Any) -> str:
    text = f"LLC {placement.llc_policy or 'allocated'}"
    if placement.llc_allocation_mb:
        text = f"{text} {placement.llc_allocation_mb:g}MB"
    return text


def _fallback_buffer_subtitle(detail_items: list[str], ip_ref: str | None) -> str:
    for prefix in ("Buffer:", "Members:", "Placement:"):
        for item in detail_items:
            if item.startswith(prefix):
                return item.split(":", 1)[1].strip()
    return ip_ref or "memory resource"


def _edge_meta(edge: EdgeElement) -> dict[str, Any]:
    data = edge.data
    details = [f"{data.source} -> {data.target}", f"Type: {data.flow_type}"]
    details.extend(data.detail_items)
    if data.latency_class:
        details.append(f"Latency: {data.latency_class}")
    for pair in getattr(data, "port_pairs", None) or []:
        details.append(f"Port: {pair.src} → {pair.dst}")
    if data.buffer_ref:
        details.append(f"Buffer: {data.buffer_ref}")
    if data.memory:
        mem = data.memory
        bits = [mem.format, f"{mem.width}x{mem.height}" if mem.width and mem.height else None, mem.compression]
        details.append("Memory: " + " / ".join(str(bit) for bit in bits if bit))
    if data.placement and data.placement.llc_allocated:
        details.append(f"LLC: {data.placement.llc_policy}")
    if data.sim_overlay:
        overlay = data.sim_overlay
        sim_bits = [
            _format_number(overlay.bw_mbs, "MB/s"),
            _format_number(overlay.bw_power_mw, "mW"),
            _format_number(overlay.bw_mbs_worst, "MB/s worst"),
        ]
        details.append("Simulation: " + " / ".join(bit for bit in sim_bits if bit))
    edge_role = _edge_role(edge)
    return {
        "id": data.id,
        "label": _edge_descriptor_label(data) or data.label or _sim_edge_label(data) or data.flow_type,
        "type": "edge",
        "flow_type": data.flow_type,
        "edge_role": edge_role,
        "stroke": _edge_stroke(data.flow_type, edge_role),
        "dash": data.flow_type in {"control", "risk", "M2M"},
        "details": details,
    }


def _edge_descriptor_label(data: Any) -> str | None:
    """Legacy-style transfer descriptor: ``BUF | WxH | FMT | 10b | COMP``.

    The legacy task-topology view carried the full memory descriptor on every
    M2M edge; rebuild it whenever the projection provides edge memory data so
    "which buffer, what size, what format" reads directly off the diagram.
    """

    pairs = getattr(data, "port_pairs", None) or []
    mem = data.memory
    if not mem and not pairs:
        return None
    bits = []
    if mem:
        bits = [
            f"{mem.width}x{mem.height}" if mem.width and mem.height else None,
            mem.format,
            f"{mem.bitdepth}b" if mem.bitdepth else None,
            mem.compression,
        ]
    descriptor = " | ".join(str(bit) for bit in bits if bit)
    # Port pairs are the strongest identity (which WDMA feeds which RDMA);
    # when present they replace the buffer name, which stays in the tooltip.
    if pairs:
        head = f"{pairs[0].src}→{pairs[0].dst}"
        if len(pairs) > 1:
            head = f"{head} +{len(pairs) - 1}"
    elif data.buffer_ref:
        head = str(data.buffer_ref)
    elif descriptor:
        head = str(data.flow_type)
    else:
        return None
    label = f"{head} | {descriptor}" if descriptor else head
    if data.sim_overlay and data.sim_overlay.bw_mbs is not None:
        label = f"{label} | {data.sim_overlay.bw_mbs:g}MB/s"
    return label


def _sim_edge_label(data: Any) -> str | None:
    if not data.sim_overlay or data.sim_overlay.bw_mbs is None:
        return None
    return f"{data.flow_type} {data.sim_overlay.bw_mbs:g} MB/s"


def _edge_role(edge: EdgeElement) -> str:
    data = edge.data
    text = " ".join(
        [
            data.id,
            data.label or "",
            data.source,
            data.target,
            data.buffer_ref or "",
            " ".join(data.detail_items),
        ]
    ).lower().replace("_", " ")
    if "sensor in" in text or "sensor input" in text:
        return "sensor_in"
    if "display out" in text or "display output" in text:
        return "display_out"
    return data.flow_type.lower()


def _edge_stroke(flow_type: str, edge_role: str) -> str:
    if edge_role == "sensor_in":
        return "#16A34A"
    if edge_role == "display_out":
        return "#0EA5E9"
    return EDGE_COLOR.get(flow_type, "#64748B")


def _style_for_node(node: NodeElement) -> dict[str, str]:
    data = node.data
    if data.type == "sw" and data.layer in LAYER_GRADIENT:
        gradient = LAYER_GRADIENT[data.layer]
        return {"fill": gradient["g2"], "stroke": gradient["border"], "text": gradient["text"]}
    if data.type == "buffer":
        if data.placement and data.placement.llc_allocated:
            return LLC_BUFFER_STYLE
        return TYPE_STYLE["buffer"]
    if data.module_kind:
        if data.module_kind == "functional":
            return IP_GROUP_STYLE.get(data.ip_group or "", TYPE_STYLE["submodule"])
        return MODULE_KIND_STYLE.get(data.module_kind, MODULE_KIND_STYLE["module"])
    if data.layer == "external":
        return TYPE_STYLE["external"]
    subsystem = _subsystem_from_badges(data.summary_badges)
    if data.type == "ip" and subsystem:
        return SUBSYSTEM_STYLE[subsystem]
    label = data.label.lower()
    role_text = " ".join(data.detail_items).lower()
    key_text = f"{data.id} {label} {data.ip_ref or ''} {role_text}"
    if any(token in key_text for token in ("isp", "camera pipeline", "camera frontend", "csis", "mcsc", "gdc")):
        return TYPE_STYLE["isp"]
    if any(token in key_text for token in ("mfc", "codec", "apv", "jpeg")):
        return TYPE_STYLE["codec"]
    if any(token in key_text for token in ("dpu", "display")):
        return TYPE_STYLE["display"]
    if any(token in key_text for token in ("gpu", "npu")):
        return TYPE_STYLE["accelerator"]
    return TYPE_STYLE.get(data.type, TYPE_STYLE["sw"])


def _subsystem_from_badges(badges: list[str]) -> str | None:
    for badge in badges:
        lowered = str(badge).lower()
        if lowered in SUBSYSTEM_STYLE:
            return lowered
    return None


def _layer_stroke(layer: str) -> str:
    if layer in LAYER_GRADIENT:
        return str(LAYER_GRADIENT[layer]["border"])
    return "#CBD5E1"


def _view_meta(view: ViewResponse) -> dict[str, Any]:
    return {
        "level": view.level,
        "mode": view.mode,
        "scenario": view.scenario_id,
        "variant": view.variant_id,
        "summary": view.summary.model_dump(),
        "layout": view.metadata.get("layout"),
    }


def _html(graph: dict[str, Any], meta: dict[str, Any], title: str, height: int, *, inline_runtime: bool = True) -> str:
    graph_json = _safe_script_json(graph)
    meta_json = _safe_script_json(meta)
    safe_title = html.escape(title)
    elk_runtime_script = _elk_runtime_script() if inline_runtime else f'<script src="{STATIC_ELK_URL}"></script>'
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
{elk_runtime_script}
<style>
  html, body {{ margin:0; padding:0; background:#FAF9F7; font-family: Inter, Segoe UI, Arial, sans-serif; }}
  .elk-shell {{ height:{height}px; border:1px solid #E5E7EB; border-radius:12px; background:#FFFFFF; overflow:hidden; position:relative; }}
  .elk-toolbar {{ position:absolute; top:10px; left:12px; right:12px; z-index:4; display:flex; align-items:center; gap:8px; pointer-events:none; }}
  .elk-title {{ font-size:13px; font-weight:800; color:#111827; background:rgba(255,255,255,.92); border:1px solid #E5E7EB; border-radius:8px; padding:6px 9px; box-shadow:0 2px 8px rgba(15,23,42,.06); }}
  .elk-controls {{ margin-left:auto; display:flex; gap:4px; pointer-events:auto; }}
  .elk-controls button {{ border:1px solid #CBD5E1; background:#FFFFFF; color:#334155; border-radius:7px; padding:5px 8px; font-weight:700; cursor:pointer; }}
  .elk-controls button:hover {{ background:#F8FAFC; }}
  .elk-legend {{ position:absolute; left:12px; bottom:10px; z-index:4; display:flex; align-items:center; gap:14px; font-size:11px; color:#64748B; background:rgba(255,255,255,.9); border:1px solid #E5E7EB; border-radius:8px; padding:6px 9px; }}
  .tip {{ position:absolute; z-index:5; min-width:220px; max-width:360px; background:#0F172A; color:#E5E7EB; border-radius:9px; padding:9px 10px; font-size:11px; line-height:1.45; pointer-events:none; opacity:0; transform:translate(8px,8px); box-shadow:0 12px 28px rgba(15,23,42,.22); }}
  .tip b {{ color:#FFFFFF; font-size:12px; }}
  .tip .muted {{ color:#CBD5E1; }}
  .tip .tip-close {{ position:absolute; top:4px; right:8px; cursor:pointer; font-size:15px; color:#94A3B8; line-height:1; }}
  .tip .tip-close:hover {{ color:#FFFFFF; }}
  .error {{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#B91C1C; font-size:13px; padding:24px; text-align:center; }}
  svg {{ width:100%; height:100%; cursor:grab; }}
  svg.dragging {{ cursor:grabbing; }}
  .node {{ cursor:default; }}
  .edge {{ pointer-events:stroke; }}
  .edge-label {{ pointer-events:none; }}
</style>
</head>
<body>
<div class="elk-shell" id="shell">
  <div class="elk-toolbar">
    <div class="elk-title">{safe_title}</div>
    <div class="elk-controls">
      <button id="zoomOut">-</button>
      <button id="fit">Fit</button>
      <button id="reset">Reset</button>
      <button id="zoomIn">+</button>
      <button id="exportSvg" title="Download the full diagram as an SVG file">SVG</button>
    </div>
  </div>
  <svg id="svg" tabindex="0"><defs>
    <marker id="arrow-blue" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#2563EB"/></marker>
    <marker id="arrow-teal" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#0D9488"/></marker>
    <marker id="arrow-orange" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#F97316"/></marker>
    <marker id="arrow-amber" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#CA8A04"/></marker>
    <marker id="arrow-gray" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#9B8EC4"/></marker>
    <marker id="arrow-red" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#EF4444"/></marker>
    <marker id="arrow-green" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#16A34A"/></marker>
    <marker id="arrow-sky" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#0EA5E9"/></marker>
  </defs><g id="main"></g></svg>
  <div class="elk-legend">
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#2563EB" stroke-width="2"/><path d="M31 1 L37 4 L31 7" fill="#2563EB"/></svg> OTF</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#0D9488" stroke-width="2"/><path d="M31 1 L37 4 L31 7" fill="#0D9488"/></svg> vOTF</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#F97316" stroke-width="2" stroke-dasharray="7 4"/><path d="M31 1 L37 4 L31 7" fill="#F97316"/></svg> M2M</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#CA8A04" stroke-width="2" stroke-dasharray="5 4"/><path d="M31 1 L37 4 L31 7" fill="#CA8A04"/></svg> SW</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#16A34A" stroke-width="2"/><path d="M31 1 L37 4 L31 7" fill="#16A34A"/></svg> Sensor In</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#0EA5E9" stroke-width="2"/><path d="M31 1 L37 4 L31 7" fill="#0EA5E9"/></svg> Display Out</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#EF4444" stroke-width="2" stroke-dasharray="4 4"/><path d="M31 1 L37 4 L31 7" fill="#EF4444"/></svg> Risk</span>
  </div>
  <div class="tip" id="tip"></div>
</div>
<script>
const G = {graph_json};
const M = {meta_json};
const shell = document.getElementById('shell');
const svg = document.getElementById('svg');
const main = document.getElementById('main');
const tip = document.getElementById('tip');
const VIEW = M.__view__ || {{}};
let scale = 1, tx = 0, ty = 0;
let layoutGraph = null;
const PAD = 36;
const NP = {{}};

function markerFor(color) {{
  if (color === '#0D9488') return 'url(#arrow-teal)';
  if (color === '#F97316') return 'url(#arrow-orange)';
  if (color === '#CA8A04') return 'url(#arrow-amber)';
  if (color === '#9B8EC4') return 'url(#arrow-gray)';
  if (color === '#EF4444') return 'url(#arrow-red)';
  if (color === '#16A34A') return 'url(#arrow-green)';
  if (color === '#0EA5E9') return 'url(#arrow-sky)';
  return 'url(#arrow-blue)';
}}

function esc(s) {{
  return String(s ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}

function svgEl(tag, attrs={{}}) {{
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([k,v]) => el.setAttribute(k, v));
  return el;
}}

function setTransform() {{
  main.setAttribute('transform', `translate(${{tx + PAD}},${{ty + PAD}}) scale(${{scale}})`);
}}

function fitGraph() {{
  if (!layoutGraph) return;
  const w = shell.clientWidth - PAD * 2;
  const h = shell.clientHeight - PAD * 2;
  const gw = Math.max(1, layoutGraph.width || 1);
  const gh = Math.max(1, layoutGraph.height || 1);
  scale = Math.max(0.28, Math.min(1.35, Math.min(w / gw, h / gh) * 0.94));
  tx = Math.max(0, (w - gw * scale) / 2);
  ty = 36;
  setTransform();
}}

function resetGraph() {{
  scale = 1;
  tx = 0;
  ty = 36;
  setTransform();
}}

function readableLevel2View() {{
  if (!layoutGraph) return;
  const w = shell.clientWidth - PAD * 2;
  const gw = Math.max(1, layoutGraph.width || 1);
  scale = Math.max(0.72, Math.min(1.05, w / gw));
  tx = Math.max(0, (w - gw * scale) / 2);
  ty = 36;
  setTransform();
}}

function initialGraphView() {{
  if (VIEW.layout === 'level2-module-detail') {{
    readableLevel2View();
    return;
  }}
  // Tall, narrow graphs (single-chain topologies) become unreadably small
  // under fit-both; start at width-fit with a readable scale floor and let
  // the user pan vertically. The Fit button still does a full fit.
  const gw = Math.max(1, layoutGraph.width || 1);
  const gh = Math.max(1, layoutGraph.height || 1);
  const w = shell.clientWidth - PAD * 2;
  const h = shell.clientHeight - PAD * 2;
  if (gh > h * 1.15 && gh > gw) {{
    scale = Math.max(0.62, Math.min(1.15, (w / gw) * 0.94));
    tx = Math.max(0, (w - gw * scale) / 2);
    ty = 16;
    setTransform();
    return;
  }}
  fitGraph();
}}

function zoomBy(factor) {{
  scale = Math.max(0.35, Math.min(1.8, scale * factor));
  setTransform();
}}

let tipPinned = false;

function tipHtml(id, pinned) {{
  const m = M[id] || {{}};
  const details = (m.details || []).map(d => `<div class="muted">${{esc(d)}}</div>`).join('');
  const badges = (m.badges || []).map(b => `<span class="muted">${{esc(b)}}</span>`).join(' ');
  const close = pinned ? '<span class="tip-close" id="tipClose">&times;</span>' : '';
  return `${{close}}<b>${{esc(m.label || id)}}</b><div class="muted">${{esc(m.layer || m.flow_type || m.type || '')}}</div>${{details}}${{badges ? '<div>'+badges+'</div>' : ''}}`;
}}

function placeTip(evt) {{
  const rect = shell.getBoundingClientRect();
  let left = evt.clientX - rect.left + 10;
  let top = evt.clientY - rect.top + 10;
  left = Math.min(left, rect.width - tip.offsetWidth - 12);
  top = Math.min(top, rect.height - tip.offsetHeight - 12);
  tip.style.left = `${{Math.max(4, left)}}px`;
  tip.style.top = `${{Math.max(4, top)}}px`;
}}

function showTip(evt, id) {{
  if (tipPinned) return;
  tip.innerHTML = tipHtml(id, false);
  tip.style.opacity = 1;
  placeTip(evt);
}}

// Click pins the tooltip so port/detail rows can be read and copied; a
// second click elsewhere, the close button, or Escape releases it.
function broadcastSelection(id) {{
  const m = M[id] || {{}};
  const selectSeq = Date.now();
  try {{
    // Same-origin top window; the graph selection bridge component forwards
    // this into Streamlit so the Graph Inspector follows diagram clicks.
    window.parent.postMessage({{
      type: 'sdb-graph-select',
      id: id,
      kind: m.type === 'edge' ? 'edge' : 'node',
      label: m.label || id,
      seq: selectSeq
    }}, '*');
  }} catch (err) {{}}
}}

function pinTip(evt, id) {{
  if (dragDist > 3) return;
  evt.stopPropagation();
  broadcastSelection(id);
  tipPinned = true;
  tip.innerHTML = tipHtml(id, true);
  tip.style.opacity = 1;
  tip.style.pointerEvents = 'auto';
  placeTip(evt);
  const closeBtn = document.getElementById('tipClose');
  if (closeBtn) closeBtn.onclick = unpinTip;
}}

function unpinTip() {{
  tipPinned = false;
  tip.style.pointerEvents = 'none';
  tip.style.opacity = 0;
}}

function hideTip() {{
  if (tipPinned) return;
  tip.style.opacity = 0;
}}

function textLines(label, maxChars) {{
  return String(label || '').split('\\n').flatMap(line => {{
    if (line.length <= maxChars) return [line];
    const out = [];
    let cur = '';
    line.split(/\\s+/).forEach(word => {{
      if ((cur + ' ' + word).trim().length > maxChars) {{
        if (cur) out.push(cur);
        cur = word;
      }} else {{
        cur = (cur + ' ' + word).trim();
      }}
    }});
    if (cur) out.push(cur);
    return out;
  }}).slice(0, 4);
}}

function drawLabel(g, label, x, y, w, color, weight='700', size=11) {{
  const lines = textLines(label, Math.max(10, Math.floor(w / 7)));
  const text = svgEl('text', {{x: x + w / 2, y: y + 18 - ((lines.length - 1) * 6), 'text-anchor':'middle', 'font-size':size, 'font-weight':weight, fill:color}});
  lines.forEach((line, i) => {{
    const tspan = svgEl('tspan', {{x: x + w / 2, dy: i === 0 ? 0 : 13}});
    tspan.textContent = line;
    text.appendChild(tspan);
  }});
  g.appendChild(text);
}}

function drawBackgrounds(g, graph, ox=0, oy=0) {{
  (graph.children || []).forEach(node => {{
    const x = (node.x || 0) + ox;
    const y = (node.y || 0) + oy;
    const m = M[node.id] || {{}};
    const isGroup = !!(node.children && node.children.length);
    if (isGroup) {{
      if (m.hidden) {{
        drawBackgrounds(g, node, x, y);
        return;
      }}
      const ng = svgEl('g', {{class:'node group-bg'}});
      ng.appendChild(svgEl('rect', {{
        x, y, width: node.width || 200, height: node.height || 100, rx: 9, ry: 9,
        fill: m.fill || '#F8FAFC', stroke: m.stroke || '#CBD5E1', 'stroke-width': 1.25,
        opacity: 0.62
      }}));
      const title = svgEl('text', {{x: x + 14, y: y + 22, 'font-size': 12, 'font-weight': 800, fill: m.text || '#334155'}});
      title.textContent = m.label || node.id;
      ng.appendChild(title);
      g.appendChild(ng);
      drawBackgrounds(g, node, x, y);
    }}
  }});
}}

function drawLeaves(g, graph, ox=0, oy=0) {{
  (graph.children || []).forEach(node => {{
    const x = (node.x || 0) + ox;
    const y = (node.y || 0) + oy;
    const m = M[node.id] || {{}};
    const isGroup = !!(node.children && node.children.length);
    if (isGroup) {{
      drawLeaves(g, node, x, y);
      return;
    }}
    const ng = svgEl('g', {{class:'node'}});
    const w = node.width || 140;
    const h = node.height || 54;
    const isDisabled = !!m.disabled;
    if (m.type === 'buffer' || m.layer === 'memory') {{
      ng.appendChild(svgEl('rect', {{
        x, y, width:w, height:h, rx:18, ry:18,
        fill:m.fill || '#ECFEFF', stroke:m.stroke || '#0F766E',
        'stroke-width':m.warning ? 2.4 : 1.9,
        filter:'drop-shadow(0 2px 4px rgba(15,23,42,.08))'
      }}));
      ng.appendChild(svgEl('path', {{
        d:`M ${{x + 14}} ${{y + 10}} H ${{x + w - 14}}`,
        fill:'none', stroke:m.stroke || '#0F766E', 'stroke-width':1.2, opacity:0.55
      }}));
      ng.appendChild(svgEl('path', {{
        d:`M ${{x + 14}} ${{y + h - 10}} H ${{x + w - 14}}`,
        fill:'none', stroke:m.stroke || '#0F766E', 'stroke-width':1.2, opacity:0.35
      }}));
    }} else {{
      const rectAttrs = {{
        x, y, width:w, height:h, rx:8, ry:8,
        fill:isDisabled ? '#EDEDED' : (m.fill || '#FFFFFF'),
        stroke:isDisabled ? '#B0B0B0' : (m.stroke || '#64748B'),
        'stroke-width':m.warning ? 2.4 : 1.8,
        filter:'drop-shadow(0 2px 4px rgba(15,23,42,.08))'
      }};
      if (isDisabled) rectAttrs['stroke-dasharray'] = '4 2';
      ng.appendChild(svgEl('rect', rectAttrs));
      if (isDisabled) ng.setAttribute('opacity', '0.75');
    }}
    const hasSubtitle = !!m.subtitle;
    drawLabel(ng, m.label || node.id, x, y + (hasSubtitle ? 6 : Math.max(0, (h - 42) / 2)), w, m.text || '#111827');
    if (hasSubtitle) {{
      // Wrap long memory descriptors onto a second line (split on " / ")
      // instead of truncating away the format/compression tail.
      const full = String(m.subtitle || '');
      const maxSubtitle = Math.max(34, Math.floor(w / 5.2));
      let subLines = [full];
      if (full.length > maxSubtitle && full.includes(' / ')) {{
        const parts = full.split(' / ');
        let first = parts.shift();
        while (parts.length && (first + ' / ' + parts[0]).length <= maxSubtitle) {{
          first = first + ' / ' + parts.shift();
        }}
        subLines = parts.length ? [first, parts.join(' / ')] : [first];
      }}
      subLines = subLines.map(line => line.length > maxSubtitle ? line.slice(0, maxSubtitle - 3) + '...' : line).slice(0, 2);
      const baseY = y + h - (subLines.length > 1 ? 22 : 13);
      const subtitle = svgEl('text', {{
        x: x + w / 2,
        y: baseY,
        'text-anchor':'middle',
        'font-size':8.5,
        'font-weight':700,
        fill:'#64748B'
      }});
      subLines.forEach((line, i) => {{
        const tspan = svgEl('tspan', {{x: x + w / 2, dy: i === 0 ? 0 : 10}});
        tspan.textContent = line;
        subtitle.appendChild(tspan);
      }});
      ng.appendChild(subtitle);
    }}
    if (m.warning) {{
      ng.appendChild(svgEl('circle', {{cx: x + (node.width || 140) - 13, cy: y + 13, r: 6, fill:'#F97316'}}));
    }}
    drawOpBadges(ng, m, x, y, w);
    ng.addEventListener('mousemove', evt => showTip(evt, node.id));
    ng.addEventListener('mouseleave', hideTip);
    ng.addEventListener('click', evt => pinTip(evt, node.id));
    ng.style.cursor = 'pointer';
    g.appendChild(ng);
  }});
}}

// Legacy-style operation badges: small circles in the top-right corner
// (S=scale orange, C=crop blue, R=rotate teal). Shifted left when the
// warning dot occupies the corner.
function drawOpBadges(ng, m, x, y, w) {{
  const badges = m.op_badges || [];
  if (!badges.length) return;
  const colors = {{S:'#E65100', C:'#1565C0', R:'#0D9488'}};
  let bx = x + w - (m.warning ? 28 : 10);
  const by = y + 9;
  badges.slice().reverse().forEach(b => {{
    ng.appendChild(svgEl('circle', {{cx:bx, cy:by, r:6.5, fill:colors[b] || '#666', 'fill-opacity':'0.92', stroke:'#FFFFFF', 'stroke-width':1}}));
    const t = svgEl('text', {{x:bx, y:by + 3, 'text-anchor':'middle', 'font-size':8, 'font-weight':700, fill:'#FFFFFF'}});
    t.textContent = b;
    ng.appendChild(t);
    bx -= 15;
  }});
}}

function drawGraphEdges(g, graph, ox=0, oy=0) {{
  drawEdges(g, graph.edges || [], graph.id);
  (graph.children || []).forEach(node => {{
    if (node.children && node.children.length) {{
      drawGraphEdges(g, node, (node.x || 0) + ox, (node.y || 0) + oy);
    }}
  }});
}}

function collectPositions(node, ox=0, oy=0) {{
  const x = (node.x || 0) + ox;
  const y = (node.y || 0) + oy;
  NP[node.id] = {{x, y}};
  (node.children || []).forEach(child => collectPositions(child, x, y));
}}

function drawNode(g, node, ox=0, oy=0) {{
  const x = (node.x || 0) + ox;
  const y = (node.y || 0) + oy;
  const m = M[node.id] || {{}};
  const isGroup = !!(node.children && node.children.length);
  const ng = svgEl('g', {{class:'node'}});
  g.appendChild(ng);

  if (isGroup) {{
    ng.appendChild(svgEl('rect', {{
      x, y, width: node.width || 200, height: node.height || 100, rx: 9, ry: 9,
      fill: m.fill || '#F8FAFC', stroke: m.stroke || '#CBD5E1', 'stroke-width': 1.4,
      'stroke-dasharray': m.layer === 'meta' ? '0' : '0', opacity: 0.92
    }}));
    const title = svgEl('text', {{x: x + 14, y: y + 22, 'font-size': 12, 'font-weight': 800, fill: m.text || '#334155'}});
    title.textContent = m.label || node.id;
    ng.appendChild(title);
  }} else {{
    const isDisabled = !!m.disabled;
    const rectAttrs = {{
      x, y, width: node.width || 140, height: node.height || 54, rx: 8, ry: 8,
      fill: isDisabled ? '#EDEDED' : (m.fill || '#FFFFFF'),
      stroke: isDisabled ? '#B0B0B0' : (m.stroke || '#64748B'),
      'stroke-width': m.warning ? 2.4 : 1.8,
      filter: 'drop-shadow(0 2px 4px rgba(15,23,42,.08))'
    }};
    if (isDisabled) rectAttrs['stroke-dasharray'] = '4 2';
    ng.appendChild(svgEl('rect', rectAttrs));
    if (isDisabled) ng.setAttribute('opacity', '0.75');
    drawLabel(ng, m.label || node.id, x, y + Math.max(0, ((node.height || 54) - 42) / 2), node.width || 140, m.text || '#111827');
    if (m.warning) {{
      ng.appendChild(svgEl('circle', {{cx: x + (node.width || 140) - 13, cy: y + 13, r: 6, fill:'#F97316'}}));
    }}
    drawOpBadges(ng, m, x, y, node.width || 140);
    ng.addEventListener('mousemove', evt => showTip(evt, node.id));
    ng.addEventListener('mouseleave', hideTip);
    ng.addEventListener('click', evt => pinTip(evt, node.id));
    ng.style.cursor = 'pointer';
  }}

  (node.children || []).forEach(child => drawNode(g, child, x, y));
  drawEdges(g, node.edges || [], x, y);
}}

function pathFromSection(section, ox, oy) {{
  const pts = [section.startPoint].concat(section.bendPoints || [], [section.endPoint]).filter(Boolean);
  if (!pts.length) return '';
  return 'M ' + (pts[0].x + ox) + ' ' + (pts[0].y + oy) + pts.slice(1).map(p => ' L ' + (p.x + ox) + ' ' + (p.y + oy)).join('');
}}

function drawEdges(g, edges, defaultContainer='root') {{
  (edges || []).forEach(edge => {{
    const m = M[edge.id] || {{}};
    if (m.hidden) return;
    const color = m.stroke || '#64748B';
    const cp = NP[edge.container || defaultContainer] || {{x:0, y:0}};
    const ox = cp.x;
    const oy = cp.y;
    // Legacy stroke-weight hierarchy: streaming OTF paths render heaviest,
    // memory hops medium, control hand-offs lightest.
    const flowWidth = (m.flow_type === 'OTF' || m.flow_type === 'vOTF') ? 2.4
      : m.flow_type === 'M2M' ? 2.0
      : m.flow_type === 'risk' ? 1.8
      : 1.6;
    (edge.sections || []).forEach(section => {{
      const p = svgEl('path', {{
        class:'edge', d: pathFromSection(section, ox, oy), fill:'none', stroke:color,
        'stroke-width': flowWidth,
        'stroke-linecap':'round', 'stroke-linejoin':'round',
        'marker-end': markerFor(color),
        opacity: m.flow_type === 'control' ? 0.72 : 0.9
      }});
      if (m.dash) p.setAttribute('stroke-dasharray', m.flow_type === 'M2M' ? '7 4' : '5 4');
      p.addEventListener('mousemove', evt => showTip(evt, edge.id));
      p.addEventListener('mouseleave', hideTip);
      p.addEventListener('click', evt => pinTip(evt, edge.id));
      g.appendChild(p);
    }});
    (edge.labels || []).forEach(label => {{
      if (label.x === undefined || label.y === undefined) return;
      const lg = svgEl('g', {{class:'edge-label'}});
      const text = String(label.text || '');
      // Long transfer descriptors (BUF | WxH | FMT | bit | COMP) wrap into up
      // to two lines split on the " | " separators instead of overflowing.
      let lines = [text];
      if (text.length > 34 && text.includes(' | ')) {{
        const parts = text.split(' | ');
        let first = parts.shift();
        while (parts.length && (first + ' | ' + parts[0]).length <= Math.ceil(text.length / 2) + 4) {{
          first = first + ' | ' + parts.shift();
        }}
        lines = parts.length ? [first, parts.join(' | ')] : [first];
      }}
      const longest = Math.max(...lines.map(l => l.length));
      const w = Math.max(30, Math.min(300, longest * 5.6 + 14));
      const lh = 12;
      const boxH = lines.length * lh + 6;
      const x = label.x + ox;
      const y = label.y + oy;
      lg.appendChild(svgEl('rect', {{x, y, width:w, height:boxH, rx:3, fill:'#FFFFFF', stroke:color, 'stroke-width':0.8, opacity:0.95}}));
      const te = svgEl('text', {{x:x + w/2, y:y + 12, 'text-anchor':'middle', 'font-size':9, 'font-weight':700, fill:color}});
      lines.forEach((line, i) => {{
        const tspan = svgEl('tspan', {{x: x + w/2, dy: i === 0 ? 0 : lh}});
        tspan.textContent = line;
        te.appendChild(tspan);
      }});
      lg.appendChild(te);
      g.appendChild(lg);
    }});
  }});
}}

async function mainRender() {{
  try {{
    if (G.manualLayout) {{
      layoutGraph = G;
    }} else {{
      const elk = new ELK();
      layoutGraph = await elk.layout(G);
    }}
    main.innerHTML = '';
    Object.keys(NP).forEach(k => delete NP[k]);
    collectPositions(layoutGraph, 0, 0);
    drawBackgrounds(main, layoutGraph, 0, 0);
    drawGraphEdges(main, layoutGraph, 0, 0);
    drawLeaves(main, layoutGraph, 0, 0);
    initialGraphView();
  }} catch (err) {{
    shell.insertAdjacentHTML('beforeend', `<div class="error">ELK layout failed: ${{esc(err && err.message ? err.message : err)}}<br/>If this network is offline, vendor elk.bundled.js into the app static assets.</div>`);
  }}
}}

document.getElementById('zoomOut').onclick = () => zoomBy(0.84);
document.getElementById('zoomIn').onclick = () => zoomBy(1.18);
document.getElementById('fit').onclick = fitGraph;
document.getElementById('reset').onclick = resetGraph;
document.getElementById('exportSvg').onclick = () => {{
  if (!layoutGraph) return;
  // Clone at identity transform so the export always contains the full
  // graph regardless of the current pan/zoom.
  const clone = svg.cloneNode(true);
  const gw = Math.ceil((layoutGraph.width || 800) + PAD * 2);
  const gh = Math.ceil((layoutGraph.height || 600) + PAD * 2);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(gw));
  clone.setAttribute('height', String(gh));
  clone.setAttribute('viewBox', `0 0 ${{gw}} ${{gh}}`);
  const cloneMain = clone.querySelector('#main');
  if (cloneMain) cloneMain.setAttribute('transform', `translate(${{PAD}},${{PAD}}) scale(1)`);
  clone.insertAdjacentHTML('afterbegin', '<rect width="100%" height="100%" fill="#FFFFFF"/>');
  const text = new XMLSerializer().serializeToString(clone);
  const blob = new Blob([text], {{type: 'image/svg+xml'}});
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  const title = (VIEW.scenario || 'view') + '_' + (VIEW.layout || 'diagram');
  link.download = title.replace(/[^A-Za-z0-9._-]+/g, '_') + '.svg';
  link.click();
  URL.revokeObjectURL(link.href);
}};

let dragging = false, sx = 0, sy = 0, startTx = 0, startTy = 0, dragDist = 0;
svg.addEventListener('mousedown', evt => {{
  dragging = true; dragDist = 0; sx = evt.clientX; sy = evt.clientY; startTx = tx; startTy = ty; svg.classList.add('dragging');
  svg.focus();
}});
window.addEventListener('mousemove', evt => {{
  if (!dragging) return;
  dragDist += 1;
  tx = startTx + (evt.clientX - sx);
  ty = startTy + (evt.clientY - sy);
  setTransform();
}});
window.addEventListener('mouseup', () => {{ dragging = false; svg.classList.remove('dragging'); }});
svg.addEventListener('wheel', evt => {{
  evt.preventDefault();
  zoomBy(evt.deltaY > 0 ? 0.92 : 1.08);
}}, {{passive:false}});
svg.addEventListener('click', evt => {{
  if (dragDist <= 3 && !tip.contains(evt.target)) unpinTip();
}});
svg.addEventListener('keydown', evt => {{
  const PAN_STEP = 60;
  if (evt.key === 'ArrowLeft') tx += PAN_STEP;
  else if (evt.key === 'ArrowRight') tx -= PAN_STEP;
  else if (evt.key === 'ArrowUp') ty += PAN_STEP;
  else if (evt.key === 'ArrowDown') ty -= PAN_STEP;
  else if (evt.key === 'Escape') {{ unpinTip(); return; }}
  else return;
  evt.preventDefault();
  setTransform();
}});
window.addEventListener('resize', fitGraph);
mainRender();
</script>
</body>
</html>"""


def _safe_script_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


STATIC_ELK_URL = "/app/static/elk.bundled.js"
_STATIC_ELK_PATH = Path(__file__).resolve().parents[1] / "static" / "elk.bundled.js"


def _static_elk_available() -> bool:
    """True when the browser can fetch the ELK runtime from the static route."""
    if not _STATIC_ELK_PATH.is_file():
        return False
    try:
        import streamlit as st

        return bool(st.get_option("server.enableStaticServing"))
    except Exception:
        return False


@lru_cache(maxsize=1)
def _elk_runtime_script() -> str:
    try:
        return f"<script>\n{_STATIC_ELK_PATH.read_text(encoding='utf-8')}\n</script>"
    except OSError:
        return '<script src="https://cdn.jsdelivr.net/npm/elkjs@0.9.3/lib/elk.bundled.js"></script>'
