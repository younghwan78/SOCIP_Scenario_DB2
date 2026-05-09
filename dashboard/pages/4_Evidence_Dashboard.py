r"""Simulation evidence dashboard for ScenarioDB.

Run from the project virtual environment:
  .\.venv\Scripts\python.exe -m streamlit run dashboard/Home.py
"""
from __future__ import annotations

import csv
import io
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

from dashboard.components.simulation_api_client import delete_simulation_result, list_simulation_results, run_simulation
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

SILICON_REVS = ["EVT0", "EVT1", "EVT1.3", "Custom"]

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
    for key in ("evidence_project_id", "evidence_scenario_category", "evidence_scenario_id", "evidence_variant_id", "evidence_selected_evidence_id", "evidence_preview_result", "evidence_preview_payload"):
        st.session_state.pop(key, None)


def _clear_context_after_project() -> None:
    for key in ("evidence_scenario_category", "evidence_scenario_id", "evidence_variant_id", "evidence_selected_evidence_id", "evidence_preview_result", "evidence_preview_payload"):
        st.session_state.pop(key, None)


def _clear_context_after_category() -> None:
    for key in ("evidence_scenario_id", "evidence_variant_id", "evidence_selected_evidence_id", "evidence_preview_result", "evidence_preview_payload"):
        st.session_state.pop(key, None)


def _clear_context_after_scenario() -> None:
    for key in ("evidence_variant_id", "evidence_selected_evidence_id", "evidence_preview_result", "evidence_preview_payload"):
        st.session_state.pop(key, None)


def _clear_context_after_variant() -> None:
    st.session_state.pop("evidence_selected_evidence_id", None)
    st.session_state.pop("evidence_preview_result", None)
    st.session_state.pop("evidence_preview_payload", None)


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


def _pipeline_viewer_url(api_base: str, scenario_id: str, variant_id: str, evidence_id: str | None = None) -> str:
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


def _render_viewer_tab_link(
    api_base: str,
    scenario_id: str,
    variant_id: str,
    evidence_id: str | None = None,
    *,
    label: str = "Open Pipeline Viewer",
) -> None:
    href = _pipeline_viewer_url(api_base, scenario_id, variant_id, evidence_id)
    st.markdown(
        f"""
<a class="viewer-tab-link" href="{href}" target="_blank" rel="noopener noreferrer">
  {label}
</a>
""",
        unsafe_allow_html=True,
    )


def _render_export_actions(result: dict[str, Any]) -> None:
    evidence_id = str(result.get("id") or "simulation-evidence")
    filename_base = _safe_filename(evidence_id)
    json_text = _evidence_json_text(result)
    col_json, col_kpi, col_dma, col_delete = st.columns(4)
    col_json.download_button(
        "Download JSON",
        data=json_text.encode("utf-8"),
        file_name=f"{filename_base}.json",
        mime="application/json",
        use_container_width=True,
        key=f"download_json_{evidence_id}",
    )
    col_kpi.download_button(
        "Download KPI CSV",
        data=_summary_csv_bytes(result),
        file_name=f"{filename_base}-summary.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"download_kpi_{evidence_id}",
    )
    col_dma.download_button(
        "Download DMA CSV",
        data=_rows_csv_bytes(result.get("dma_breakdown") or []),
        file_name=f"{filename_base}-dma.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"download_dma_{evidence_id}",
    )
    if col_delete.button("Delete Evidence", use_container_width=True, key=f"delete_evidence_{evidence_id}"):
        try:
            delete_simulation_result(st.session_state["evidence_api_base"], evidence_id)
            _load_sim_results.clear()
            st.session_state.pop("evidence_selected_evidence_id", None)
            st.success(f"Deleted evidence: {evidence_id}")
            st.rerun()
        except ViewerApiError as exc:
            st.error(str(exc))
            if exc.body:
                st.code(exc.body)
    with st.expander("Raw JSON for copy", expanded=False):
        st.code(json_text, language="json")


