"""Saved simulation timing, pinned to the evidence used by the pipeline view."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import streamlit as st

from dashboard.components.timing_chart import render_timing_chart, render_timing_summary
from dashboard.components.viewer_api_client import ViewerApiError, _request_json
from scenario_db.api.schemas.view import ViewResponse


def _validate_scope(payload: dict[str, Any], scenario_id: str, variant_id: str, evidence_id: str | None = None) -> None:
    if (payload.get("kind") != "evidence.simulation"
            or payload.get("scenario_ref") != scenario_id
            or payload.get("variant_ref") != variant_id
            or not isinstance(payload.get("id"), str)
            or not payload["id"]
            or (evidence_id is not None and payload["id"] != evidence_id)):
        raise ViewerApiError("Simulation evidence does not match the requested id, scenario and variant")


@st.cache_data(ttl=30, show_spinner=False)
def list_saved_simulation_results(api_base: str, scenario_id: str, variant_id: str | None, *, latest: bool = False) -> list[dict[str, Any]]:
    """At most 50 newest runs. Failures propagate and are never cached."""
    if not scenario_id or not variant_id:
        return []
    payload = _request_json("GET", api_base, "/simulation/results", params={
        "scenario_ref": scenario_id, "variant_ref": variant_id,
        "limit": 1 if latest else 50, "latest": latest,
    })
    items = payload.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ViewerApiError("Invalid simulation results list")
    for item in items:
        _validate_scope(item, scenario_id, variant_id)
    return items


def resolve_overlay_evidence_id(api_base: str, scenario_id: str, variant_id: str | None, *, sim_mode: str, sim_evidence_id: str | None) -> str | None:
    """Resolve latest once before any projection, then request every view by ID."""
    if sim_mode == "none":
        return None
    if sim_mode not in {"latest", "specific"}:
        raise ViewerApiError("Unknown simulation overlay mode")
    if not scenario_id or not variant_id:
        if sim_evidence_id:
            raise ViewerApiError("Select a scenario and variant before choosing simulation evidence")
        return None
    if sim_mode == "specific":
        return sim_evidence_id or None
    items = list_saved_simulation_results(api_base, scenario_id, variant_id, latest=True)
    return items[0]["id"] if items else None


def view_overlay_evidence_id(view: ViewResponse, scenario_id: str, variant_id: str | None) -> str | None:
    """Use the server's applied ID, not a second latest lookup or a text input."""
    evidence_id = view.metadata.get("simulation_evidence_id")
    if not evidence_id:
        return None
    if not variant_id or view.scenario_id != scenario_id or view.variant_id != variant_id or not isinstance(evidence_id, str):
        raise ViewerApiError("The displayed view does not match the selected simulation context")
    return evidence_id


def saved_evidence_option_label(item: dict[str, Any]) -> str:
    evidence_id = str(item.get("id") or "")
    kpi = item.get("kpi") if isinstance(item.get("kpi"), dict) else {}
    bits = []
    for key, label in (("total_power_mw", "mW"), ("critical_path_ms", "ms")):
        value = kpi.get(key)
        if isinstance(value, (int, float)):
            bits.append(f"{'crit ' if key == 'critical_path_ms' else ''}{value:.1f}{label}")
    return f"{evidence_id}  ({', '.join(bits)})" if bits else evidence_id


@st.cache_data(ttl=30, show_spinner=False)
def _load_simulation_result(api_base: str, evidence_id: str, scenario_id: str, variant_id: str) -> dict[str, Any]:
    payload = _request_json("GET", api_base, f"/simulation/results/{quote(evidence_id, safe='')}")
    _validate_scope(payload, scenario_id, variant_id, evidence_id)
    events = payload.get("timeline_events")
    if events is not None and (not isinstance(events, list) or any(not isinstance(event, dict) for event in events)):
        raise ViewerApiError("Invalid simulation timeline events")
    return payload


def clear_viewer_timing_caches() -> None:
    list_saved_simulation_results.clear()
    _load_simulation_result.clear()


def render_viewer_timing_panel(*, api_base: str, evidence_id: str, scenario_id: str, variant_id: str, expanded: bool = False) -> None:
    with st.expander(f"Simulation Timing - {evidence_id}", expanded=expanded):
        try:
            result = _load_simulation_result(api_base, evidence_id, scenario_id, variant_id)
        except ViewerApiError as exc:
            st.error(f"Simulation timing could not be loaded: {exc}")
            if st.button("Retry simulation timing", key=f"viewer_timing_retry_{scenario_id}_{variant_id}_{evidence_id}"):
                _load_simulation_result.clear(api_base, evidence_id, scenario_id, variant_id)
                st.rerun()
            return
        if not result.get("timeline_events"):
            st.info("This saved evidence has no timeline events. Run and save a simulation with timeline capture enabled.")
            return
        st.caption("Node flags summarize all frames. Diagram time windows show frame 0; red edges require a ranked same-frame predecessor relationship.")
        render_timing_summary(result)
        render_timing_chart(result, key_prefix=f"viewer_timing_{scenario_id}_{variant_id}", api_base=api_base)
