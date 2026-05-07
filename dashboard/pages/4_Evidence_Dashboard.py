r"""Simulation evidence dashboard for ScenarioDB.

Run from the project virtual environment:
  .\.venv\Scripts\python.exe -m streamlit run dashboard/Home.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st

_root = Path(__file__).resolve().parents[2]
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.components.simulation_api_client import list_simulation_results, run_simulation
from dashboard.components.viewer_api_client import (
    ViewerApiError,
    default_variant_id,
    list_projects,
    list_scenarios,
    list_soc_platforms,
    list_variants,
    project_label,
    scenario_label,
    soc_label,
    variant_label,
)


st.set_page_config(
    page_title="Evidence Dashboard - ScenarioDB",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  .block-container { padding-top: 0.6rem !important; max-width: none !important; }
  header[data-testid="stHeader"], footer, #MainMenu { display: none !important; }
  .metric-row {
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 10px 12px;
    background: #FFFFFF;
  }
  .metric-row b { font-size: 13px; color: #111827; }
  .metric-row span { font-size: 12px; color: #64748B; }
</style>
""",
    unsafe_allow_html=True,
)


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
) -> tuple[list[dict], str | None]:
    try:
        if project_ref:
            items = list_scenarios(base_url, project_ref=project_ref)
            if items:
                return items, None
        if soc_ref:
            items = list_scenarios(base_url, soc_ref=soc_ref)
            if items:
                return items, None
        return list_scenarios(base_url), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=30)
def _load_variant_options(base_url: str, scenario_id: str) -> tuple[list[dict], str | None]:
    try:
        return list_variants(base_url, scenario_id), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=20)
def _load_sim_results(
    base_url: str,
    scenario_id: str,
    variant_id: str,
    latest: bool,
) -> tuple[list[dict], str | None]:
    try:
        return (
            list_simulation_results(
                base_url,
                scenario_ref=scenario_id or None,
                variant_ref=variant_id or None,
                latest=latest,
                limit=100,
            ),
            None,
        )
    except ViewerApiError as exc:
        return [], str(exc)


def _select_context(api_base: str) -> tuple[str, str]:
    socs, soc_error = _load_soc_options(api_base)
    if socs:
        soc_ids = [str(item.get("id")) for item in socs if item.get("id")]
        soc_id = st.selectbox(
            "SoC Platform",
            soc_ids,
            format_func=lambda value: soc_label(next((item for item in socs if item.get("id") == value), {"id": value})),
        )
    else:
        if soc_error:
            st.caption(f"SoC list unavailable: {soc_error}")
        soc_id = st.text_input("SoC Platform", value=st.session_state.get("viewer_soc_id", ""))
    st.session_state["viewer_soc_id"] = soc_id

    projects, project_error = _load_project_options(api_base, soc_id or None)
    if projects:
        project_ids = [str(item.get("id")) for item in projects if item.get("id")]
        project_id = st.selectbox(
            "Project / Board",
            project_ids,
            format_func=lambda value: project_label(
                next((item for item in projects if item.get("id") == value), {"id": value})
            ),
        )
    else:
        if project_error:
            st.caption(f"Project list unavailable: {project_error}")
        project_id = st.text_input("Project / Board", value=st.session_state.get("viewer_project_id", ""))
    st.session_state["viewer_project_id"] = project_id

    scenarios, scenario_error = _load_scenario_options(api_base, project_id or None, soc_id or None)
    if not scenarios:
        if scenario_error:
            st.error(f"Scenario list unavailable: {scenario_error}")
        else:
            st.error("No scenarios are available from the API.")
        st.stop()
    scenario_ids = [str(item.get("id")) for item in scenarios if item.get("id")]
    previous_scenario = st.session_state.get("viewer_scenario_id", "uc-camera-recording")
    scenario_index = scenario_ids.index(previous_scenario) if previous_scenario in scenario_ids else 0
    scenario_id = st.selectbox(
        "Scenario",
        scenario_ids,
        index=scenario_index,
        format_func=lambda value: scenario_label(next((item for item in scenarios if item.get("id") == value), {"id": value})),
    )
    st.session_state["viewer_scenario_id"] = scenario_id

    variants, variant_error = _load_variant_options(api_base, scenario_id)
    if not variants:
        if variant_error:
            st.error(f"Variant list unavailable: {variant_error}")
        else:
            st.error("No variants found for this scenario.")
        st.stop()
    variant_ids = [str(item.get("id")) for item in variants if item.get("id")]
    selected_variant = default_variant_id(variants, st.session_state.get("viewer_variant_id", "UHD60-HDR10-H265"))
    variant_index = variant_ids.index(selected_variant) if selected_variant in variant_ids else 0
    variant_id = st.selectbox(
        "Variant",
        variant_ids,
        index=variant_index,
        format_func=lambda value: variant_label(next((item for item in variants if item.get("id") == value), {"id": value})),
    )
    st.session_state["viewer_variant_id"] = variant_id
    return scenario_id, variant_id


def _result_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in results:
        kpi = item.get("kpi") if isinstance(item.get("kpi"), dict) else {}
        run_info = item.get("run_info") if isinstance(item.get("run_info"), dict) else {}
        rows.append(
            {
                "id": item.get("id"),
                "feasibility": item.get("overall_feasibility"),
                "power_mw": _round(_kpi(kpi, "total_power_mw", "power_mw")),
                "power_ma": _round(_kpi(kpi, "total_power_ma", "power_ma")),
                "bw_mbs": _round(_kpi(kpi, "total_bw_mbs", "bw_mbs")),
                "hw_time_ms": _round(_kpi(kpi, "hw_time_max_ms", "hw_time_ms")),
                "timeline_end_ms": _round(kpi.get("timeline_end_ms")),
                "timestamp": run_info.get("timestamp"),
                "params_hash": item.get("params_hash"),
            }
        )
    return rows