def _render_preview_actions(api_base: str, result: dict[str, Any]) -> None:
    evidence_id = str(result.get("id") or "simulation-preview")
    filename_base = _safe_filename(evidence_id)
    json_text = _evidence_json_text(result)
    col_save, col_json, col_kpi = st.columns(3)
    if col_save.button("Confirm & Save Evidence", type="primary", use_container_width=True):
        payload = st.session_state.get("evidence_preview_payload")
        if not isinstance(payload, dict):
            st.error("No preview payload is available to save.")
            return
        try:
            response = run_simulation(api_base, payload)
            saved_id = str(response.get("evidence_id") or evidence_id)
            _load_sim_results.clear()
            st.session_state.pop("evidence_preview_result", None)
            st.session_state.pop("evidence_preview_payload", None)
            st.session_state["viewer_sim_mode"] = "specific"
            st.session_state["viewer_sim_evidence_id"] = saved_id
            st.session_state["evidence_selected_evidence_id"] = saved_id
            st.success(f"Saved confirmed evidence: {saved_id}")
            st.rerun()
        except ViewerApiError as exc:
            st.error(str(exc))
            if exc.body:
                st.code(exc.body)
    col_json.download_button(
        "Download Preview JSON",
        data=json_text.encode("utf-8"),
        file_name=f"{filename_base}-preview.json",
        mime="application/json",
        use_container_width=True,
        key=f"download_preview_json_{evidence_id}",
    )
    col_kpi.download_button(
        "Download Preview KPI CSV",
        data=_summary_csv_bytes(result),
        file_name=f"{filename_base}-preview-summary.csv",
        mime="text/csv",
        use_container_width=True,
        key=f"download_preview_kpi_{evidence_id}",
    )
    with st.expander("Preview JSON for copy", expanded=False):
        st.code(json_text, language="json")


def _evidence_json_text(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def _summary_csv_bytes(result: dict[str, Any]) -> bytes:
    execution_context = result.get("execution_context") if isinstance(result.get("execution_context"), dict) else {}
    run_info = result.get("run_info") if isinstance(result.get("run_info"), dict) else {}
    kpi = result.get("kpi") if isinstance(result.get("kpi"), dict) else {}
    row: dict[str, Any] = {
        "id": result.get("id"),
        "scenario_ref": result.get("scenario_ref"),
        "variant_ref": result.get("variant_ref"),
        "sw_baseline_ref": result.get("sw_baseline_ref"),
        "silicon_rev": execution_context.get("silicon_rev"),
        "thermal": execution_context.get("thermal"),
        "ambient_temp_c": execution_context.get("ambient_temp_c"),
        "overall_feasibility": result.get("overall_feasibility"),
        "params_hash": result.get("params_hash"),
        "timestamp": run_info.get("timestamp"),
    }
    for key, value in kpi.items():
        row[f"kpi_{key}"] = value
    return _rows_csv_bytes([row])


def _rows_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    clean_rows = [row for row in rows if isinstance(row, dict)]
    if not clean_rows:
        return b""
    fieldnames: list[str] = []
    for row in clean_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in clean_rows:
        writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})
    return buffer.getvalue().encode("utf-8-sig")


def _csv_cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return value


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in value)[:160]


def _default_silicon_rev() -> str:
    soc_id = str(st.session_state.get("evidence_soc_id") or st.session_state.get("viewer_soc_id") or "").lower()
    if "exynos2600" in soc_id:
        return "EVT1.3"
    return "EVT0"


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


def _numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_ms(value: Any) -> str:
    number = _numeric(value)
    if number is None:
        return "-"
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    return f"{text} ms"


def _format_value(value: Any, suffix: str = "") -> str:
    number = _numeric(value)
    if number is None:
        return "-"
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def _timeline_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in result.get("timeline_events") or [] if isinstance(row, dict)]


def _event_id(event: dict[str, Any]) -> str:
    return str(event.get("task_id") or event.get("node_id") or event.get("hw_name") or "task")


def _event_label(event: dict[str, Any], *, include_frame: bool) -> str:
    name = _event_id(event)
    resource = event.get("resource_id") or event.get("task_type") or event.get("constraint_type")
    if resource and resource not in name:
        name = f"{resource} / {name}"
    if include_frame and event.get("frame_index") is not None:
        name = f"F{event.get('frame_index')} / {name}"
    return name


