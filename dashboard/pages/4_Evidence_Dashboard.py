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
from urllib.parse import urlencode

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
    list_sw_profiles,
    list_variants,
    project_label,
    scenario_label,
    soc_label,
    sw_profile_label,
    variant_label,
)

THERMAL_PRESETS = {
    "normal": {"label": "normal (~25C ambient)", "ambient_temp_c": 25.0, "note": "Room-temperature baseline."},
    "hot": {"label": "hot (~85C chamber)", "ambient_temp_c": 85.0, "note": "Thermal stress / throttling-risk condition."},
    "cold": {"label": "cold (~-20C chamber)", "ambient_temp_c": -20.0, "note": "Cold-start validation condition."},
}

SILICON_REVS = ["A0", "A1", "B0", "B1", "C0"]

DEFAULT_DVFS_TABLES = {
    "CSIS": {
        "domain": "CSIS",
        "levels": [
            {"level": 0, "speed_mhz": 800, "voltages": {"4": 800}},
            {"level": 2, "speed_mhz": 533, "voltages": {"4": 675}},
            {"level": 4, "speed_mhz": 332, "voltages": {"4": 606.25}},
            {"level": 7, "speed_mhz": 133, "voltages": {"4": 562.5}},
        ],
    },
    "CAM": {
        "domain": "CAM",
        "levels": [
            {"level": 0, "speed_mhz": 800, "voltages": {"4": 800}},
            {"level": 2, "speed_mhz": 533, "voltages": {"4": 675}},
            {"level": 4, "speed_mhz": 332, "voltages": {"4": 606.25}},
            {"level": 7, "speed_mhz": 133, "voltages": {"4": 562.5}},
        ],
    },
    "INTCAM": {
        "domain": "INTCAM",
        "levels": [
            {"level": 0, "speed_mhz": 800, "voltages": {"4": 800}},
            {"level": 2, "speed_mhz": 533, "voltages": {"4": 675}},
            {"level": 4, "speed_mhz": 332, "voltages": {"4": 606.25}},
            {"level": 7, "speed_mhz": 133, "voltages": {"4": 562.5}},
        ],
    },
    "INT": {
        "domain": "INT",
        "levels": [
            {"level": 0, "speed_mhz": 800, "voltages": {"4": 800}},
            {"level": 2, "speed_mhz": 533, "voltages": {"4": 675}},
            {"level": 4, "speed_mhz": 332, "voltages": {"4": 606.25}},
            {"level": 7, "speed_mhz": 133, "voltages": {"4": 562.5}},
        ],
    },
}


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
  .viewer-tab-link {
    display: block;
    width: 100%;
    box-sizing: border-box;
    border: 1px solid #D1D5DB;
    border-radius: 7px;
    background: #FFFFFF;
    color: #374151 !important;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.4;
    padding: 9px 12px;
    text-align: center;
    text-decoration: none !important;
  }
  .viewer-tab-link:hover {
    border-color: #9CA3AF;
    background: #F9FAFB;
    color: #111827 !important;
  }
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


@st.cache_data(ttl=30)
def _load_sw_profile_options(base_url: str) -> tuple[list[dict], str | None]:
    try:
        return list_sw_profiles(base_url), None
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
        _ensure_choice("evidence_soc_id", soc_ids, preferred=st.session_state.get("viewer_soc_id"))
        st.selectbox(
            "SoC Platform",
            soc_ids,
            key="evidence_soc_id",
            on_change=_clear_context_after_soc,
            format_func=lambda value: soc_label(next((item for item in socs if item.get("id") == value), {"id": value})),
        )
        soc_id = st.session_state["evidence_soc_id"]
    else:
        if soc_error:
            st.caption(f"SoC list unavailable: {soc_error}")
        soc_id = st.text_input("SoC Platform", key="evidence_soc_id_text", value=st.session_state.get("viewer_soc_id", ""))
    st.session_state["viewer_soc_id"] = soc_id

    projects, project_error = _load_project_options(api_base, soc_id or None)
    if projects:
        project_ids = [str(item.get("id")) for item in projects if item.get("id")]
        _ensure_choice("evidence_project_id", project_ids, preferred=st.session_state.get("viewer_project_id"))
        st.selectbox(
            "Project / Board",
            project_ids,
            key="evidence_project_id",
            on_change=_clear_context_after_project,
            format_func=lambda value: project_label(
                next((item for item in projects if item.get("id") == value), {"id": value})
            ),
        )
        project_id = st.session_state["evidence_project_id"]
    else:
        if project_error:
            st.caption(f"Project list unavailable: {project_error}")
        project_id = st.text_input("Project / Board", key="evidence_project_id_text", value=st.session_state.get("viewer_project_id", ""))
    st.session_state["viewer_project_id"] = project_id

    scenarios, scenario_error = _load_scenario_options(api_base, project_id or None, soc_id or None)
    if not scenarios:
        if scenario_error:
            st.error(f"Scenario list unavailable: {scenario_error}")
        else:
            st.error("No scenarios are available from the API.")
        st.stop()
    categories = _scenario_categories(scenarios)
    _ensure_choice("evidence_scenario_category", categories, preferred=st.session_state.get("evidence_scenario_category", "all"))
    st.selectbox(
        "Scenario Category",
        categories,
        key="evidence_scenario_category",
        on_change=_clear_context_after_category,
        format_func=lambda value: "All categories" if value == "all" else value,
    )
    filtered_scenarios = _filter_scenarios_by_category(scenarios, st.session_state["evidence_scenario_category"])

    scenario_ids = [str(item.get("id")) for item in filtered_scenarios if item.get("id")]
    _ensure_choice("evidence_scenario_id", scenario_ids, preferred=st.session_state.get("viewer_scenario_id", "uc-camera-recording"))
    st.selectbox(
        "Scenario",
        scenario_ids,
        key="evidence_scenario_id",
        on_change=_clear_context_after_scenario,
        format_func=lambda value: scenario_label(next((item for item in filtered_scenarios if item.get("id") == value), {"id": value})),
    )
    scenario_id = st.session_state["evidence_scenario_id"]
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
    _ensure_choice("evidence_variant_id", variant_ids, preferred=selected_variant)
    st.selectbox(
        "Variant",
        variant_ids,
        key="evidence_variant_id",
        on_change=_clear_context_after_variant,
        format_func=lambda value: variant_label(next((item for item in variants if item.get("id") == value), {"id": value})),
    )
    variant_id = st.session_state["evidence_variant_id"]
    st.session_state["viewer_variant_id"] = variant_id
    return scenario_id, variant_id


