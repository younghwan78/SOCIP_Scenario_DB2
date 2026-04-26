"""Cytoscape.js Level 0 renderer — builds self-contained HTML for components.html().

Debug notes:
- SRI integrity hash is intentionally omitted (fake hash blocks loading)
- Classes-based styling preferred over attribute selectors (more reliable)
- Explicit px dimensions on both #wrapper and #cy to prevent 0x0 canvas
- cy.resize() + cy.fit() called in cy.ready() to handle iframe sizing
"""
from __future__ import annotations

import json

import streamlit.components.v1 as components

from dashboard.components.lane_layout import (
    BG_CENTER_X, BG_WIDTH, CANVAS_H, CANVAS_W, LANE_COLORS,
    LANE_DISPLAY_NAMES, LANE_GAP, LANE_H, LANE_LABEL_ORDER,
    LANE_LABEL_W, LANE_Y, NODE_H, NODE_W,
    STAGE_BOUNDS, STAGE_HEADER_H, STAGE_NAMES, STAGE_X,
    LANE_ICONS,
)
from dashboard.components.viewer_theme import EDGE_COLOR, LAYER_GRADIENT, LANE_BG_RGBA

ALL_LAYERS = list(LANE_Y.keys())
ALL_EDGE_TYPES = ["OTF", "vOTF", "M2M", "control", "risk"]

_LAYOUT_TYPES = {"lane_bg", "lane_label", "stage_header", "stage_divider"}


# ---------------------------------------------------------------------------
# Layout element builders (lane backgrounds, labels, stage headers)
# ---------------------------------------------------------------------------

def _build_layout_nodes() -> list[dict]:
    nodes: list[dict] = []

    # Lane backgrounds — wide rectangle, behind functional nodes (z-index 1)
    for lane in LANE_LABEL_ORDER:
        nodes.append({
            "data": {"id": f"bg-{lane}", "label": "", "type": "lane_bg", "layer": lane},
            "position": {"x": float(BG_CENTER_X), "y": float(LANE_Y[lane])},
            "classes": f"lane-bg layer-{lane}",
        })

    # Lane labels — left column (x = lane label width / 2)
    for lane in LANE_LABEL_ORDER:
        icon = LANE_ICONS.get(lane, "")
        nodes.append({
            "data": {
                "id": f"lbl-{lane}",
                "label": f"{icon}\n{LANE_DISPLAY_NAMES[lane]}",
                "type": "lane_label", "layer": lane,
            },
            "position": {"x": float(LANE_LABEL_W) / 2.0, "y": float(LANE_Y[lane])},
            "classes": f"lane-label layer-{lane}",
        })

    # Stage headers — top row
    for key, name in STAGE_NAMES.items():
        nodes.append({
            "data": {"id": f"hdr-{key}", "label": name, "type": "stage_header", "layer": "meta"},
            "position": {"x": float(STAGE_X[key]), "y": float(STAGE_HEADER_H) / 2.0},
            "classes": "stage-header",
        })

    # Stage dividers — thin vertical marker at each boundary (except leftmost)
    for i, (key, (x0, _x1)) in enumerate(STAGE_BOUNDS.items()):
        if i == 0:
            continue
        nodes.append({
            "data": {"id": f"div-{key}", "label": "", "type": "stage_divider", "layer": "meta"},
            "position": {"x": float(x0), "y": float(CANVAS_H) / 2.0},
            "classes": "stage-div",
        })

    return nodes


# ---------------------------------------------------------------------------
# Stylesheet builder (class-based — avoids unreliable attribute selectors)
# ---------------------------------------------------------------------------