def _constraint_label(event: dict[str, Any]) -> str:
    if event.get("constraint_type"):
        return str(event.get("constraint_type"))
    task_type = str(event.get("task_type") or "")
    if task_type:
        return task_type
    return "task"


def _render_timing_summary(result: dict[str, Any]) -> None:
    events = _timeline_events(result)
    kpi = result.get("kpi") if isinstance(result.get("kpi"), dict) else {}
    if not events:
        st.info("No timeline events are available for this evidence.")
        return

    end_ms = _numeric(kpi.get("timeline_end_ms"))
    if end_ms is None:
        end_ms = max((_numeric(event.get("end_ms")) or 0.0 for event in events), default=0.0)
    critical_ms = _numeric(kpi.get("critical_path_ms"))
    critical_count = _numeric(kpi.get("critical_path_task_count"))
    resource_wait_event = max(events, key=lambda event: _numeric(event.get("resource_wait_ms")) or 0.0)
    token_wait_event = max(events, key=lambda event: _numeric(event.get("token_wait_ms")) or 0.0)
    slack_events = [event for event in events if _numeric(event.get("slack_ms")) is not None]
    tightest_slack_event = min(slack_events, key=lambda event: _numeric(event.get("slack_ms")) or 0.0) if slack_events else None
    source_events = [
        event
        for event in events
        if event.get("constraint_type") == "source" or _numeric(event.get("v_valid_ms")) is not None
    ]
    sink_events = [
        event
        for event in events
        if event.get("constraint_type") == "sink" or _numeric(event.get("scanout_ms")) is not None
    ]

    cols = st.columns(4)
    cols[0].metric("Timeline End", _format_ms(end_ms))
    critical_detail = f"{int(critical_count)} tasks" if critical_count is not None else "-"
    cols[1].metric("Critical Path", _format_ms(critical_ms), help=critical_detail)
    cols[2].metric(
        "Max Resource Wait",
        _format_ms(resource_wait_event.get("resource_wait_ms")),
        help=_event_id(resource_wait_event),
    )
    cols[3].metric(
        "Max Token Wait",
        _format_ms(token_wait_event.get("token_wait_ms")),
        help=_event_id(token_wait_event),
    )

    cols = st.columns(3)
    if tightest_slack_event:
        cols[0].metric("Tightest Slack", _format_ms(tightest_slack_event.get("slack_ms")), help=_event_id(tightest_slack_event))
    else:
        cols[0].metric("Tightest Slack", "-")
    if source_events:
        source = source_events[0]
        cols[1].metric(
            "Source Window",
            _format_ms(source.get("v_valid_ms") or source.get("duration_ms")),
            help=f"{_event_id(source)} / fps={_format_value(source.get('source_fps'))}",
        )
    else:
        cols[1].metric("Source Window", "-")
    if sink_events:
        sink = min(sink_events, key=lambda event: _numeric(event.get("slack_ms")) or 0.0)
        cols[2].metric(
            "Sink Deadline Slack",
            _format_ms(sink.get("slack_ms")),
            help=f"{_event_id(sink)} / deadline={_format_ms(sink.get('deadline_ms'))}",
        )
    else:
        cols[2].metric("Sink Deadline Slack", "-")


def _timeline_chart_color(event: dict[str, Any]) -> str:
    if event.get("critical"):
        return "#EF4444"
    constraint = event.get("constraint_type")
    if constraint == "source":
        return "#22C55E"
    if constraint == "sink":
        return "#3B82F6"
    task_type = str(event.get("task_type") or "").lower()
    if "sw" in task_type:
        return "#8B5CF6"
    if "dma" in task_type or "m2m" in task_type:
        return "#F59E0B"
    return "#64748B"