def _ensure_choice(key: str, options: list[str], *, preferred: str | None = None) -> None:
    if not options:
        return
    if st.session_state.get(key) not in options:
        st.session_state[key] = preferred if preferred in options else options[0]


def _clear_context_after_soc() -> None:
    for key in ("evidence_project_id", "evidence_scenario_category", "evidence_scenario_id", "evidence_variant_id", "evidence_selected_evidence_id"):
        st.session_state.pop(key, None)


def _clear_context_after_project() -> None:
    for key in ("evidence_scenario_category", "evidence_scenario_id", "evidence_variant_id", "evidence_selected_evidence_id"):
        st.session_state.pop(key, None)


def _clear_context_after_category() -> None:
    for key in ("evidence_scenario_id", "evidence_variant_id", "evidence_selected_evidence_id"):
        st.session_state.pop(key, None)


def _clear_context_after_scenario() -> None:
    for key in ("evidence_variant_id", "evidence_selected_evidence_id"):
        st.session_state.pop(key, None)


def _clear_context_after_variant() -> None:
    st.session_state.pop("evidence_selected_evidence_id", None)


def _scenario_categories(scenarios: list[dict[str, Any]]) -> list[str]:
    categories = {"all"}
    for item in scenarios:
        metadata = item.get("metadata_") if isinstance(item.get("metadata_"), dict) else item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        for key in ("category", "domain"):
            value = metadata.get(key)
            if isinstance(value, list):
                categories.update(str(part) for part in value if part)
            elif value:
                categories.add(str(value))
    return ["all", *sorted(category for category in categories if category != "all")]


def _filter_scenarios_by_category(scenarios: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    if category == "all":
        return scenarios
    filtered = []
    for item in scenarios:
        metadata = item.get("metadata_") if isinstance(item.get("metadata_"), dict) else item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        values: list[str] = []
        for key in ("category", "domain"):
            value = metadata.get(key)
            if isinstance(value, list):
                values.extend(str(part) for part in value)
            elif value:
                values.append(str(value))
        if category in values:
            filtered.append(item)
    return filtered


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


def _ordered_table(rows: list[dict[str, Any]], priority: list[str]) -> list[dict[str, Any]]:
    ordered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out = {key: row.get(key) for key in priority if key in row}
        for key, value in row.items():
            if key not in out:
                out[key] = value
        ordered.append(out)
    return ordered


def _pipeline_viewer_url(api_base: str, scenario_id: str, variant_id: str, evidence_id: str) -> str:
    query = {
        "api_base": api_base,
        "soc_id": st.session_state.get("evidence_soc_id") or st.session_state.get("viewer_soc_id"),
        "project_id": st.session_state.get("evidence_project_id") or st.session_state.get("viewer_project_id"),
        "scenario_id": scenario_id,
        "variant_id": variant_id,
        "sim_evidence_id": evidence_id,
    }
    clean = {key: value for key, value in query.items() if value not in (None, "")}
    return f"/Pipeline_Viewer?{urlencode(clean)}"


def _render_viewer_tab_link(api_base: str, scenario_id: str, variant_id: str, evidence_id: str) -> None:
    href = _pipeline_viewer_url(api_base, scenario_id, variant_id, evidence_id)
    st.markdown(
        f"""
<a class="viewer-tab-link" href="{href}" target="_blank" rel="noopener noreferrer">
  Open Pipeline Viewer Overlay
</a>
""",
        unsafe_allow_html=True,
    )


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
        st.dataframe(
            _ordered_table(
                result.get("dma_breakdown") or [],
                [
                    "node_id",
                    "port",
                    "direction",
                    "bw_mbs",
                    "bw_power_mw",
                    "bw_power_ma",
                    "width",
                    "height",
                    "size_mp",
                    "format",
                    "bitwidth",
                    "compression",
                    "llc_enabled",
                ],
            ),
            use_container_width=True,
            hide_index=True,
        )
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
        key="evidence_api_base",
    )
    if st.button("Refresh", use_container_width=True):
        _load_soc_options.clear()
        _load_project_options.clear()
        _load_scenario_options.clear()
        _load_variant_options.clear()
        _load_sw_profile_options.clear()
        _load_sim_results.clear()
        st.rerun()
    scenario_id, variant_id = _select_context(api_base)

