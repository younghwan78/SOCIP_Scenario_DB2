"""Preview and saved evidence result panel for the Evidence Dashboard."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_actions import (
    render_kpi_metrics,
    render_preview_actions,
    render_result_warnings,
    render_saved_export_actions,
    render_viewer_tab_link,
    result_rows,
)
from dashboard.components.evidence_dashboard_contract import (
    SIMULATION_RESULT_TOP_TABS,
    VIEWER_LINK_LABEL_PREVIEW,
    VIEWER_LINK_LABEL_SAVED,
)
from dashboard.components.evidence_compare import render_preview_saved_comparison
from dashboard.components.evidence_result_view import render_result_breakdown
from dashboard.components.simulation_api_client import list_simulation_results
from dashboard.components.table_actions import render_copyable_dataframe
from dashboard.components.viewer_api_client import ViewerApiError


def render_evidence_results_panel(
    *,
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
) -> None:
    st.subheader("Simulation Results")
    preview_tab, saved_tab = st.tabs(list(SIMULATION_RESULT_TOP_TABS))
    with preview_tab:
        _render_preview_result(api_base, scenario_id, variant_id, soc_id, project_id)
    with saved_tab:
        _render_saved_results(api_base, scenario_id, variant_id, soc_id, project_id)


def clear_evidence_results_cache() -> None:
    _load_sim_results.clear()


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


def _render_preview_result(
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
) -> None:
    preview_result = st.session_state.get("evidence_preview_result")
    if not isinstance(preview_result, dict):
        st.info("Run a simulation preview from the left panel. Preview results stay separate from saved evidence until confirmed.")
        return

    st.markdown("**Simulation Preview (not saved)**")
    st.caption("Review this preview first. It will not appear in the evidence list until you confirm and save it.")
    preview_kpi = preview_result.get("kpi") if isinstance(preview_result.get("kpi"), dict) else {}
    render_kpi_metrics(preview_kpi)
    render_result_warnings(preview_result)
    render_preview_actions(
        preview_result,
        api_base=api_base,
        preview_payload=st.session_state.get("evidence_preview_payload"),
        on_saved=_after_preview_saved,
    )
    render_viewer_tab_link(
        api_base=api_base,
        scenario_id=scenario_id,
        variant_id=variant_id,
        soc_id=soc_id,
        project_id=project_id,
        evidence_id=None,
        label=VIEWER_LINK_LABEL_PREVIEW,
    )
    render_result_breakdown(preview_result, key_prefix="preview")


def _render_saved_results(
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
) -> None:
    latest_only = st.toggle("Latest result only", value=False, key="evidence_latest_only")
    results, results_error = _load_sim_results(api_base, scenario_id, variant_id, latest_only)
    if results_error:
        st.error(results_error)
        return
    if not results:
        st.info("No simulation evidence is stored for the selected scenario/variant.")
        return

    rows = result_rows(results)
    render_copyable_dataframe(rows, key="saved_evidence_result_list", use_container_width=True, hide_index=True)
    evidence_ids = [str(row["id"]) for row in rows if row.get("id")]
    _ensure_choice("evidence_selected_evidence_id", evidence_ids)
    selected_id = st.selectbox("Selected Evidence", evidence_ids, key="evidence_selected_evidence_id")
    selected = next((item for item in results if item.get("id") == selected_id), results[0])
    _render_saved_result_detail(api_base, scenario_id, variant_id, soc_id, project_id, selected_id, selected)


def _render_saved_result_detail(
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None,
    project_id: str | None,
    selected_id: str,
    selected: dict[str, Any],
) -> None:
    kpi = selected.get("kpi") if isinstance(selected.get("kpi"), dict) else {}
    render_kpi_metrics(kpi)
    render_result_warnings(selected)
    render_viewer_tab_link(
        api_base=api_base,
        scenario_id=scenario_id,
        variant_id=variant_id,
        soc_id=soc_id,
        project_id=project_id,
        evidence_id=selected_id,
        label=VIEWER_LINK_LABEL_SAVED,
    )
    render_saved_export_actions(selected, api_base=api_base, on_deleted=_after_evidence_deleted)
    render_preview_saved_comparison(
        preview=st.session_state.get("evidence_preview_result"),
        saved=selected,
        key_prefix=f"stored_{selected_id}",
    )
    render_result_breakdown(selected, key_prefix="stored")


def _after_preview_saved(saved_id: str) -> None:
    clear_evidence_results_cache()
    st.session_state.pop("evidence_preview_result", None)
    st.session_state.pop("evidence_preview_payload", None)
    st.session_state["viewer_sim_mode"] = "specific"
    st.session_state["viewer_sim_evidence_id"] = saved_id
    st.session_state["evidence_selected_evidence_id"] = saved_id


def _after_evidence_deleted(_deleted_id: str) -> None:
    clear_evidence_results_cache()
    st.session_state.pop("evidence_selected_evidence_id", None)


def _ensure_choice(key: str, options: list[str], preferred: str | None = None) -> None:
    if options and st.session_state.get(key) not in options:
        st.session_state[key] = preferred if preferred in options else options[0]