def _timeline_hover(event: dict[str, Any]) -> str:
    fields = [
        ("task", _event_id(event)),
        ("node", event.get("node_id")),
        ("resource", event.get("resource_id")),
        ("frame", event.get("frame_index")),
        ("edge", event.get("edge_type")),
        ("otf_group", event.get("otf_group_id")),
        ("bottleneck", event.get("bottleneck")),
        ("type", _constraint_label(event)),
        ("start", _format_ms(event.get("start_ms"))),
        ("end", _format_ms(event.get("end_ms"))),
        ("duration", _format_ms(event.get("duration_ms"))),
        ("resource_wait", _format_ms(event.get("resource_wait_ms"))),
        ("token_wait", _format_ms(event.get("token_wait_ms"))),
        ("deadline", _format_ms(event.get("deadline_ms"))),
        ("slack", _format_ms(event.get("slack_ms"))),
    ]
    return "<br>".join(f"{key}: {value}" for key, value in fields if value not in (None, "-"))


def _render_timing_chart(result: dict[str, Any], *, key_prefix: str = "stored") -> None:
    events = _timeline_events(result)
    if not events:
        st.info("No timeline events are available for chart rendering.")
        return
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.warning("Plotly is not installed in this environment. The timeline table is shown instead.")
        st.dataframe(events, use_container_width=True, hide_index=True)
        return

    evidence_id = _safe_filename(str(result.get("id") or "selected"))
    frame_values = sorted(
        {
            int(value)
            for value in (_numeric(event.get("frame_index")) for event in events)
            if value is not None
        }
    )
    if len(frame_values) > 1:
        frame_options = ["All", *[str(value) for value in frame_values]]
        frame_choice = st.selectbox("Frame", frame_options, key=f"{key_prefix}_timing_chart_frame_{evidence_id}", index=0)
    else:
        frame_choice = "All"
    show_waits = st.checkbox("Show queue waits", value=True, key=f"{key_prefix}_timing_chart_waits_{evidence_id}")
    show_deadlines = st.checkbox("Show deadlines", value=True, key=f"{key_prefix}_timing_chart_deadlines_{evidence_id}")

    event_order = {id(event): index for index, event in enumerate(events)}
    visible_events = events
    if frame_choice != "All":
        frame_index = int(frame_choice)
        visible_events = [
            event
            for event in events
            if _numeric(event.get("frame_index")) is not None and int(_numeric(event.get("frame_index")) or 0) == frame_index
        ]
    visible_events = sorted(
        visible_events,
        key=lambda event: (
            _numeric(event.get("frame_index")) or 0.0,
            _numeric(event.get("start_ms")) or 0.0,
            event_order.get(id(event), 0),
        ),
    )
    include_frame = frame_choice == "All" and len(frame_values) > 1
    labels = [_event_label(event, include_frame=include_frame) for event in visible_events]
    fig = go.Figure()
    legend_seen: set[str] = set()

    for label, event in zip(labels, visible_events, strict=False):
        start = _numeric(event.get("start_ms")) or 0.0
        end = _numeric(event.get("end_ms"))
        duration = _numeric(event.get("duration_ms"))
        if duration is None and end is not None:
            duration = max(0.0, end - start)
        duration = duration or 0.0
        color = _timeline_chart_color(event)
        segment_name = "Critical" if event.get("critical") else _constraint_label(event).title()
        showlegend = segment_name not in legend_seen
        legend_seen.add(segment_name)
        fig.add_trace(
            go.Bar(
                x=[duration],
                y=[label],
                base=[start],
                orientation="h",
                name=segment_name,
                marker={
                    "color": color,
                    "line": {"color": "#B91C1C" if event.get("critical") else color, "width": 2 if event.get("critical") else 0},
                },
                hovertext=[_timeline_hover(event)],
                hoverinfo="text",
                showlegend=showlegend,
            )
        )

        if show_waits:
            ready = _numeric(event.get("ready_ms"))
            token_wait = _numeric(event.get("token_wait_ms")) or 0.0
            if ready is not None and token_wait > 0:
                showlegend = "Token Wait" not in legend_seen
                legend_seen.add("Token Wait")
                fig.add_trace(
                    go.Bar(
                        x=[token_wait],
                        y=[label],
                        base=[max(0.0, ready - token_wait)],
                        orientation="h",
                        name="Token Wait",
                        marker={"color": "#FDBA74", "pattern": {"shape": "/"}},
                        hovertext=[f"token_wait: {_format_ms(token_wait)}<br>task: {_event_id(event)}"],
                        hoverinfo="text",
                        showlegend=showlegend,
                    )
                )
            resource_wait = _numeric(event.get("resource_wait_ms")) or 0.0
            if ready is not None and resource_wait > 0:
                showlegend = "Resource Wait" not in legend_seen
                legend_seen.add("Resource Wait")
                fig.add_trace(
                    go.Bar(
                        x=[resource_wait],
                        y=[label],
                        base=[ready],
                        orientation="h",
                        name="Resource Wait",
                        marker={"color": "#CBD5E1", "pattern": {"shape": "x"}},
                        hovertext=[f"resource_wait: {_format_ms(resource_wait)}<br>task: {_event_id(event)}"],
                        hoverinfo="text",
                        showlegend=showlegend,
                    )
                )

    if show_deadlines:
        deadline_x: list[float] = []
        deadline_y: list[str] = []
        deadline_text: list[str] = []
        deadline_color: list[str] = []
        for label, event in zip(labels, visible_events, strict=False):
            deadline = _numeric(event.get("deadline_ms"))
            if deadline is None:
                continue
            slack = _numeric(event.get("slack_ms"))
            deadline_x.append(deadline)
            deadline_y.append(label)
            deadline_text.append(f"deadline: {_format_ms(deadline)}<br>slack: {_format_ms(slack)}<br>task: {_event_id(event)}")
            deadline_color.append("#16A34A" if slack is None or slack >= 0 else "#DC2626")
        if deadline_x:
            fig.add_trace(
                go.Scatter(
                    x=deadline_x,
                    y=deadline_y,
                    mode="markers",
                    name="Deadline",
                    marker={"symbol": "x", "size": 10, "color": deadline_color, "line": {"width": 2}},
                    hovertext=deadline_text,
                    hoverinfo="text",
                )
            )

    height = max(420, min(900, 120 + 30 * max(1, len(labels))))
    fig.update_layout(
        height=height,
        barmode="overlay",
        bargap=0.28,
        margin={"l": 16, "r": 16, "t": 24, "b": 32},
        xaxis_title="Time (ms)",
        yaxis_title="Task",
        legend_title_text="Segment",
        hovermode="closest",
    )
    fig.update_xaxes(rangemode="tozero", showgrid=True, gridcolor="#E5E7EB")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_timing_chart_plot_{evidence_id}_{frame_choice}")

    critical_rows = [
        row
        for row in _ordered_table(
            [event for event in visible_events if event.get("critical")],
            [
                "critical_path_rank",
                "task_id",
                "node_id",
                "resource_id",
                "edge_type",
                "otf_group_id",
                "bottleneck",
                "frame_index",
                "start_ms",
                "end_ms",
                "duration_ms",
                "resource_wait_ms",
                "token_wait_ms",
                "slack_ms",
            ],
        )
    ]
    issue_rows = _ordered_table(
        sorted(
            visible_events,
            key=lambda event: (
                -((_numeric(event.get("resource_wait_ms")) or 0.0) + (_numeric(event.get("token_wait_ms")) or 0.0)),
                _numeric(event.get("slack_ms")) if _numeric(event.get("slack_ms")) is not None else 1e12,
            ),
        )[:12],
        [
            "task_id",
            "node_id",
            "resource_id",
            "frame_index",
            "resource_wait_ms",
            "token_wait_ms",
            "deadline_ms",
            "slack_ms",
            "predecessors",
        ],
    )
    detail_cols = st.columns(2)
    with detail_cols[0]:
        st.caption("Critical path")
        st.dataframe(critical_rows, use_container_width=True, hide_index=True)
    with detail_cols[1]:
        st.caption("Top wait/slack candidates")
        st.dataframe(issue_rows, use_container_width=True, hide_index=True)


