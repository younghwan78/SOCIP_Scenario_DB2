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
from dashboard.components.level0_detail_panel import scenario_context_description, scenario_context_rows
from dashboard.components.level0_resource_overview import render_level0_resource_overview
from dashboard.components.level2_expand_options import (
    CUSTOM_EXPAND_OPTION,
    build_level2_expand_options,
    custom_level2_expand_default,
    default_level2_expand_value,
    has_concrete_level2_options,
    level2_expand_request_target,
    selected_level2_expand_value,
)
from dashboard.components.viewer_api_client import (
    ViewerApiError,
    compact_project_label,
    compact_scenario_label,
    compact_soc_label,
    compact_variant_label,
    default_variant_id,
    list_projects,
    list_scenarios,
    list_soc_platforms,
    list_variants,
)
from dashboard.components.ui_theme import apply_app_theme
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
  footer, #MainMenu { display: none !important; }
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
apply_app_theme(sidebar_width=288)


@st.cache_data(ttl=30)
def _load_view(
    base_url: str,
    scenario_id: str,
    variant_id: str | None,
    level: int,
    mode: str | None = None,
    expand: str | None = None,
    sim_mode: str = "none",
    sim_evidence_id: str | None = None,
) -> tuple[ViewResponse, str]:
    params: dict[str, object] = {"level": level}
    if mode:
        params["mode"] = mode
    if level == 2 and expand:
        params["expand"] = expand
    if sim_evidence_id:
        params["sim_evidence_id"] = sim_evidence_id
    elif sim_mode == "latest":
        params["sim"] = "latest"
    try:
        if variant_id:
            url = f"{base_url.rstrip('/')}/scenarios/{scenario_id}/variants/{variant_id}/view"
        else:
            url = f"{base_url.rstrip('/')}/scenarios/{scenario_id}/view"
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        return ViewResponse.model_validate(response.json()), "api"
    except Exception as exc:
        fallback = build_sample_level0()
        fallback.metadata["load_error"] = str(exc)
        return fallback, "sample-fallback"


@st.cache_data(ttl=30)
def _load_soc_options(base_url: str) -> tuple[list[dict], str | None]:
    try:
        return list_soc_platforms(base_url), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=30)
def _load_project_options(base_url: str, soc_ref: str | None) -> tuple[list[dict], str | None]:
    try:
        return list_projects(base_url, soc_ref=soc_ref), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=30)
def _load_scenario_options(
    base_url: str,
    project_ref: str | None,
    soc_ref: str | None,
) -> tuple[list[dict], str, str | None]:
    try:
        if project_ref:
            project_items = list_scenarios(base_url, project_ref=project_ref)
            if project_items:
                return project_items, "project", None
        if soc_ref:
            soc_items = list_scenarios(base_url, soc_ref=soc_ref)
            if soc_items:
                return soc_items, "soc", None
        return list_scenarios(base_url), "all", None
    except ViewerApiError as exc:
        return [], "none", str(exc)


@st.cache_data(ttl=30)
def _load_variant_options(base_url: str, scenario_id: str) -> tuple[list[dict], str | None]:
    try:
        return list_variants(base_url, scenario_id), None
    except ViewerApiError as exc:
        return [], str(exc)


def _render_detail_panel(view: ViewResponse) -> None:
    summary = view.summary
    sim_nodes = [
        node.data
        for node in view.nodes
        if node.data.sim_overlay is not None and node.data.type in {"ip", "submodule", "dma_group", "sysmmu"}
    ][:6]
    sim_rows = []
    for data in sim_nodes:
        overlay = data.sim_overlay
        if overlay is None:
            continue
        sim_rows.append(
            f"""<div class="ip-mini-row"><b>{escape(data.label.splitlines()[0])}</b>
            <span>{_fmt(overlay.power_mw, 'mW')} · {_fmt(overlay.set_clock_mhz, 'MHz')} · {_fmt(overlay.hw_time_ms, 'ms')}</span></div>"""
        )
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

    context_rows = "".join(
        f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>"
        for label, value in scenario_context_rows(view)
    )
    html = f"""
<div class="detail-panel">
  <h4>Node / Edge Detail</h4>
  <p>{escape(scenario_context_description(view))}</p>
  <table class="detail-table">
    {context_rows}
  </table>
  <h4>Risks</h4>
  {risks}
  <h4>IP Summary</h4>
  {''.join(ip_rows) if ip_rows else '<p>No IP nodes in current view.</p>'}
  <h4>Simulation Overlay</h4>
  {''.join(sim_rows) if sim_rows else '<p>No simulation overlay loaded.</p>'}
</div>
"""
    st.markdown(html, unsafe_allow_html=True)


