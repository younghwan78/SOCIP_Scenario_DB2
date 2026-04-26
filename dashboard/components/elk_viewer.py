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
from typing import Any

import streamlit.components.v1 as components

from dashboard.components.viewer_theme import EDGE_COLOR, LAYER_GRADIENT
from scenario_db.api.schemas.view import EdgeElement, NodeElement, ViewResponse

ALL_LAYERS = ["app", "framework", "hal", "kernel", "hw", "memory"]
ALL_EDGE_TYPES = ["OTF", "vOTF", "M2M", "control", "risk"]

LAYER_LABELS = {
    "app": "App",
    "framework": "Framework",
    "hal": "HAL",
    "kernel": "Kernel",
    "hw": "HW",
    "memory": "Memory",
}

LAYER_TINT = {
    "app": "#F3ECFF",
    "framework": "#ECF2FF",
    "hal": "#E9FBF8",
    "kernel": "#F2ECFF",
    "hw": "#FFF4E8",
    "memory": "#E9FBF6",
    "meta": "#F8FAFC",
}

TYPE_STYLE = {
    "sw": {"fill": "#FFFFFF", "stroke": "#64748B", "text": "#1F2937"},
    "ip": {"fill": "#FED7AA", "stroke": "#F97316", "text": "#7C2D12"},
    "submodule": {"fill": "#DBEAFE", "stroke": "#3B82F6", "text": "#1E3A8A"},
    "dma_group": {"fill": "#FFEDD5", "stroke": "#F97316", "text": "#7C2D12"},
    "dma_channel": {"fill": "#FFF7ED", "stroke": "#FB923C", "text": "#7C2D12"},
    "sysmmu": {"fill": "#E2E8F0", "stroke": "#64748B", "text": "#334155"},
    "buffer": {"fill": "#CCFBF1", "stroke": "#0F766E", "text": "#064E3B"},
    "group": {"fill": "#F8FAFC", "stroke": "#CBD5E1", "text": "#334155"},
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
    """Render a ViewResponse using ELK orthogonal routing."""
    graph, meta = build_elk_graph(view)
    height = canvas_height or int(view.metadata.get("canvas_h") or 900)
    components.html(_html(graph, meta, title or "ScenarioDB View", height), height=height + 52, scrolling=False)


def build_elk_graph(view: ViewResponse) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build an ELK graph and rendering metadata from a ViewResponse.

    This function is intentionally testable without Streamlit/browser runtime.
    """
    layout = str(view.metadata.get("layout") or "")
    if layout == "layered-lanes":
        return _build_layered_architecture(view)
    return _build_grouped_graph(view)


def _build_layered_architecture(view: ViewResponse) -> tuple[dict[str, Any], dict[str, Any]]:
    meta: dict[str, Any] = {"__view__": _view_meta(view)}
    nodes_by_layer: dict[str, list[NodeElement]] = defaultdict(list)
    for node in _functional_nodes(view.nodes):
        layer = node.data.layer if node.data.layer in ALL_LAYERS else "hw"
        nodes_by_layer[layer].append(node)

    layer_groups: list[dict[str, Any]] = []
    for layer in ALL_LAYERS:
        children = [_elk_leaf(node, meta) for node in _sort_nodes(nodes_by_layer.get(layer, []))]
        if not children:
            continue
        layer_groups.append(_elk_group(f"layer-{layer}", LAYER_LABELS[layer], layer, children, meta, direction="RIGHT"))

    visible_edges = _elk_edges(view.edges, meta)
    graph = _elk_root(
        children=layer_groups,
        edges=visible_edges + _layer_order_edges([group["id"] for group in layer_groups], meta),
        direction="DOWN",
        spacing=38,
        node_node=26,
        hierarchy=True,
    )
    return graph, meta


def _build_grouped_graph(view: ViewResponse) -> tuple[dict[str, Any], dict[str, Any]]:
    meta: dict[str, Any] = {"__view__": _view_meta(view)}
    group_nodes = [node for node in view.nodes if _is_group_box(node)]
    leaf_nodes = [node for node in _functional_nodes(view.nodes) if not _is_group_box(node)]

    assigned: set[str] = set()
    children: list[dict[str, Any]] = []
    for group in _sort_nodes(group_nodes):
        contained = [node for node in leaf_nodes if _inside_group(group, node)]
        if not contained:
            continue
        assigned.update(node.data.id for node in contained)
        children.append(
            _elk_group(
                group.data.id,
                group.data.label,
                "meta",
                [_elk_leaf(node, meta) for node in _sort_nodes(contained)],
                meta,
                direction="DOWN",
            )
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
) -> dict[str, Any]:
    width = max(260, sum(int(child.get("width", 120)) for child in children) // max(len(children), 1) + 80)
    height = 110 + (len(children) * 6)
    meta[node_id] = {
        "id": node_id,
        "label": label,
        "type": "group",
        "layer": layer,
        "fill": LAYER_TINT.get(layer, "#F8FAFC"),
        "stroke": _layer_stroke(layer),
        "text": "#334155",
        "details": [],
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
        label = data.label or ("SW" if data.flow_type == "control" else data.flow_type)
        out.append(
            {
                "id": data.id,
                "sources": [data.source],
                "targets": [data.target],
                "labels": [{"text": label, "width": max(38, min(260, len(label) * 6 + 14)), "height": 18}],
            }
        )
    return out


def _layer_order_edges(layer_group_ids: list[str], meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Invisible edges keep Level 0 groups in App->...->Memory order."""
    edges: list[dict[str, Any]] = []
    for idx, (source, target) in enumerate(zip(layer_group_ids, layer_group_ids[1:])):
        edge_id = f"__layer_order_{idx}"
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
    if data.ip_ref:
        details.append(f"IP: {data.ip_ref}")
    if data.capability_badges:
        details.append("Capabilities: " + ", ".join(data.capability_badges[:6]))
    if data.summary_badges:
        details.append("Summary: " + ", ".join(data.summary_badges[:6]))
    if data.active_operations:
        op = data.active_operations
        ops = []
        if op.crop:
            ops.append("crop")
        if op.scale:
            ops.append(f"scale {op.scale_from or ''}->{op.scale_to or ''}".strip())
        if op.rotate is not None:
            ops.append(f"rotate {op.rotate}")
        if op.colorspace_convert:
            ops.append(f"csc {op.colorspace_convert}")
        if ops:
            details.append("Ops: " + ", ".join(ops))
    if data.memory:
        mem = data.memory
        mem_bits = [mem.format, f"{mem.width}x{mem.height}" if mem.width and mem.height else None, f"{mem.fps}fps" if mem.fps else None, mem.compression]
        details.append("Memory: " + " / ".join(str(bit) for bit in mem_bits if bit))
    if data.placement and data.placement.llc_allocated:
        placement = data.placement
        mb = f"{placement.llc_allocation_mb:g}MB " if placement.llc_allocation_mb else ""
        details.append(f"LLC: {mb}{placement.llc_policy}")
    return {
        "id": data.id,
        "label": data.label,
        "type": data.type,
        "layer": data.layer,
        "fill": style["fill"],
        "stroke": style["stroke"],
        "text": style["text"],
        "badges": data.summary_badges[:4],
        "details": details,
        "warning": data.warning,
        "severity": data.severity,
    }


def _edge_meta(edge: EdgeElement) -> dict[str, Any]:
    data = edge.data
    details = [f"{data.source} -> {data.target}", f"Type: {data.flow_type}"]
    if data.latency_class:
        details.append(f"Latency: {data.latency_class}")
    if data.buffer_ref:
        details.append(f"Buffer: {data.buffer_ref}")
    if data.memory:
        mem = data.memory
        bits = [mem.format, f"{mem.width}x{mem.height}" if mem.width and mem.height else None, mem.compression]
        details.append("Memory: " + " / ".join(str(bit) for bit in bits if bit))
    if data.placement and data.placement.llc_allocated:
        details.append(f"LLC: {data.placement.llc_policy}")
    return {
        "id": data.id,
        "label": data.label or data.flow_type,
        "type": "edge",
        "flow_type": data.flow_type,
        "stroke": EDGE_COLOR.get(data.flow_type, "#64748B"),
        "dash": data.flow_type in {"control", "risk", "M2M"},
        "details": details,
    }


def _style_for_node(node: NodeElement) -> dict[str, str]:
    data = node.data
    if data.type == "sw" and data.layer in LAYER_GRADIENT:
        gradient = LAYER_GRADIENT[data.layer]
        return {"fill": gradient["g2"], "stroke": gradient["border"], "text": gradient["text"]}
    if data.type == "buffer":
        return TYPE_STYLE["buffer"]
    return TYPE_STYLE.get(data.type, TYPE_STYLE["sw"])


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


def _html(graph: dict[str, Any], meta: dict[str, Any], title: str, height: int) -> str:
    graph_json = json.dumps(graph, ensure_ascii=False)
    meta_json = json.dumps(meta, ensure_ascii=False)
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<script src="https://cdn.jsdelivr.net/npm/elkjs@0.9.3/lib/elk.bundled.js"></script>
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
    </div>
  </div>
  <svg id="svg"><defs>
    <marker id="arrow-blue" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#4A6CF7"/></marker>
    <marker id="arrow-teal" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#2BB3AA"/></marker>
    <marker id="arrow-orange" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#F97316"/></marker>
    <marker id="arrow-gray" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#9B8EC4"/></marker>
    <marker id="arrow-red" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L8,3 z" fill="#EF4444"/></marker>
  </defs><g id="main"></g></svg>
  <div class="elk-legend">
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#4A6CF7" stroke-width="2"/><path d="M31 1 L37 4 L31 7" fill="#4A6CF7"/></svg> OTF</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#2BB3AA" stroke-width="2"/><path d="M31 1 L37 4 L31 7" fill="#2BB3AA"/></svg> vOTF</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#F97316" stroke-width="2" stroke-dasharray="5 4"/><path d="M31 1 L37 4 L31 7" fill="#F97316"/></svg> M2M</span>
    <span><svg width="38" height="8"><path d="M1 4 H35" stroke="#9B8EC4" stroke-width="2" stroke-dasharray="5 4"/><path d="M31 1 L37 4 L31 7" fill="#9B8EC4"/></svg> SW</span>
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
let scale = 1, tx = 0, ty = 0;
let layoutGraph = null;
const PAD = 36;
const NP = {{}};

function markerFor(color) {{
  if (color === '#2BB3AA') return 'url(#arrow-teal)';
  if (color === '#F97316') return 'url(#arrow-orange)';
  if (color === '#9B8EC4') return 'url(#arrow-gray)';
  if (color === '#EF4444') return 'url(#arrow-red)';
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

function zoomBy(factor) {{
  scale = Math.max(0.35, Math.min(1.8, scale * factor));
  setTransform();
}}

function showTip(evt, id) {{
  const m = M[id] || {{}};
  const details = (m.details || []).map(d => `<div class="muted">${{esc(d)}}</div>`).join('');
  const badges = (m.badges || []).map(b => `<span class="muted">${{esc(b)}}</span>`).join(' ');
  tip.innerHTML = `<b>${{esc(m.label || id)}}</b><div class="muted">${{esc(m.layer || m.flow_type || m.type || '')}}</div>${{details}}${{badges ? '<div>'+badges+'</div>' : ''}}`;
  tip.style.left = `${{evt.clientX - shell.getBoundingClientRect().left + 10}}px`;
  tip.style.top = `${{evt.clientY - shell.getBoundingClientRect().top + 10}}px`;
  tip.style.opacity = 1;
}}

function hideTip() {{
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
    ng.appendChild(svgEl('rect', {{
      x, y, width: node.width || 140, height: node.height || 54, rx: 8, ry: 8,
      fill: m.fill || '#FFFFFF', stroke: m.stroke || '#64748B',
      'stroke-width': m.warning ? 2.4 : 1.8,
      filter: 'drop-shadow(0 2px 4px rgba(15,23,42,.08))'
    }}));
    drawLabel(ng, m.label || node.id, x, y + Math.max(0, ((node.height || 54) - 42) / 2), node.width || 140, m.text || '#111827');
    if (m.warning) {{
      ng.appendChild(svgEl('circle', {{cx: x + (node.width || 140) - 13, cy: y + 13, r: 6, fill:'#F97316'}}));
    }}
    ng.addEventListener('mousemove', evt => showTip(evt, node.id));
    ng.addEventListener('mouseleave', hideTip);
    g.appendChild(ng);
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
    ng.appendChild(svgEl('rect', {{
      x, y, width: node.width || 140, height: node.height || 54, rx: 8, ry: 8,
      fill: m.fill || '#FFFFFF', stroke: m.stroke || '#64748B',
      'stroke-width': m.warning ? 2.4 : 1.8,
      filter: 'drop-shadow(0 2px 4px rgba(15,23,42,.08))'
    }}));
    drawLabel(ng, m.label || node.id, x, y + Math.max(0, ((node.height || 54) - 42) / 2), node.width || 140, m.text || '#111827');
    if (m.warning) {{
      ng.appendChild(svgEl('circle', {{cx: x + (node.width || 140) - 13, cy: y + 13, r: 6, fill:'#F97316'}}));
    }}
    ng.addEventListener('mousemove', evt => showTip(evt, node.id));
    ng.addEventListener('mouseleave', hideTip);
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
    (edge.sections || []).forEach(section => {{
      const p = svgEl('path', {{
        class:'edge', d: pathFromSection(section, ox, oy), fill:'none', stroke:color,
        'stroke-width': m.flow_type === 'risk' ? 1.8 : 1.55,
        'stroke-linecap':'round', 'stroke-linejoin':'round',
        'marker-end': markerFor(color),
        opacity: m.flow_type === 'control' ? 0.72 : 0.9
      }});
      if (m.dash) p.setAttribute('stroke-dasharray', m.flow_type === 'M2M' ? '7 4' : '5 4');
      p.addEventListener('mousemove', evt => showTip(evt, edge.id));
      p.addEventListener('mouseleave', hideTip);
      g.appendChild(p);
    }});
    (edge.labels || []).forEach(label => {{
      if (label.x === undefined || label.y === undefined) return;
      const lg = svgEl('g', {{class:'edge-label'}});
      const text = String(label.text || '');
      const w = Math.max(30, Math.min(260, text.length * 6 + 12));
      const x = label.x + ox;
      const y = label.y + oy;
      lg.appendChild(svgEl('rect', {{x, y, width:w, height:18, rx:3, fill:'#FFFFFF', stroke:color, 'stroke-width':0.8, opacity:0.95}}));
      const te = svgEl('text', {{x:x + w/2, y:y + 12, 'text-anchor':'middle', 'font-size':9, 'font-weight':700, fill:color}});
      te.textContent = text;
      lg.appendChild(te);
      g.appendChild(lg);
    }});
  }});
}}