def _render_debug_trace(result: dict[str, Any]) -> None:
    trace = result.get("calculation_trace")
    if not isinstance(trace, dict):
        st.info("No calculation trace is stored for this result. Run a simulation preview with Debug trace enabled, then confirm/save it if needed.")
        return

    st.caption("Formula-level trace for KPI, IP power/performance, DMA bandwidth, and timing scheduling inputs.")
    config = trace.get("config") if isinstance(trace.get("config"), dict) else {}
    if config:
        with st.expander("Run config used by calculations", expanded=False):
            st.json(config)

    kpi_rows = []
    for name, item in (trace.get("kpi") or {}).items():
        if not isinstance(item, dict):
            continue
        kpi_rows.append(
            {
                "kpi": name,
                "formula": item.get("formula"),
                "inputs": item.get("inputs"),
                "result": item.get("result"),
            }
        )
    if kpi_rows:
        st.markdown("**KPI formulas**")
        st.dataframe(kpi_rows, use_container_width=True, hide_index=True)

    ip_rows = []
    for item in trace.get("ip") or []:
        if not isinstance(item, dict):
            continue
        required = item.get("required_clock") if isinstance(item.get("required_clock"), dict) else {}
        dvfs = item.get("dvfs") if isinstance(item.get("dvfs"), dict) else {}
        power = item.get("power") if isinstance(item.get("power"), dict) else {}
        timing = item.get("timing") if isinstance(item.get("timing"), dict) else {}
        ip_rows.append(
            {
                "node_id": item.get("node_id"),
                "hw_name": item.get("hw_name"),
                "mode": item.get("mode"),
                "required_before_group_mhz": required.get("before_group_align_mhz"),
                "required_after_group_mhz": required.get("after_group_align_mhz"),
                "dvfs_group": dvfs.get("dvfs_group"),
                "dvfs_level": dvfs.get("selected_level"),
                "set_clock_mhz": dvfs.get("set_clock_mhz"),
                "set_voltage_mv": dvfs.get("set_voltage_mv"),
                "vdd": dvfs.get("vdd"),
                "vdd_leader": dvfs.get("vdd_leader"),
                "power_mw": power.get("result_mw"),
                "hw_time_ms": timing.get("result_ms"),
                "feasible": dvfs.get("feasible"),
                "infeasible_reason": dvfs.get("infeasible_reason"),
            }
        )
    if ip_rows:
        st.markdown("**IP power / DVFS / performance trace**")
        st.dataframe(ip_rows, use_container_width=True, hide_index=True)

    dma_rows = []
    for item in trace.get("dma") or []:
        if not isinstance(item, dict):
            continue
        inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
        intermediate = item.get("intermediate") if isinstance(item.get("intermediate"), dict) else {}
        result_values = item.get("result") if isinstance(item.get("result"), dict) else {}
        dma_rows.append(
            {
                "node_id": item.get("node_id"),
                "port": item.get("port"),
                "direction": item.get("direction"),
                "width": inputs.get("width"),
                "height": inputs.get("height"),
                "fps": inputs.get("fps"),
                "format": inputs.get("format"),
                "bitwidth": inputs.get("bitwidth"),
                "compression": inputs.get("compression"),
                "comp_ratio": inputs.get("comp_ratio"),
                "format_bpp_factor": intermediate.get("format_bpp_factor"),
                "llc_enabled": inputs.get("llc_enabled"),
                "llc_weight": intermediate.get("llc_weight"),
                "bw_mbs": result_values.get("bw_mbs"),
                "bw_power_mw": result_values.get("bw_power_mw"),
                "bw_power_ma": result_values.get("bw_power_ma"),
            }
        )
    if dma_rows:
        st.markdown("**DMA bandwidth trace**")
        st.dataframe(dma_rows, use_container_width=True, hide_index=True)

    timeline = trace.get("timeline") if isinstance(trace.get("timeline"), dict) else {}
    otf_groups = timeline.get("otf_groups") if isinstance(timeline.get("otf_groups"), list) else []
    if otf_groups:
        st.markdown("**Timing / OTF group trace**")
        st.dataframe(otf_groups, use_container_width=True, hide_index=True)
    with st.expander("Raw calculation trace", expanded=False):
        st.json(trace)


