r"""Pipeline Viewer for ScenarioDB.

Run from the project virtual environment:
  .\.venv\Scripts\python.exe -m streamlit run dashboard/Home.py
"""
from __future__ import annotations

import os
import sys
from html import escape
from pathlib import Path

import requests
import streamlit as st

_root = Path(__file__).resolve().parents[2]
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.components.elk_viewer import render_elk_view
from scenario_db.api.schemas.view import ViewResponse
from scenario_db.view.service import build_sample_level0


st.set_page_config(
    page_title="Pipeline Viewer - ScenarioDB",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  .block-container {
    padding-top: 0.4rem !important;
    padding-bottom: 1rem !important;
    padding-left: 1.2rem !important;
    padding-right: 1.2rem !important;
    max-width: none !important;
  }
  header[data-testid="stHeader"], footer, #MainMenu { display: none !important; }
  section[data-testid="stSidebar"] { width: 260px !important; min-width: 260px !important; }
  section[data-testid="stSidebar"] > div { width: 260px !important; }
  .viewer-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0 12px 0;
    border-bottom: 1px solid #E8E4DF;
    margin-bottom: 12px;
  }
  .viewer-title { font-size: 21px; font-weight: 800; color: #111827; }
  .meta-chip {
    background: #F3F4F6;
    border: 1px solid #E5E7EB;
    border-radius: 7px;
    padding: 3px 8px;
    font-size: 11px;
    color: #6B7280;
    font-weight: 650;
  }
  .section-card {
    border: 1px solid #E8E4DF;
    border-radius: 12px;
    background: #FAF9F7;
    padding: 10px 10px 4px 10px;
    margin: 10px 0 18px 0;
  }
  .compact-panel {
    border: 1px solid #E8E4DF;
    border-radius: 10px;
    background: #FFFFFF;
    padding: 10px 12px;
    margin: 8px 0 12px 0;
  }
  .compact-panel h4 {
    margin: 0 0 6px 0;
    font-size: 12px;
    color: #6B7280;
    text-transform: uppercase;
    letter-spacing: .05em;
  }
  .risk-chip {
    display: inline-block;
    border-radius: 7px;
    border: 1px solid #FDE68A;
    background: #FFFBEB;
    color: #92400E;
    padding: 4px 7px;
    font-size: 11px;
    font-weight: 650;
    margin: 2px 4px 2px 0;
  }
  .detail-panel {
    position: sticky;
    top: 8px;
    border-left: 1px solid #E8E4DF;
    background: #FFFFFF;
    padding: 10px 0 10px 14px;
    min-height: 640px;
    font-size: 12px;
    color: #374151;
  }
  .detail-panel h4 {
    margin: 4px 0 8px 0;
    font-size: 12px;
    color: #111827;
    font-weight: 800;
  }
  .detail-panel p {
    margin: 0 0 8px 0;
    line-height: 1.45;
    color: #4B5563;
  }
  .detail-table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 14px 0;
    font-size: 11px;
  }
  .detail-table td {
    border-bottom: 1px solid #F1F5F9;
    padding: 4px 2px;
    vertical-align: top;
  }
  .detail-table td:first-child {
    color: #6B7280;
    width: 42%;
  }
  .detail-risk {
    border-left: 3px solid #F59E0B;
    background: #FFFBEB;
    border-radius: 6px;
    padding: 6px 8px;
    margin: 5px 0;
    font-size: 11px;
    line-height: 1.35;
  }
  .ip-mini-row {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    border-bottom: 1px solid #F1F5F9;
    padding: 4px 0;
    font-size: 11px;
  }
  .ip-mini-row span:last-child {
    color: #64748B;
    text-align: right;
  }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=30)
def _load_view(
    base_url: str,
    scenario_id: str,
    variant_id: str,
    level: int,
    mode: str | None = None,
    expand: str | None = None,
) -> tuple[ViewResponse, str]:
    params: dict[str, object] = {"level": level}
    if mode:
        params["mode"] = mode
    if level == 2 and expand:
        params["expand"] = expand
    try:
        url = f"{base_url.rstrip('/')}/scenarios/{scenario_id}/variants/{variant_id}/view"
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        return ViewResponse.model_validate(response.json()), "api"
    except Exception as exc:
        fallback = build_sample_level0()
        fallback.metadata["load_error"] = str(exc)
        return fallback, "sample-fallback"


