r"""Simulation evidence dashboard for ScenarioDB.

Run from the project virtual environment:
  .\.venv\Scripts\python.exe -m streamlit run dashboard/Home.py
"""
from __future__ import annotations

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
from dashboard.components.simulation_readiness import render_simulation_readiness
from dashboard.components.table_actions import render_copyable_dataframe
from dashboard.components.ui_theme import apply_app_theme, render_page_header
from dashboard.components.evidence_actions import (
    render_kpi_metrics,
    render_preview_actions,
    render_result_warnings,
    render_saved_export_actions,
    render_viewer_tab_link,
    result_rows,
)
from dashboard.components.evidence_result_view import render_result_breakdown
from dashboard.components.simulation_run_form import render_simulation_run_form
from dashboard.components.evidence_dashboard_contract import (
    SIMULATION_RESULT_TOP_TABS,
    VIEWER_LINK_LABEL_PREVIEW,
    VIEWER_LINK_LABEL_SAVED,
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
    list_sw_profiles,
    list_variants,
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
  footer, #MainMenu { display: none !important; }
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
apply_app_theme(sidebar_width=288)


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
            format_func=lambda value: compact_soc_label(next((item for item in socs if item.get("id") == value), {"id": value})),
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
            format_func=lambda value: compact_project_label(
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
    st.pills(
        "Scenario Category",
        categories,
        selection_mode="single",
        key="evidence_scenario_category",
        on_change=_clear_context_after_category,
        format_func=_category_label,
        width="stretch",
    )
    category_scenarios = _filter_scenarios_by_category(scenarios, st.session_state["evidence_scenario_category"])
    scenario_query = st.text_input(
        "Scenario Search",
        key="evidence_scenario_filter",
        placeholder="Filter by id or name",
    )
    filtered_scenarios = _filter_scenarios_by_text(category_scenarios, scenario_query)
    if not filtered_scenarios and scenario_query:
        st.warning("No scenarios match the current search filter.")
        filtered_scenarios = category_scenarios

    scenario_ids = [str(item.get("id")) for item in filtered_scenarios if item.get("id")]
    _ensure_choice("evidence_scenario_id", scenario_ids, preferred=st.session_state.get("viewer_scenario_id", "uc-camera-recording"))
    st.selectbox(
        "Scenario",
        scenario_ids,
        key="evidence_scenario_id",
        on_change=_clear_context_after_scenario,
        format_func=lambda value: compact_scenario_label(next((item for item in filtered_scenarios if item.get("id") == value), {"id": value})),
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
        format_func=lambda value: compact_variant_label(next((item for item in variants if item.get("id") == value), {"id": value})),
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


def _category_label(category: str) -> str:
    if category == "all":
        return "All"
    return category.replace("_", " ").title()


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


def _filter_scenarios_by_text(scenarios: list[dict[str, Any]], query: str | None) -> list[dict[str, Any]]:
    needle = str(query or "").strip().lower()
    if not needle:
        return scenarios
    filtered = []
    for item in scenarios:
        metadata = item.get("metadata_") if isinstance(item.get("metadata_"), dict) else item.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        text = " ".join(
            str(value or "").lower()
            for value in (
                item.get("id"),
                item.get("name"),
                metadata.get("name"),
                metadata.get("title"),
                metadata.get("category"),
                metadata.get("domain"),
            )
        )
        if needle in text:
            filtered.append(item)
    return filtered


def _default_silicon_rev() -> str:
    soc_id = str(st.session_state.get("evidence_soc_id") or st.session_state.get("viewer_soc_id") or "").lower()
    if "exynos2600" in soc_id:
        return "EVT1.3"
    return "EVT0"


def _after_preview_saved(saved_id: str) -> None:
    _load_sim_results.clear()
    st.session_state.pop("evidence_preview_result", None)
    st.session_state.pop("evidence_preview_payload", None)
    st.session_state["viewer_sim_mode"] = "specific"
    st.session_state["viewer_sim_evidence_id"] = saved_id
    st.session_state["evidence_selected_evidence_id"] = saved_id


def _after_evidence_deleted(_deleted_id: str) -> None:
    _load_sim_results.clear()
    st.session_state.pop("evidence_selected_evidence_id", None)


render_page_header(
    "Evidence Dashboard",
    "Run scenario/variant simulation as a preview, save only confirmed evidence, and inspect KPI breakdowns.",
    chips=("Preview first", "Confirm to save", "Power/BW/Timing"),
)

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
    render_simulation_readiness(api_base, scenario_id, variant_id)

run_col, result_col = st.columns([0.9, 1.6], gap="large")

with run_col:
    sw_profiles, sw_error = _load_sw_profile_options(api_base)
    payload = render_simulation_run_form(
        scenario_id=scenario_id,
        variant_id=variant_id,
        default_silicon_rev=_default_silicon_rev(),
        sw_profiles=sw_profiles,
        sw_error=sw_error,
    )
    if payload:
        try:
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
        except ViewerApiError as exc:
            st.error(str(exc))
            if exc.body:
                st.code(exc.body)

with result_col:
    st.subheader("Simulation Results")
    preview_tab, saved_tab = st.tabs(list(SIMULATION_RESULT_TOP_TABS))
    with preview_tab:
        preview_result = st.session_state.get("evidence_preview_result")
        if isinstance(preview_result, dict):
            st.markdown("**Simulation Preview (not saved)**")
            st.caption("Review this preview first. It will not appear in the evidence list until you confirm and save it.")
            preview_kpi = preview_result.get("kpi") if isinstance(preview_result.get("kpi"), dict) else {}
            render_kpi_metrics(preview_kpi)
            render_result_warnings(preview_result)
            render_preview_actions(
                preview_result,
                api_base=api_base,
                preview_payload=st.session_state.get("evidence_preview_payload"),
                on_saved=lambda saved_id: _after_preview_saved(saved_id),
            )
            render_viewer_tab_link(
                api_base=api_base,
                scenario_id=scenario_id,
                variant_id=variant_id,
                soc_id=st.session_state.get("evidence_soc_id") or st.session_state.get("viewer_soc_id"),
                project_id=st.session_state.get("evidence_project_id") or st.session_state.get("viewer_project_id"),
                evidence_id=None,
                label=VIEWER_LINK_LABEL_PREVIEW,
            )
            render_result_breakdown(preview_result, key_prefix="preview")
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
            rows = result_rows(results)
            render_copyable_dataframe(
                rows,
                key="saved_evidence_result_list",
                use_container_width=True,
                hide_index=True,
            )
            evidence_ids = [str(row["id"]) for row in rows if row.get("id")]
            _ensure_choice("evidence_selected_evidence_id", evidence_ids)
            selected_id = st.selectbox("Selected Evidence", evidence_ids, key="evidence_selected_evidence_id")
            selected = next((item for item in results if item.get("id") == selected_id), results[0])
            kpi = selected.get("kpi") if isinstance(selected.get("kpi"), dict) else {}
            render_kpi_metrics(kpi)
            render_result_warnings(selected)
            render_viewer_tab_link(
                api_base=api_base,
                scenario_id=scenario_id,
                variant_id=variant_id,
                soc_id=st.session_state.get("evidence_soc_id") or st.session_state.get("viewer_soc_id"),
                project_id=st.session_state.get("evidence_project_id") or st.session_state.get("viewer_project_id"),
                evidence_id=selected_id,
                label=VIEWER_LINK_LABEL_SAVED,
            )
            render_saved_export_actions(
                selected,
                api_base=api_base,
                on_deleted=lambda deleted_id: _after_evidence_deleted(deleted_id),
            )
            render_result_breakdown(selected, key_prefix="stored")