def _result_warnings(result: dict[str, Any]) -> list[str]:
    direct = result.get("warnings")
    if isinstance(direct, list):
        return [str(item) for item in direct if item]
    trace = result.get("calculation_trace")
    if isinstance(trace, dict) and isinstance(trace.get("warnings"), list):
        return [str(item) for item in trace["warnings"] if item]
    return []


def _render_result_warnings(result: dict[str, Any]) -> None:
    warnings = _result_warnings(result)
    if not warnings:
        return
    severe = any(
        marker in warning
        for warning in warnings
        for marker in ("All compute IP core power is zero", "All compute IP HW time is zero")
    )
    message = "\n".join(f"- {warning}" for warning in warnings)
    if severe:
        st.error(message)
    else:
        st.warning(message)


def _ip_power_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    dvfs_rows = result.get("dvfs_breakdown") if isinstance(result.get("dvfs_breakdown"), list) else []
    if dvfs_rows:
        return _ordered_table(
            [
                {
                    "node_id": row.get("node_id"),
                    "hw_name": row.get("hw_name"),
                    "mode": row.get("mode"),
                    "ip_ref": row.get("ip_ref"),
                    "power_mw": row.get("total_power_mw"),
                    "active_power_mw": row.get("active_power_mw"),
                    "required_clock_mhz": row.get("required_clock_mhz"),
                    "set_clock_mhz": row.get("set_clock_mhz"),
                    "dvfs_level": row.get("dvfs_level"),
                    "set_voltage_mv": row.get("set_voltage_mv"),
                    "vdd": row.get("vdd"),
                    "vdd_leader": row.get("vdd_leader"),
                    "ppc": row.get("ppc"),
                    "unit_power_mw_mp": row.get("unit_power_mw_mp"),
                    "resolution_mp": row.get("input_resolution_mp"),
                    "fps": row.get("fps"),
                    "feasible": row.get("feasible"),
                    "infeasible_reason": row.get("infeasible_reason"),
                }
                for row in dvfs_rows
                if isinstance(row, dict)
            ],
            [
                "node_id",
                "hw_name",
                "mode",
                "ip_ref",
                "power_mw",
                "set_clock_mhz",
                "dvfs_level",
                "set_voltage_mv",
                "vdd",
                "ppc",
                "unit_power_mw_mp",
            ],
        )
    return _ordered_table(
        result.get("ip_breakdown") or [],
        ["ip", "instance_index", "power_mW", "submodules"],
    )