def _render_level2_unavailable(view: ViewResponse) -> None:
    reasons = [str(item) for item in view.metadata.get("unavailable_reasons") or []]
    required = [str(item) for item in view.metadata.get("required_data") or []]
    targets = [str(item) for item in view.metadata.get("target_nodes") or []]
    reason_html = "".join(f"<li>{escape(item)}</li>" for item in reasons) or "<li>No reason was provided.</li>"
    required_html = "".join(f"<li>{escape(item)}</li>" for item in required)
    target_text = ", ".join(targets) if targets else "No active target nodes"
    st.markdown(
        f"""
<div class="compact-panel">
  <h4>Level 2 Module View Unavailable</h4>
  <p>Expand target: <b>{escape(str(view.metadata.get("expand") or ""))}</b> · {escape(target_text)}</p>
  <ul>{reason_html}</ul>
  <h4>Required fixture data</h4>
  <ul>{required_html}</ul>
</div>
""",
        unsafe_allow_html=True,
    )


def _stop_on_load_error(
    view: ViewResponse,
    *,
    source: str,
    scenario_id: str,
    variant_id: str | None,
    level: int,
    mode: str | None = None,
    expand: str | None = None,
) -> None:
    load_error = view.metadata.get("load_error")
    if not load_error:
        return
    target = f"{scenario_id}/{variant_id or 'BASE'}"
    details = [f"level={level}"]
    if mode:
        details.append(f"mode={mode}")
    if expand:
        details.append(f"expand={expand}")
    st.error(
        "Requested view failed, so the sample fallback graph was not rendered. "
        f"Target: {target} ({', '.join(details)}). Source: {source}. Error: {load_error}"
    )
    st.stop()