def _render_detail_panel(view: ViewResponse) -> None:
    summary = view.summary
    risks = "".join(
        f"""<div class="detail-risk"><b>{escape(risk.severity)}</b> {escape(risk.title)}<br>
        <span>{escape(risk.component)} · {escape(risk.impact)}</span></div>"""
        for risk in view.risks[:3]
    ) or "<p>No active risk cards.</p>"

    ip_rows = []
    for node in view.nodes:
        data = node.data
        if data.type not in {"ip", "submodule", "dma_group", "sysmmu"}:
            continue
        badges = ", ".join(data.capability_badges[:3]) if data.capability_badges else data.layer
        ip_rows.append(
            f"""<div class="ip-mini-row"><b>{escape(data.label.splitlines()[0])}</b>
            <span>{escape(badges)}</span></div>"""
        )
        if len(ip_rows) >= 8:
            break

    html = f"""
<div class="detail-panel">
  <h4>Node / Edge Detail</h4>
  <p>Click a node inside the graph for inline tooltip details. This panel keeps scenario-level context visible while scrolling.</p>
  <table class="detail-table">
    <tr><td>Scenario</td><td>{escape(summary.name)}</td></tr>
    <tr><td>Variant</td><td>{escape(summary.variant_id)}</td></tr>
    <tr><td>Resolution</td><td>{escape(summary.resolution)}</td></tr>
    <tr><td>Frame Rate</td><td>{summary.fps} fps</td></tr>
    <tr><td>Period</td><td>{summary.period_ms} ms</td></tr>
    <tr><td>Budget</td><td>{summary.budget_ms} ms</td></tr>
  </table>
  <h4>Risks</h4>
  {risks}
  <h4>IP Summary</h4>
  {''.join(ip_rows) if ip_rows else '<p>No IP nodes in current view.</p>'}
</div>
"""
    st.markdown(html, unsafe_allow_html=True)


with st.sidebar:
    st.markdown("### ScenarioDB Viewer")
    api_base = st.text_input(
        "API Base",
        value=os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
    )
    scenario_id_input = st.text_input("Scenario", value="uc-camera-recording")
    variant_id_input = st.text_input("Variant", value="UHD60-HDR10-H265")
    view_level = st.radio(
        "View Level",
        ["0 - Architecture + Task Topology", "1 - IP Detail DAG", "2 - Drill-Down"],
        index=0,
    )
    level = int(view_level.split(" ", 1)[0])
    expand_options = {
        "Camera pipeline (CSIS + ISP)": "camera",
        "Video encode (MFC)": "video",
        "Display output (DPU)": "display",
    }
    expand_label = st.selectbox("Expand IP (Level 2)", list(expand_options.keys()), index=0)
    expand_id = expand_options[expand_label]


if level == 0:
    arch_view, arch_source = _load_view(api_base, scenario_id_input, variant_id_input, 0, "architecture")
    topo_view, topo_source = _load_view(api_base, scenario_id_input, variant_id_input, 0, "topology")
    primary = arch_view
elif level == 1:
    primary, arch_source = _load_view(api_base, scenario_id_input, variant_id_input, 1)
    topo_view, topo_source = primary, arch_source
else:
    primary, arch_source = _load_view(api_base, scenario_id_input, variant_id_input, 2, expand=expand_id)
    topo_view, topo_source = primary, arch_source

s = primary.summary

st.markdown(
    f"""
<div class="viewer-header">
  <span class="viewer-title">{s.name}</span>
  <span class="meta-chip">{s.subtitle}</span>
  <span class="meta-chip">period {s.period_ms} ms</span>
  <span class="meta-chip">budget {s.budget_ms} ms</span>
  <div style="flex:1"></div>
  <span class="meta-chip">Variant: {s.variant_label} / {s.variant_id}</span>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.divider()
    st.markdown("**Loaded View**")
    st.caption(f"Data source: {arch_source if level != 0 else arch_source + ' / ' + topo_source}")
    if primary.metadata.get("load_error"):
        st.caption(f"API fallback reason: {primary.metadata['load_error']}")
    st.caption(f"Scenario: {primary.scenario_id}")
    st.caption(f"Variant: {primary.variant_id}")
    st.caption(f"Nodes: {len(primary.nodes)} | Edges: {len(primary.edges)}")
    st.caption(f"Risks: {len(primary.risks)}")

main_col, detail_col = st.columns([5.6, 0.95], gap="small")

with detail_col:
    _render_detail_panel(primary)

with main_col:
    st.markdown(
        f"""
<div class="compact-panel">
  <h4>Scenario Summary</h4>
  <span class="meta-chip">Resolution {s.resolution}</span>
  <span class="meta-chip">FPS {s.fps}</span>
  <span class="meta-chip">Mode {primary.mode}</span>
  <span class="meta-chip">Nodes {len(primary.nodes)}</span>
  <span class="meta-chip">Edges {len(primary.edges)}</span>
</div>
""",
        unsafe_allow_html=True,
    )

    if primary.risks:
        risk_html = "".join(
            f'<span class="risk-chip">{risk.severity}: {risk.title}</span>'
            for risk in primary.risks[:4]
        )
        st.markdown(
            f"""<div class="compact-panel"><h4>Risks</h4>{risk_html}</div>""",
            unsafe_allow_html=True,
        )

    if level == 0:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        render_elk_view(
            arch_view,
            canvas_height=820,
            title="Level 0 - Architecture View",
        )
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        render_elk_view(
            topo_view,
            canvas_height=1680,
            title="Level 0 - SW Task Topology View",
        )
        st.markdown("</div>", unsafe_allow_html=True)
    elif level == 1:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        render_elk_view(
            primary,
            canvas_height=1360,
            title="Level 1 - IP Detail DAG",
        )
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        level2_height = int(primary.metadata.get("canvas_h") or 980)
        render_elk_view(
            primary,
            canvas_height=min(max(level2_height, 860), 1320),
            title=f"Level 2 - Drill Down ({expand_label})",
        )
        st.markdown("</div>", unsafe_allow_html=True)