def _kpi(kpi: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in kpi:
            return kpi[key]
    return None


def _round(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _render_breakdown(result: dict[str, Any]) -> None:
    tabs = st.tabs(["IP Power", "DMA BW", "Timing", "Timeline", "Raw Evidence"])
    with tabs[0]:
        st.dataframe(result.get("ip_breakdown") or [], use_container_width=True, hide_index=True)
    with tabs[1]:
        st.dataframe(result.get("dma_breakdown") or [], use_container_width=True, hide_index=True)
    with tabs[2]:
        st.dataframe(result.get("timing_breakdown") or [], use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(result.get("timeline_events") or [], use_container_width=True, hide_index=True)
    with tabs[4]:
        st.json(result)


st.title("Evidence Dashboard")
st.caption("Run scenario/variant simulation, persist simulation evidence, and inspect KPI breakdowns.")

with st.sidebar:
    st.markdown("### Simulation Context")
    api_base = st.text_input(
        "API Base",
        value=os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
    )
    if st.button("Refresh", use_container_width=True):
        _load_soc_options.clear()
        _load_project_options.clear()
        _load_scenario_options.clear()
        _load_variant_options.clear()
        _load_sim_results.clear()
        st.rerun()
    scenario_id, variant_id = _select_context(api_base)

run_col, result_col = st.columns([0.9, 1.6], gap="large")

with run_col:
    st.subheader("Run Simulation")
    with st.form("run-simulation"):
        silicon_rev = st.text_input("Silicon Rev", value="A0")
        sw_baseline_ref = st.text_input("SW Baseline", value="sw-vendor-v1.2.3")
        thermal = st.selectbox("Thermal", ["nominal", "hot", "cold"], index=0)
        asv_group = st.number_input("ASV Group", min_value=0, max_value=8, value=4, step=1)
        fps_value = st.text_input("FPS Override", value="")
        include_timeline = st.checkbox("Include timing timeline", value=True)
        force = st.checkbox("Force recompute", value=False)
        persist = st.checkbox("Persist evidence", value=True)
        dvfs_json = st.text_area("DVFS Tables JSON", value="{}", height=104)
        submitted = st.form_submit_button("Run Simulation", type="primary", use_container_width=True)

    if submitted:
        try:
            dvfs_tables = json.loads(dvfs_json or "{}")
            fps = float(fps_value) if fps_value.strip() else None
            payload = {
                "scenario_id": scenario_id,
                "variant_id": variant_id,
                "execution_context": {
                    "silicon_rev": silicon_rev,
                    "sw_baseline_ref": sw_baseline_ref,
                    "thermal": thermal,
                },
                "config": {
                    "asv_group": asv_group,
                    "fps": fps,
                    "include_timeline": include_timeline,
                },
                "dvfs_tables": dvfs_tables,
                "persist": persist,
                "force": force,
            }
            response = run_simulation(api_base, payload)
            _load_sim_results.clear()
            evidence_id = str(response.get("evidence_id") or "")
            st.session_state["viewer_sim_mode"] = "specific"
            st.session_state["viewer_sim_evidence_id"] = evidence_id
            st.success(f"Simulation completed: {evidence_id}")
            for warning in response.get("warnings") or []:
                st.warning(str(warning))
            st.json({key: response.get(key) for key in ("cached", "params_hash", "kpi")})
        except json.JSONDecodeError as exc:
            st.error(f"DVFS JSON is invalid: {exc}")
        except ViewerApiError as exc:
            st.error(str(exc))
            if exc.body:
                st.code(exc.body)
        except ValueError as exc:
            st.error(str(exc))

with result_col:
    st.subheader("Simulation Results")
    latest_only = st.toggle("Latest result only", value=False)
    results, results_error = _load_sim_results(api_base, scenario_id, variant_id, latest_only)
    if results_error:
        st.error(results_error)
    elif not results:
        st.info("No simulation evidence is stored for the selected scenario/variant.")
    else:
        rows = _result_rows(results)
        st.dataframe(rows, use_container_width=True, hide_index=True)
        selected_id = st.selectbox("Selected Evidence", [str(row["id"]) for row in rows if row.get("id")])
        selected = next((item for item in results if item.get("id") == selected_id), results[0])
        kpi = selected.get("kpi") if isinstance(selected.get("kpi"), dict) else {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Power", f"{_round(_kpi(kpi, 'total_power_mw', 'power_mw')) or 0:g} mW")
        c2.metric("Current", f"{_round(_kpi(kpi, 'total_power_ma', 'power_ma')) or 0:g} mA")
        c3.metric("Bandwidth", f"{_round(_kpi(kpi, 'total_bw_mbs', 'bw_mbs')) or 0:g} MB/s")
        c4.metric("HW Time", f"{_round(_kpi(kpi, 'hw_time_max_ms', 'hw_time_ms')) or 0:g} ms")
        if st.button("Open Pipeline Viewer Overlay", use_container_width=True):
            st.session_state["viewer_sim_mode"] = "specific"
            st.session_state["viewer_sim_evidence_id"] = selected_id
            st.switch_page("pages/2_Pipeline_Viewer.py")
        _render_breakdown(selected)