def _state_key_suffix(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "default"


def _fmt(value: float | None, suffix: str) -> str:
    if value is None:
        return "-"
    return f"{value:g}{suffix}"


with st.sidebar:
    st.markdown("### ScenarioDB Viewer")
    query_params = st.query_params
    query_api_base = query_params.get("api_base")
    api_base = st.text_input(
        "API Base",
        value=query_api_base or os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
    )
    if st.button("Refresh scenario list", use_container_width=True):
        _load_soc_options.clear()
        _load_project_options.clear()
        _load_scenario_options.clear()
        _load_variant_options.clear()
        _load_view.clear()
        st.rerun()

    query_soc_id = query_params.get("soc_id")
    query_project_id = query_params.get("project_id")
    query_scenario_id = query_params.get("scenario_id")
    query_variant_id = query_params.get("variant_id")

    socs, soc_error = _load_soc_options(api_base)
    if socs:
        soc_ids = [str(item.get("id")) for item in socs if item.get("id")]
        previous_soc = query_soc_id or st.session_state.get("viewer_soc_id") or (soc_ids[0] if soc_ids else "")
        soc_index = soc_ids.index(previous_soc) if previous_soc in soc_ids else 0
        soc_id_input = st.selectbox(
            "SoC Platform",
            soc_ids,
            index=soc_index,
            format_func=lambda soc_id: compact_soc_label(
                next((item for item in socs if item.get("id") == soc_id), {"id": soc_id})
            ),
        )
        st.session_state["viewer_soc_id"] = soc_id_input
    else:
        if soc_error:
            st.caption(f"SoC list unavailable: {soc_error}")
        soc_id_input = st.text_input("SoC Platform", value=query_soc_id or st.session_state.get("viewer_soc_id", ""))
        st.session_state["viewer_soc_id"] = soc_id_input

    projects, project_error = _load_project_options(api_base, soc_id_input or None)
    if projects:
        project_ids = [str(item.get("id")) for item in projects if item.get("id")]
        previous_project = query_project_id or st.session_state.get("viewer_project_id") or (project_ids[0] if project_ids else "")
        project_index = project_ids.index(previous_project) if previous_project in project_ids else 0
        project_id_input = st.selectbox(
            "Project / Board",
            project_ids,
            index=project_index,
            format_func=lambda project_id: compact_project_label(
                next((item for item in projects if item.get("id") == project_id), {"id": project_id})
            ),
        )
        st.session_state["viewer_project_id"] = project_id_input
    else:
        if project_error:
            st.caption(f"Project list unavailable: {project_error}")
        project_id_input = st.text_input("Project / Board", value=query_project_id or st.session_state.get("viewer_project_id", ""))
        st.session_state["viewer_project_id"] = project_id_input

    scenarios, scenario_scope, scenario_error = _load_scenario_options(api_base, project_id_input or None, soc_id_input or None)
    if scenarios:
        scenario_ids = [str(item.get("id")) for item in scenarios if item.get("id")]
        previous_scenario = query_scenario_id or st.session_state.get("viewer_scenario_id", "uc-camera-recording")
        scenario_index = scenario_ids.index(previous_scenario) if previous_scenario in scenario_ids else 0
        scenario_id_input = st.selectbox(
            "Scenario",
            scenario_ids,
            index=scenario_index,
            format_func=lambda scenario_id: compact_scenario_label(
                next((item for item in scenarios if item.get("id") == scenario_id), {"id": scenario_id})
            ),
        )
        st.session_state["viewer_scenario_id"] = scenario_id_input
        if scenario_scope == "soc":
            st.caption("Selected project has no scenarios. Showing scenarios for selected SoC.")
        elif scenario_scope == "all":
            st.caption("Selected project/SoC has no scenarios. Showing all scenarios.")
    else:
        if scenario_error:
            st.caption(f"Scenario list unavailable: {scenario_error}")
        st.error("No scenarios are available from the API.")
        st.stop()

    variants, variant_error = _load_variant_options(api_base, scenario_id_input) if scenario_id_input else ([], None)
    if variants:
        variant_ids = [str(item.get("id")) for item in variants if item.get("id")]
        selected_variant = default_variant_id(variants, query_variant_id or st.session_state.get("viewer_variant_id", "UHD60-HDR10-H265"))
        variant_index = variant_ids.index(selected_variant) if selected_variant in variant_ids else 0
        variant_id_input = st.selectbox(
            "Variant",
            variant_ids,
            index=variant_index,
            format_func=lambda variant_id: compact_variant_label(
                next((item for item in variants if item.get("id") == variant_id), {"id": variant_id})
            ),
        )
        st.session_state["viewer_variant_id"] = variant_id_input
    else:
        if variant_error:
            st.caption(f"Variant list unavailable: {variant_error}")
        st.info("No variants found for this scenario. Viewer will load the base scenario pipeline.")
        variant_id_input = ""
        st.session_state["viewer_variant_id"] = variant_id_input

    view_level = st.radio(
        "View Level",
        ["0 - Resource + Topology", "1 - IP Detail DAG", "2 - Drill-Down"],
        index=0,
    )
    level = int(view_level.split(" ", 1)[0])
    expand_label = ""
    expand_id = ""
    current_expand_context = f"{scenario_id_input}/{variant_id_input or 'BASE'}"
    if level == 2:
        level1_for_options, option_source = _load_view(
            api_base,
            scenario_id_input,
            variant_id_input,
            1,
            sim_mode="none",
        )
        level2_options = build_level2_expand_options(level1_for_options)
        if option_source != "api":
            _stop_on_load_error(
                level1_for_options,
                source=option_source,
                scenario_id=scenario_id_input,
                variant_id=variant_id_input,
                level=1,
            )
        current_expand_context = f"{scenario_id_input}/{variant_id_input or 'BASE'}"
        previous_expand = selected_level2_expand_value(
            level2_options,
            previous_value=st.session_state.get("viewer_level2_expand_value") or default_level2_expand_value(level2_options),
            previous_context=st.session_state.get("viewer_level2_expand_context"),
            current_context=current_expand_context,
        )
        option_values = [option.value for option in level2_options]
        option_index = option_values.index(previous_expand) if previous_expand in option_values else 0
        selected_expand_option = st.selectbox(
            "Expand IP (Level 2)",
            level2_options,
            index=option_index,
            format_func=lambda option: option.label,
        )
        expand_label = selected_expand_option.label
        expand_id = selected_expand_option.value
        if option_source != "api":
            st.caption(f"Level 2 options loaded from {option_source}.")
        if not has_concrete_level2_options(level2_options):
            st.caption("No active Level 2 module candidate was found for this scenario. Use a custom node/IP id only if module data exists.")
    if expand_id == CUSTOM_EXPAND_OPTION.value:
        selected_expand_value = expand_id
        custom_default = custom_level2_expand_default(
            previous_value=st.session_state.get("viewer_level2_custom_expand"),
            previous_context=st.session_state.get("viewer_level2_custom_expand_context"),
            current_context=current_expand_context,
        )
        custom_expand = st.text_input(
            "Custom expand id",
            value=custom_default,
            key=f"viewer_level2_custom_expand_input_{_state_key_suffix(current_expand_context)}",
            help="Use an active pipeline node id such as csispdp, gpu, dpu, or an IP catalog id.",
        ).strip()
        expand_id = level2_expand_request_target(selected_expand_value, custom_expand) or ""
        st.session_state["viewer_level2_custom_expand"] = custom_expand
        st.session_state["viewer_level2_custom_expand_context"] = current_expand_context
    if level == 2 and expand_id:
        st.session_state["viewer_level2_expand_value"] = (
            CUSTOM_EXPAND_OPTION.value if expand_label == CUSTOM_EXPAND_OPTION.label else expand_id
        )
        st.session_state["viewer_level2_expand_context"] = f"{scenario_id_input}/{variant_id_input or 'BASE'}"

    st.divider()
    st.markdown("**Simulation Overlay**")
    query_sim = query_params.get("sim")
    query_sim_evidence_id = query_params.get("sim_evidence_id")
    previous_sim_mode = st.session_state.get("viewer_sim_mode") or ("specific" if query_sim_evidence_id else query_sim or "none")
    sim_options = {
        "none": "None",
        "latest": "Latest Evidence",
        "specific": "Specific Evidence ID",
    }
    sim_mode = st.selectbox(
        "Overlay Source",
        list(sim_options.keys()),
        index=list(sim_options.keys()).index(previous_sim_mode) if previous_sim_mode in sim_options else 0,
        format_func=lambda value: sim_options[value],
    )
    st.session_state["viewer_sim_mode"] = sim_mode
    sim_evidence_id = ""
    if sim_mode == "specific":
        sim_evidence_id = st.text_input(
            "Simulation Evidence ID",
            value=query_sim_evidence_id or st.session_state.get("viewer_sim_evidence_id", ""),
        )
        st.session_state["viewer_sim_evidence_id"] = sim_evidence_id

overlay_evidence_id = sim_evidence_id if sim_mode == "specific" and sim_evidence_id else None

if level == 2 and not expand_id:
    st.info(
        "No Level 2 expand target is selected for this scenario. "
        "This usually means the active graph has no declared module-level HW candidate. "
        "Select another view level or type a custom node/IP id when fixture module data exists."
    )
    st.stop()

if level == 0:
    resource_view, resource_source = _load_view(
        api_base,
        scenario_id_input,
        variant_id_input,
        0,
        "resource",
        sim_mode=sim_mode,
        sim_evidence_id=overlay_evidence_id,
    )
    topo_view, topo_source = _load_view(
        api_base,
        scenario_id_input,
        variant_id_input,
        0,
        "topology",
        sim_mode=sim_mode,
        sim_evidence_id=overlay_evidence_id,
    )
    primary = resource_view
    _stop_on_load_error(
        resource_view,
        source=resource_source,
        scenario_id=scenario_id_input,
        variant_id=variant_id_input,
        level=0,
        mode="resource",
    )
    _stop_on_load_error(
        topo_view,
        source=topo_source,
        scenario_id=scenario_id_input,
        variant_id=variant_id_input,
        level=0,
        mode="topology",
    )
elif level == 1:
    primary, arch_source = _load_view(
        api_base,
        scenario_id_input,
        variant_id_input,
        1,
        sim_mode=sim_mode,
        sim_evidence_id=overlay_evidence_id,
    )
    topo_view, topo_source = primary, arch_source
    _stop_on_load_error(
        primary,
        source=arch_source,
        scenario_id=scenario_id_input,
        variant_id=variant_id_input,
        level=1,
    )
else:
    primary, arch_source = _load_view(
        api_base,
        scenario_id_input,
        variant_id_input,
        2,
        expand=expand_id,
        sim_mode=sim_mode,
        sim_evidence_id=overlay_evidence_id,
    )
    topo_view, topo_source = primary, arch_source
    _stop_on_load_error(
        primary,
        source=arch_source,
        scenario_id=scenario_id_input,
        variant_id=variant_id_input,
        level=2,
        expand=expand_id,
    )

s = primary.summary
graph_node_count = len(topo_view.nodes) if level == 0 else len(primary.nodes)
graph_edge_count = len(topo_view.edges) if level == 0 else len(primary.edges)
mode_label = "resource + topology" if level == 0 else str(primary.mode)

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
    st.caption(f"Data source: {arch_source if level != 0 else resource_source + ' / ' + topo_source}")
    if primary.metadata.get("load_error"):
        st.caption(f"API fallback reason: {primary.metadata['load_error']}")
    st.caption(f"Scenario: {primary.scenario_id}")
    st.caption(f"Variant: {primary.variant_id}")
    st.caption(f"Nodes: {graph_node_count} | Edges: {graph_edge_count}")
    st.caption(f"Risks: {len(primary.risks)}")
    if "simulation" in primary.overlays_available:
        st.caption("Overlay: simulation")

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
  <span class="meta-chip">Mode {mode_label}</span>
  <span class="meta-chip">Nodes {graph_node_count}</span>
  <span class="meta-chip">Edges {graph_edge_count}</span>
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
        render_level0_resource_overview(resource_view)

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        render_elk_view(
            topo_view,
            canvas_height=1280,
            title="Level 0 - Topology Overview",
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
        if primary.metadata.get("level2_available") is False:
            _render_level2_unavailable(primary)
        else:
            title_expand = expand_label if expand_label != "Custom node/IP id" else expand_id
            render_elk_view(
                primary,
                canvas_height=min(max(level2_height, 860), 1320),
                title=f"Level 2 - Drill Down ({title_expand})",
            )
        st.markdown("</div>", unsafe_allow_html=True)