def _render_breakdown(result: dict[str, Any], *, key_prefix: str = "stored") -> None:
    tabs = st.tabs(["IP/Node Power", "DMA BW", "Timing Chart", "Timing Table", "Timeline Table", "Debug Trace", "Raw Evidence"])
    with tabs[0]:
        st.caption("Power is calculated per scenario node / hardware role. `ip_ref` is the catalog source and can repeat for multiple ISP roles.")
        st.dataframe(_ip_power_rows(result), use_container_width=True, hide_index=True)
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
        _render_timing_summary(result)
        _render_timing_chart(result, key_prefix=key_prefix)
    with tabs[3]:
        st.dataframe(result.get("timing_breakdown") or [], use_container_width=True, hide_index=True)
    with tabs[4]:
        st.dataframe(
            _ordered_table(
                result.get("timeline_events") or [],
                [
                    "frame_index",
                    "critical_path_rank",
                    "critical",
                    "task_id",
                    "node_id",
                    "hw_name",
                    "resource_id",
                    "edge_type",
                    "otf_group_id",
                    "bottleneck",
                    "latency_offset_ms",
                    "task_type",
                    "constraint_type",
                    "start_ms",
                    "end_ms",
                    "duration_ms",
                    "ready_ms",
                    "resource_wait_ms",
                    "token_wait_ms",
                    "deadline_ms",
                    "slack_ms",
                    "source_fps",
                    "v_valid_ms",
                    "refresh_hz",
                    "scanout_ms",
                    "predecessors",
                ],
            ),
            use_container_width=True,
            hide_index=True,
        )
    with tabs[5]:
        _render_debug_trace(result)
    with tabs[6]:
        st.json(result)