def _build_stylesheet(canvas_h: int) -> list[dict]:
    styles: list[dict] = []

    # ── Default node (fallback) ────────────────────────────────────────────
    # z-index-compare: "manual" lets edges (z:4) render above lane_bg nodes (z:1)
    # while functional nodes (z:10) stay on top. Without "manual", Cytoscape
    # always renders ALL nodes above ALL edges regardless of z-index values.
    styles.append({
        "selector": "node",
        "style": {
            "label": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-family": "Inter, system-ui, sans-serif",
            "font-size": 12,
            "font-weight": 600,
            "shape": "round-rectangle",
            "background-color": "#E5E7EB",
            "border-width": 1.5,
            "border-color": "#D1D5DB",
            "color": "#374151",
            "text-wrap": "none",
            "overlay-opacity": 0,
            "z-index-compare": "manual",
            "z-index": 10,
        },
    })

    # ── Lane background ────────────────────────────────────────────────────
    styles.append({
        "selector": ".lane-bg",
        "style": {
            "width": int(BG_WIDTH),
            "height": int(LANE_H) - 4,
            "shape": "round-rectangle",
            # Lane bands are context, not data. Keep them translucent so
            # OTF/vOTF/M2M/control edges remain visible on top of the lanes.
            "background-opacity": 0.22,
            "border-width": 1,
            "border-opacity": 0.35,
            "label": "",
            "events": "no",
            "z-index-compare": "manual",
            "z-index": -10,
        },
    })
    # Per-lane background tint (color must be a literal, not data() mapper)
    for lane in LANE_LABEL_ORDER:
        styles.append({
            "selector": f".layer-{lane}.lane-bg",
            "style": {
                "background-color": LANE_BG_RGBA[lane],
                "border-color": LANE_COLORS[lane]["border"],
            },
        })

    # ── Lane label ─────────────────────────────────────────────────────────
    styles.append({
        "selector": ".lane-label",
        "style": {
            "width": int(NODE_W["lane_label"]),
            "height": int(LANE_H) - 10,
            "background-opacity": 0,
            "border-width": 0,
            "font-size": 11,
            "font-weight": 700,
            "text-wrap": "wrap",
            "text-max-width": f"{NODE_W['lane_label']}px",
            "events": "no",
            "z-index-compare": "manual",
            "z-index": 6,   # above edges (z:4), below functional nodes (z:10)
        },
    })
    for lane in LANE_LABEL_ORDER:
        styles.append({
            "selector": f".lane-label.layer-{lane}",
            "style": {"color": LAYER_GRADIENT[lane]["border"]},
        })

    # ── Stage header ───────────────────────────────────────────────────────
    styles.append({
        "selector": ".stage-header",
        "style": {
            "width": int(NODE_W["stage_header"]),
            "height": int(NODE_H["stage_header"]),
            "background-opacity": 0,
            "border-width": 0,
            "font-size": 11,
            "font-weight": 600,
            "color": "#9CA3AF",
            "events": "no",
            "z-index-compare": "manual",
            "z-index": 6,
        },
    })

    # ── Stage divider ──────────────────────────────────────────────────────
    styles.append({
        "selector": ".stage-div",
        "style": {
            "width": 1,
            "height": canvas_h,
            "background-color": "#DDD8D0",
            "background-opacity": 0.55,
            "border-width": 0,
            "label": "",
            "events": "no",
            "z-index": 2,
        },
    })

    # ── Functional nodes: gradient by layer ────────────────────────────────
    # Use explicit per-layer-class selectors (reliable, no attribute selectors)
    for lane in LANE_LABEL_ORDER:
        g = LAYER_GRADIENT[lane]
        # Applies to any non-layout node with this layer class
        styles.append({
            "selector": f".layer-{lane}:not(.lane-bg):not(.lane-label)",
            "style": {
                "background-fill": "linear-gradient",
                "background-gradient-direction": "to-bottom-right",
                "background-gradient-stop-colors": f"{g['g1']} {g['g2']}",
                "background-gradient-stop-positions": "0 1",
                "border-color": g["border"],
                "color": g["text"],
                "z-index": 10,
            },
        })

    # ── Node sizing by type class ──────────────────────────────────────────
    styles.append({
        "selector": ".sw",
        "style": {"width": int(NODE_W["sw"]), "height": int(NODE_H["sw"])},
    })
    styles.append({
        "selector": ".ip",
        "style": {"width": int(NODE_W["ip"]), "height": int(NODE_H["ip"]), "font-size": 12},
    })
    styles.append({
        "selector": ".buffer",
        "style": {"width": int(NODE_W["buffer"]), "height": int(NODE_H["buffer"]), "font-size": 11},
    })
    styles.append({
        "selector": ".sized",
        "style": {
            "width": "data(w)",
            "height": "data(h)",
            "text-wrap": "wrap",
            "text-max-width": "data(text_w)",
        },
    })
    styles.append({
        "selector": ".group-box",
        "style": {
            "shape": "round-rectangle",
            "background-color": "#F8FAFC",
            "background-opacity": 0.42,
            "border-color": "#CBD5E1",
            "border-width": 1.4,
            "border-style": "solid",
            "color": "#64748B",
            "font-size": 13,
            "font-weight": 800,
            "text-valign": "top",
            "text-margin-y": 12,
            "events": "no",
            "z-index": -2,
        },
    })
    styles.append({
        "selector": ".task-node",
        "style": {
            "font-size": 11,
            "font-weight": 700,
            "text-wrap": "wrap",
            "text-max-width": "data(text_w)",
        },
    })
    styles.append({
        "selector": ".submodule:not(.group-box)",
        "style": {
            "background-fill": "linear-gradient",
            "background-gradient-direction": "to-bottom-right",
            "background-gradient-stop-colors": "#DBEAFE #BFDBFE",
            "border-color": "#60A5FA",
            "color": "#1E3A8A",
        },
    })
    styles.append({
        "selector": ".dma_channel",
        "style": {
            "background-fill": "linear-gradient",
            "background-gradient-direction": "to-bottom-right",
            "background-gradient-stop-colors": "#FFEDD5 #FED7AA",
            "border-color": "#F97316",
            "color": "#7C2D12",
        },
    })
    styles.append({
        "selector": ".sysmmu",
        "style": {
            "background-fill": "linear-gradient",
            "background-gradient-direction": "to-bottom-right",
            "background-gradient-stop-colors": "#F1F5F9 #E2E8F0",
            "border-color": "#64748B",
            "color": "#334155",
        },
    })

    # ── Warning / risk node ────────────────────────────────────────────────
    styles.append({
        "selector": ".warning",
        "style": {
            "border-color": "#EF4444",
            "border-width": 2.5,
            "border-style": "dashed",
        },
    })

    # ── Selected ───────────────────────────────────────────────────────────
    styles.append({
        "selector": "node:selected",
        "style": {
            "border-color": "#1D4ED8",
            "border-width": 3,
            "overlay-color": "#1D4ED8",
            "overlay-opacity": 0.08,
            "overlay-padding": 4,
        },
    })

    # ── Default edge ───────────────────────────────────────────────────────
    # z-index-compare: "manual" + z-index: 4 → renders above lane_bg (z:1)
    # but below functional nodes (z:10). This is the key fix for edge visibility:
    # without "manual", all nodes (including lane_bg) render above all edges.
    styles.append({
        "selector": "edge",
        "style": {
            "label": "data(label)",
            "font-size": 8,
            "font-weight": 700,
            "color": "#6B7280",
            "text-background-color": "#FFFFFF",
            "text-background-opacity": 0.72,
            "text-background-padding": 2,
            "width": 2,
            "line-color": "#9CA3AF",
            "target-arrow-color": "#9CA3AF",
            "target-arrow-shape": "vee",
            "arrow-scale": 0.95,
            "curve-style": "taxi",
            "taxi-direction": "auto",
            "taxi-turn": "50%",
            "opacity": 0.9,
            "overlay-opacity": 0,
            "z-index-compare": "manual",
            "z-index": 4,
        },
    })

    # ── Edge type classes ──────────────────────────────────────────────────
    edge_defs: dict[str, dict] = {
        "OTF": {
            "line-color": EDGE_COLOR["OTF"],
            "target-arrow-color": EDGE_COLOR["OTF"],
            "line-style": "solid",
            "width": 1.8,
        },
        "vOTF": {
            "line-color": EDGE_COLOR["vOTF"],
            "target-arrow-color": EDGE_COLOR["vOTF"],
            "source-arrow-color": EDGE_COLOR["vOTF"],
            "target-arrow-shape": "vee",
            "source-arrow-shape": "none",
            "line-style": "solid",
            "width": 2.0,
        },
        "M2M": {
            "line-color": EDGE_COLOR["M2M"],
            "target-arrow-color": EDGE_COLOR["M2M"],
            "line-style": "solid",
            "width": 1.8,
        },
        "control": {
            "line-color": EDGE_COLOR["control"],
            "target-arrow-color": EDGE_COLOR["control"],
            "source-arrow-color": EDGE_COLOR["control"],
            "target-arrow-shape": "vee",
            "source-arrow-shape": "vee",
            "line-style": "dashed",
            "line-dash-pattern": [6, 4],
            "width": 1.4,
            "opacity": 0.82,
        },
        "risk": {
            "line-color": EDGE_COLOR["risk"],
            "target-arrow-color": EDGE_COLOR["risk"],
            "line-style": "dashed",
            "line-dash-pattern": [8, 3],
            "width": 2,
        },
    }
    for etype, style in edge_defs.items():
        styles.append({"selector": f".edge-{etype}", "style": style})

    # edge selected
    styles.append({
        "selector": "edge:selected",
        "style": {"width": 2.8, "overlay-color": "#1D4ED8", "overlay-opacity": 0.10},
    })

    return styles


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _build_html(
    functional_nodes: list[dict],
    all_edges: list[dict],
    visible_layers: list[str],
    visible_edge_types: list[str],
    canvas_h: int,
    *,
    layout_mode: str = "layered-lanes",
    title: str | None = None,
) -> str:
    use_lanes = layout_mode == "layered-lanes"
    layout_nodes = _build_layout_nodes() if use_lanes else []
    stylesheet = _build_stylesheet(canvas_h)

    vis_set = set(visible_layers)
    if not use_lanes:
        vis_set.add("meta")
    vis_etypes = set(visible_edge_types)

    filtered_nodes = [
        n for n in functional_nodes
        if n["data"].get("layer") in vis_set
    ]
    filtered_ids = {n["data"]["id"] for n in filtered_nodes}

    filtered_edges = [
        e for e in all_edges
        if (
            e["data"].get("flow_type") in vis_etypes
            and e["data"]["source"] in filtered_ids
            and e["data"]["target"] in filtered_ids
        )
    ]

    all_elements = layout_nodes + filtered_nodes + filtered_edges

    # Legend SVG
    legend_html = "".join(
        f"""<div class="leg-item">
          <svg width="32" height="14" style="flex-shrink:0">
            <line x1="2" y1="7" x2="26" y2="7"
              stroke="{EDGE_COLOR[et]}"
              stroke-width="{'2.5' if et=='vOTF' else '2'}"
              stroke-dasharray="{'none' if et in ('OTF','vOTF','M2M') else '6,3'}"/>
            <polygon points="21,4 27,7 21,10" fill="{EDGE_COLOR[et]}"/>
          </svg>
          <span>{et if et != 'control' else 'SW'}</span>
        </div>"""
        for et in ALL_EDGE_TYPES
    )

    elem_json = json.dumps(all_elements, ensure_ascii=False)
    style_json = json.dumps(stylesheet, ensure_ascii=False)

    total_iframe_h = canvas_h + 52   # diagram + legend bar
    title_html = ""
    if title:
        title_html = f"""<div id="view-title">
          <span>{title}</span>
          <div id="view-controls">
            <button type="button" data-action="zoom-out">-</button>
            <button type="button" data-action="fit">Fit</button>
            <button type="button" data-action="reset">Reset</button>
            <button type="button" data-action="zoom-in">+</button>
          </div>
        </div>"""
        total_iframe_h += 38

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: 100%; height: {total_iframe_h}px;
    background: #FAF9F7;
    font-family: Inter, system-ui, -apple-system, sans-serif;
    overflow: hidden;
  }}
  /* Diagram wrapper — explicit px height so Cytoscape canvas is non-zero */
  #wrapper {{
    position: relative;
    width: 100%;
    height: {canvas_h}px;
    background: #FAFAF8;
    border: 1px solid #E8E4DF;
    border-radius: 8px;
    overflow: hidden;
  }}
  /* Cytoscape container — must have explicit pixel dimensions */
  #cy {{
    width: 100%;
    height: {canvas_h}px;
    display: block;
  }}
  #legend {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 6px 16px;
    height: 44px;
    background: #F9FAFB;
    border-top: 1px solid #E8E4DF;
    overflow: hidden;
    flex-wrap: nowrap;
  }}
  .leg-label {{ font-size: 11px; font-weight: 600; color: #9CA3AF; }}
  .leg-item {{
    display: flex; align-items: center; gap: 4px;
    font-size: 11px; color: #6B7280; white-space: nowrap;
  }}
  /* Debug bar — only shown if JS errors occur */
  #debug-bar {{
    position: fixed; bottom: 48px; left: 0; right: 0;
    background: #1e1e1e; color: #4ec9b0;
    font-family: monospace; font-size: 11px;
    padding: 3px 8px; z-index: 999;
    display: none;
  }}
  /* Tooltip */
  #tip {{
    display: none;
    position: absolute;
    background: white;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 10px 13px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.12);
    font-size: 12px;
    max-width: 260px;
    z-index: 200;
    pointer-events: none;
    line-height: 1.55;
  }}
  #view-title {{
    height: 38px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 10px 8px 4px;
    color: #111827;
    font-weight: 750;
    font-size: 15px;
  }}
  #view-controls {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  #view-controls button {{
    border: 1px solid #E5E7EB;
    background: #FFFFFF;
    color: #374151;
    border-radius: 7px;
    padding: 4px 9px;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
    box-shadow: 0 1px 3px rgba(17,24,39,0.04);
  }}
  #view-controls button:hover {{
    border-color: #A5B4FC;
    color: #4338CA;
    background: #F8FAFF;
  }}
  .tt-title {{ font-size: 13px; font-weight: 700; color: #111827;
    margin-bottom: 5px; border-bottom: 1px solid #F3F4F6; padding-bottom: 4px; }}
  .tt-row {{ display: flex; gap: 8px; font-size: 11px; color: #6B7280; margin-top: 2px; }}
  .tt-row .k {{ min-width: 76px; color: #9CA3AF; }}
  .tt-badge {{ display: inline-block; background: #EEF2FF; color: #3730A3;
    border-radius: 4px; padding: 1px 5px; font-size: 10px; font-weight: 600;
    margin: 0 2px 1px 0; }}
  .tt-risk {{ background: #FEE2E2 !important; color: #991B1B !important; }}
</style>
<!-- Cytoscape.js 3.29.2 — NO integrity attribute (fake hash blocks loading) -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.29.2/cytoscape.min.js"></script>
</head>
<body>

{title_html}
<div id="wrapper">
  <div id="cy"></div>
  <div id="tip"></div>
</div>
<div id="legend">
  <span class="leg-label">Edges:</span>
  {legend_html}
</div>
<div id="debug-bar"></div>

<script>
(function() {{
  'use strict';

  // ── Debug helper ──────────────────────────────────────────────────────
  const dbg = document.getElementById('debug-bar');
  function showDebug(msg) {{
    dbg.textContent = msg;
    dbg.style.display = 'block';
    console.log('[CytoscapeViewer]', msg);
  }}

  // ── Guard: Cytoscape must be loaded ──────────────────────────────────
  if (typeof cytoscape === 'undefined') {{
    showDebug('ERROR: cytoscape.js failed to load — check CDN / network');
    return;
  }}

  // ── Element data (embedded from Python) ──────────────────────────────
  const allElements = {elem_json};
  const stylesheet  = {style_json};

  console.log('[CytoscapeViewer] elements total:', allElements.length);
  const nodeCount = allElements.filter(e => !e.data.source).length;
  const edgeCount = allElements.filter(e => !!e.data.source).length;
  console.log('[CytoscapeViewer] nodes:', nodeCount, 'edges:', edgeCount);

  // Verify all nodes have positions (preset layout requires it)
  const missingPos = allElements.filter(e => !e.data.source && (!e.position || e.position.x == null));
  if (missingPos.length > 0) {{
    showDebug('WARN: ' + missingPos.length + ' nodes missing position: ' +
      missingPos.slice(0, 3).map(e => e.data.id).join(', '));
  }}

  // ── Initialise Cytoscape ──────────────────────────────────────────────
  let cy;
  try {{
    cy = cytoscape({{
      container: document.getElementById('cy'),
      elements: allElements,
      layout: {{ name: 'preset' }},
      style: stylesheet,
      zoom: 1.0,
      pan: {{ x: 0, y: 0 }},
      userZoomingEnabled: true,
      userPanningEnabled: true,
      minZoom: 0.55,
      maxZoom: 1.65,
      boxSelectionEnabled: false,
      motionBlur: false,
      textureOnViewport: false,
    }});
  }} catch(err) {{
    showDebug('ERROR init: ' + err.message);
    console.error(err);
    return;
  }}

  // ── After elements are rendered ───────────────────────────────────────
  function fitWhenSized(attempt) {{
    const container = cy.container();
    const w = container ? container.clientWidth : 0;
    const h = container ? container.clientHeight : 0;

    // Streamlit may create the component while a tab/iframe still reports
    // width=0. Fitting at that moment leaves Cytoscape with extent=[0,0→0,0]
    // and the graph looks blank even though nodes/edges are loaded.
    if ((w <= 10 || h <= 10) && attempt < 30) {{
      window.setTimeout(function() {{ fitWhenSized(attempt + 1); }}, 100);
      return;
    }}

    cy.resize();

    const funcNodes = cy.nodes().filter(function(n) {{
      const t = n.data('type');
      return t !== 'lane_bg' && t !== 'lane_label' && t !== 'stage_header' && t !== 'stage_divider';
    }});

    if (funcNodes.length > 0) {{
      cy.fit(funcNodes, 40);
    }} else {{
      cy.fit(undefined, 20);
    }}

    const ext = cy.extent();
    const info = 'OK nodes=' + cy.nodes().length +
      ' edges=' + cy.edges().length +
      ' size=' + w + 'x' + h +
      ' zoom=' + cy.zoom().toFixed(2) +
      ' extent=[' + ext.x1.toFixed(0) + ',' + ext.y1.toFixed(0) +
      '→' + ext.x2.toFixed(0) + ',' + ext.y2.toFixed(0) + ']';
    console.log('[CytoscapeViewer]', info);

    dbg.textContent = info;
    dbg.style.display = 'none';
  }}

  cy.ready(function() {{
    window.__scenarioDbCy = cy;
    window.requestAnimationFrame(function() {{ fitWhenSized(0); }});
  }});

  document.querySelectorAll('#view-controls button').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      const action = btn.getAttribute('data-action');
      const funcNodes = cy.nodes().filter(function(n) {{
        const t = n.data('type');
        return t !== 'lane_bg' && t !== 'lane_label' && t !== 'stage_header' && t !== 'stage_divider';
      }});
      if (action === 'fit' || action === 'reset') {{
        cy.stop();
        if (funcNodes.length > 0) {{
          cy.fit(funcNodes, action === 'reset' ? 55 : 32);
        }} else {{
          cy.fit(undefined, 32);
        }}
      }} else if (action === 'zoom-in') {{
        cy.zoom({{ level: Math.min(cy.maxZoom(), cy.zoom() * 1.10), renderedPosition: {{ x: cy.width() / 2, y: cy.height() / 2 }} }});
      }} else if (action === 'zoom-out') {{
        cy.zoom({{ level: Math.max(cy.minZoom(), cy.zoom() / 1.10), renderedPosition: {{ x: cy.width() / 2, y: cy.height() / 2 }} }});
      }}
    }});
  }});

  // ── Tooltip ───────────────────────────────────────────────────────────
  const tip = document.getElementById('tip');

  function hideTip() {{ tip.style.display = 'none'; }}

  function showTip(node) {{
    const d = node.data();
    const skip = ['lane_bg', 'lane_label', 'stage_header', 'stage_divider'];
    if (skip.includes(d.type)) return;

    let html = '<div class="tt-title">' + (d.label || d.id) + '</div>';

    if (d.layer && d.layer !== 'meta') {{
      html += '<div class="tt-row"><span class="k">Layer</span><span>' + d.layer + '</span></div>';
    }}
    if (d.type) {{
      html += '<div class="tt-row"><span class="k">Type</span><span>' + d.type + '</span></div>';
    }}
    if (d.ip_ref) {{
      html += '<div class="tt-row"><span class="k">IP ref</span><span>' + d.ip_ref + '</span></div>';
    }}

    const caps = d.capability_badges;
    if (caps && caps.length) {{
      html += '<div class="tt-row"><span class="k">Capabilities</span><span>' +
        caps.map(function(b) {{ return '<span class="tt-badge">' + b + '</span>'; }}).join('') +
        '</span></div>';
    }}

    const ops = d.active_operations;
    if (ops) {{
      if (ops.scale) {{
        html += '<div class="tt-row"><span class="k">Scale</span><span>' +
          (ops.scale_from || '?') + ' → ' + (ops.scale_to || '?') + '</span></div>';
      }}
      if (ops.crop) {{
        html += '<div class="tt-row"><span class="k">Crop</span><span>' +
          (ops.crop_ratio ? 'ratio ' + ops.crop_ratio : 'yes') + '</span></div>';
      }}
    }}

    const mem = d.memory;
    if (mem) {{
      const parts = [mem.format,
        (mem.width && mem.height ? mem.width + 'x' + mem.height : null),
        (mem.fps ? mem.fps + 'fps' : null),
        mem.compression].filter(Boolean);
      if (parts.length) {{
        html += '<div class="tt-row"><span class="k">Memory</span><span>' +
          parts.join(' · ') + '</span></div>';
      }}
    }}

    const pl = d.placement;
    if (pl && pl.llc_allocated) {{
      html += '<div class="tt-row"><span class="k">LLC</span><span>' +
        (pl.llc_allocation_mb || '?') + ' MB (' + (pl.llc_policy || '') + ')</span></div>';
    }}

    const issues = d.matched_issues;
    if (issues && issues.length) {{
      html += '<div class="tt-row"><span class="k">Issues</span><span>' +
        issues.map(function(i) {{
          return '<span class="tt-badge tt-risk">' + i + '</span>';
        }}).join('') + '</span></div>';
    }}

    tip.innerHTML = html;

    // Position tooltip relative to #wrapper
    const wrap = document.getElementById('wrapper');
    const pan = cy.pan();
    const zoom = cy.zoom();
    const pos = node.position();
    const px = pos.x * zoom + pan.x;
    const py = pos.y * zoom + pan.y;
    let left = px + 16;
    let top  = py - 16;
    if (left + 270 > wrap.clientWidth) left = px - 275;
    if (top + 200 > wrap.clientHeight) top  = py - 205;
    tip.style.left = left + 'px';
    tip.style.top  = top  + 'px';
    tip.style.display = 'block';
  }}

  cy.on('tap', 'node', function(evt) {{ showTip(evt.target); }});
  cy.on('tap', function(evt) {{
    if (evt.target === cy) hideTip();
  }});
  cy.on('pan zoom', hideTip);

}})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public render function
# ---------------------------------------------------------------------------

def render_level0(
    view_response,
    visible_layers: list[str] | None = None,
    visible_edge_types: list[str] | None = None,
    canvas_height: int = 640,
    selected_node: dict | None = None,
    title: str | None = None,
) -> None:
    """Render Level 0 Cytoscape lane diagram into the current Streamlit location."""
    if visible_layers is None:
        visible_layers = ALL_LAYERS[:]
    if visible_edge_types is None:
        visible_edge_types = ALL_EDGE_TYPES[:]

    # ── Build Cytoscape node list ──────────────────────────────────────────
    functional_nodes: list[dict] = []
    for ne in view_response.nodes:
        d = ne.data

        # Flatten to a plain dict for Cytoscape data (nested Pydantic → dict)
        data_flat: dict = {
            "id":    d.id,
            "label": d.label,
            "type":  d.type,
            "layer": d.layer,
        }
        if d.parent:
            data_flat["parent"] = d.parent
        if d.view_hints and d.view_hints.width:
            data_flat["w"] = int(d.view_hints.width)
            data_flat["text_w"] = max(40, int(d.view_hints.width) - 16)
        if d.view_hints and d.view_hints.height:
            data_flat["h"] = int(d.view_hints.height)
        if d.ip_ref:
            data_flat["ip_ref"] = d.ip_ref
        if d.sw_ref:
            data_flat["sw_ref"] = d.sw_ref
        if d.capability_badges:
            data_flat["capability_badges"] = d.capability_badges
        if d.matched_issues:
            data_flat["matched_issues"] = d.matched_issues
        if d.warning:
            data_flat["warning"] = True
        if d.severity:
            data_flat["severity"] = d.severity
        if d.active_operations:
            data_flat["active_operations"] = d.active_operations.model_dump(exclude_none=True)
        if d.memory:
            data_flat["memory"] = d.memory.model_dump(exclude_none=True)
        if d.placement:
            data_flat["placement"] = d.placement.model_dump(exclude_none=True)

        # CSS classes: layer + type + optional warning
        classes_list = [f"layer-{d.layer}", d.type]
        if d.view_hints and (d.view_hints.width or d.view_hints.height):
            classes_list.append("sized")
        if d.layer == "meta" and d.type == "submodule":
            classes_list.append("group-box")
        if d.summary_badges and "task" in d.summary_badges:
            classes_list.append("task-node")
        if d.warning:
            classes_list.append("warning")

        functional_nodes.append({
            "data": data_flat,
            "position": {
                "x": float(ne.position["x"]),
                "y": float(ne.position["y"]),
            },
            "classes": " ".join(classes_list),
        })

    # ── Build Cytoscape edge list ──────────────────────────────────────────
    edges: list[dict] = []
    for ee in view_response.edges:
        ed = ee.data
        edge_data: dict = {
            "id":        ed.id,
            "source":    ed.source,
            "target":    ed.target,
            "flow_type": ed.flow_type,
        }
        if ed.label:
            edge_data["label"] = ed.label
        edges.append({
            "data":    edge_data,
            "classes": f"edge-{ed.flow_type}",
        })

    html = _build_html(
        functional_nodes=functional_nodes,
        all_edges=edges,
        visible_layers=visible_layers,
        visible_edge_types=visible_edge_types,
        canvas_h=canvas_height,
        layout_mode=str(view_response.metadata.get("layout") or "layered-lanes"),
        title=title,
    )

    iframe_h = canvas_height + 96
    components.html(html, height=iframe_h, scrolling=False)