async function mainRender() {{
  try {{
    const elk = new ELK();
    layoutGraph = await elk.layout(G);
    main.innerHTML = '';
    Object.keys(NP).forEach(k => delete NP[k]);
    collectPositions(layoutGraph, 0, 0);
    drawBackgrounds(main, layoutGraph, 0, 0);
    drawGraphEdges(main, layoutGraph, 0, 0);
    drawLeaves(main, layoutGraph, 0, 0);
    fitGraph();
  }} catch (err) {{
    shell.insertAdjacentHTML('beforeend', `<div class="error">ELK layout failed: ${{esc(err && err.message ? err.message : err)}}<br/>If this network is offline, vendor elk.bundled.js into the app static assets.</div>`);
  }}
}}

document.getElementById('zoomOut').onclick = () => zoomBy(0.84);
document.getElementById('zoomIn').onclick = () => zoomBy(1.18);
document.getElementById('fit').onclick = fitGraph;
document.getElementById('reset').onclick = resetGraph;

let dragging = false, sx = 0, sy = 0, startTx = 0, startTy = 0;
svg.addEventListener('mousedown', evt => {{
  dragging = true; sx = evt.clientX; sy = evt.clientY; startTx = tx; startTy = ty; svg.classList.add('dragging');
}});
window.addEventListener('mousemove', evt => {{
  if (!dragging) return;
  tx = startTx + (evt.clientX - sx);
  ty = startTy + (evt.clientY - sy);
  setTransform();
}});
window.addEventListener('mouseup', () => {{ dragging = false; svg.classList.remove('dragging'); }});
svg.addEventListener('wheel', evt => {{
  evt.preventDefault();
  zoomBy(evt.deltaY > 0 ? 0.92 : 1.08);
}}, {{passive:false}});
window.addEventListener('resize', fitGraph);
mainRender();
</script>
</body>
</html>"""