run_col, result_col = st.columns([0.9, 1.6], gap="large")

with run_col:
    st.subheader("Run Simulation")
    with st.form("run-simulation"):
        silicon_rev = st.selectbox("Silicon Rev", SILICON_REVS, key="evidence_silicon_rev")
        sw_profiles, sw_error = _load_sw_profile_options(api_base)
        if sw_profiles:
            sw_ids = [str(item.get("id")) for item in sw_profiles if item.get("id")]
            _ensure_choice("evidence_sw_baseline_ref", sw_ids, preferred="sw-vendor-v1.2.3")
            sw_baseline_ref = st.selectbox(
                "SW Baseline",
                sw_ids,
                key="evidence_sw_baseline_ref",
                format_func=lambda value: sw_profile_label(
                    next((item for item in sw_profiles if item.get("id") == value), {"id": value})
                ),
            )
        else:
            if sw_error:
                st.caption(f"SW profile list unavailable: {sw_error}")
            sw_baseline_ref = st.text_input("SW Baseline", key="evidence_sw_baseline_ref_text", value="sw-vendor-v1.2.3")
        thermal = st.selectbox(
            "Thermal",
            list(THERMAL_PRESETS),
            key="evidence_thermal",
            format_func=lambda value: THERMAL_PRESETS[value]["label"],
            help="normal/hot/cold are execution-context buckets. The ambient temperature value is also sent in execution_context.",
        )
        st.caption(THERMAL_PRESETS[thermal]["note"])
        asv_group = st.number_input("ASV Group", min_value=0, max_value=8, value=4, step=1, key="evidence_asv_group")
        fps_value = st.text_input("FPS Override", value="", key="evidence_fps_override")
        include_timeline = st.checkbox("Include timing timeline", value=True, key="evidence_include_timeline")
        force = st.checkbox("Force recompute", value=False, key="evidence_force_recompute")
        persist = st.checkbox("Persist evidence", value=True, key="evidence_persist")
        default_dvfs_json = json.dumps(DEFAULT_DVFS_TABLES, indent=2)
        if "evidence_dvfs_json" not in st.session_state:
            st.session_state["evidence_dvfs_json"] = default_dvfs_json
        dvfs_json = st.text_area(
            "DVFS Tables JSON",
            key="evidence_dvfs_json",
            height=220,
            help="Schema: domain -> {domain, levels:[{level, speed_mhz, voltages:{asv_group: millivolts}}]}. Keys must match IP dvfs_group values such as CAM, CSIS, INTCAM, INT.",
        )
        with st.expander("DVFS JSON help", expanded=False):
            st.markdown(
                "`speed_mhz` is the available DVFS clock. `voltages` maps ASV group to mV. "
                "If a domain is omitted, simulation falls back to the reference voltage for power calculation."
            )
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
                    "ambient_temp_c": THERMAL_PRESETS[thermal]["ambient_temp_c"],
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
            st.session_state["evidence_selected_evidence_id"] = evidence_id
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
    latest_only = st.toggle("Latest result only", value=False, key="evidence_latest_only")
    results, results_error = _load_sim_results(api_base, scenario_id, variant_id, latest_only)
    if results_error:
        st.error(results_error)
    elif not results:
        st.info("No simulation evidence is stored for the selected scenario/variant.")
    else:
        rows = _result_rows(results)
        st.dataframe(rows, use_container_width=True, hide_index=True)
        evidence_ids = [str(row["id"]) for row in rows if row.get("id")]
        _ensure_choice("evidence_selected_evidence_id", evidence_ids)
        selected_id = st.selectbox("Selected Evidence", evidence_ids, key="evidence_selected_evidence_id")
        selected = next((item for item in results if item.get("id") == selected_id), results[0])
        kpi = selected.get("kpi") if isinstance(selected.get("kpi"), dict) else {}
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Power", f"{_round(_kpi(kpi, 'total_power_mw', 'power_mw')) or 0:g} mW")
        c2.metric("Current", f"{_round(_kpi(kpi, 'total_power_ma', 'power_ma')) or 0:g} mA")
        c3.metric("Bandwidth", f"{_round(_kpi(kpi, 'total_bw_mbs', 'bw_mbs')) or 0:g} MB/s")
        c4.metric("HW Time", f"{_round(_kpi(kpi, 'hw_time_max_ms', 'hw_time_ms')) or 0:g} ms")
        _render_viewer_tab_link(api_base, scenario_id, variant_id, selected_id)
        _render_breakdown(selected)