st.title("Evidence Dashboard")
st.caption("Run scenario/variant simulation as a preview, save only confirmed evidence, and inspect KPI breakdowns.")

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
        _ensure_choice("evidence_silicon_rev", SILICON_REVS, preferred=_default_silicon_rev())
        silicon_rev_choice = st.selectbox(
            "Silicon Rev",
            SILICON_REVS,
            key="evidence_silicon_rev",
            help="Typical bring-up revisions are EVT0 and EVT1. Exynos2600 final is EVT1.3. Use Custom for other minor revisions.",
        )
        if silicon_rev_choice == "Custom":
            silicon_rev = st.text_input(
                "Custom Silicon Rev",
                value=st.session_state.get("evidence_custom_silicon_rev", "EVT1.3"),
                key="evidence_custom_silicon_rev",
            )
        else:
            silicon_rev = silicon_rev_choice
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
        debug_trace = st.checkbox(
            "Debug calculation trace",
            value=False,
            key="evidence_debug_trace",
            help="Attach formula-level calculation details to the preview. It is saved to DB only when you confirm the result.",
        )
        debug_trace_level = st.selectbox(
            "Debug detail",
            ["formula", "summary", "full"],
            key="evidence_debug_trace_level",
            help="formula is the normal debug mode. summary is compact; full is reserved for deeper timing details.",
            disabled=not debug_trace,
        )
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
        st.caption("Simulation runs are preview-only by default. Use Confirm & Save Evidence after reviewing the result.")
        submitted = st.form_submit_button("Run Preview", type="primary", use_container_width=True)

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
                    "debug_trace": debug_trace,
                    "debug_trace_level": debug_trace_level,
                },
                "dvfs_tables": dvfs_tables,
                "persist": False,
                "force": force,
            }
            response = run_simulation(api_base, payload)
            evidence_id = str(response.get("evidence_id") or "")
            if response.get("persisted"):
                _load_sim_results.clear()
                st.session_state["viewer_sim_mode"] = "specific"
                st.session_state["viewer_sim_evidence_id"] = evidence_id
                st.session_state["evidence_selected_evidence_id"] = evidence_id
                st.session_state.pop("evidence_preview_result", None)
                st.session_state.pop("evidence_preview_payload", None)
                st.success(f"Existing confirmed evidence matched this run: {evidence_id}")
            else:
                preview = response.get("evidence")
                if isinstance(preview, dict):
                    preview["warnings"] = response.get("warnings") or []
                    save_payload = dict(payload)
                    save_payload["persist"] = True
                    st.session_state["evidence_preview_result"] = preview
                    st.session_state["evidence_preview_payload"] = save_payload
                st.success(f"Simulation preview completed: {evidence_id} (not saved)")
            for warning in response.get("warnings") or []:
                st.warning(str(warning))
            st.json({key: response.get(key) for key in ("cached", "persisted", "params_hash", "kpi")})
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
    preview_tab, saved_tab = st.tabs(["Preview Run", "Saved Evidence"])
    with preview_tab:
        preview_result = st.session_state.get("evidence_preview_result")
        if isinstance(preview_result, dict):
            st.markdown("**Simulation Preview (not saved)**")
            st.caption("Review this preview first. It will not appear in the evidence list until you confirm and save it.")
            preview_kpi = preview_result.get("kpi") if isinstance(preview_result.get("kpi"), dict) else {}
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Power", f"{_round(_kpi(preview_kpi, 'total_power_mw', 'power_mw')) or 0:g} mW")
            p2.metric("Current", f"{_round(_kpi(preview_kpi, 'total_power_ma', 'power_ma')) or 0:g} mA")
            p3.metric("Bandwidth", f"{_round(_kpi(preview_kpi, 'total_bw_mbs', 'bw_mbs')) or 0:g} MB/s")
            p4.metric("HW Time", f"{_round(_kpi(preview_kpi, 'hw_time_max_ms', 'hw_time_ms')) or 0:g} ms")
            _render_result_warnings(preview_result)
            _render_preview_actions(api_base, preview_result)
            _render_viewer_tab_link(
                api_base,
                scenario_id,
                variant_id,
                None,
                label="Open Scenario in Pipeline Viewer",
            )
            _render_breakdown(preview_result, key_prefix="preview")
        else:
            st.info("Run a simulation preview from the left panel. Preview results stay separate from saved evidence until confirmed.")

    with saved_tab:
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
            _render_result_warnings(selected)
            _render_viewer_tab_link(api_base, scenario_id, variant_id, selected_id)
            _render_export_actions(selected)
            _render_breakdown(selected, key_prefix="stored")
