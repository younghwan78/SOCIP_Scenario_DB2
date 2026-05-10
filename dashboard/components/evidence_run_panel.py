"""Simulation run execution panel for the Evidence Dashboard."""
from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from dashboard.components.simulation_api_client import run_simulation
from dashboard.components.simulation_run_form import render_simulation_run_form
from dashboard.components.viewer_api_client import ViewerApiError, list_sw_profiles


def render_evidence_run_panel(
    *,
    api_base: str,
    scenario_id: str,
    variant_id: str,
    default_silicon_rev: str,
    on_persisted: Callable[[str], None] | None = None,
) -> None:
    sw_profiles, sw_error = _load_sw_profile_options(api_base)
    payload = render_simulation_run_form(
        scenario_id=scenario_id,
        variant_id=variant_id,
        default_silicon_rev=default_silicon_rev,
        sw_profiles=sw_profiles,
        sw_error=sw_error,
    )
    if not payload:
        return

    try:
        response = run_simulation(api_base, payload)
        _handle_simulation_response(response, payload, on_persisted=on_persisted)
    except ViewerApiError as exc:
        st.error(str(exc))
        if exc.body:
            st.code(exc.body)


def clear_evidence_run_caches() -> None:
    _load_sw_profile_options.clear()


@st.cache_data(ttl=30)
def _load_sw_profile_options(base_url: str) -> tuple[list[dict], str | None]:
    try:
        return list_sw_profiles(base_url), None
    except ViewerApiError as exc:
        return [], str(exc)


def _handle_simulation_response(
    response: dict,
    payload: dict,
    *,
    on_persisted: Callable[[str], None] | None,
) -> None:
    evidence_id = str(response.get("evidence_id") or "")
    if response.get("persisted"):
        _clear_preview_state()
        _select_saved_evidence(evidence_id)
        if on_persisted:
            on_persisted(evidence_id)
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


def _select_saved_evidence(evidence_id: str) -> None:
    st.session_state["viewer_sim_mode"] = "specific"
    st.session_state["viewer_sim_evidence_id"] = evidence_id
    st.session_state["evidence_selected_evidence_id"] = evidence_id


def _clear_preview_state() -> None:
    st.session_state.pop("evidence_preview_result", None)
    st.session_state.pop("evidence_preview_payload", None)
