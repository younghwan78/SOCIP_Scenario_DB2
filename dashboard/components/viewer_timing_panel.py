"""Simulation timing panel for the Pipeline Viewer.

Renders the timeline of the overlay evidence (the same simulation evidence
whose clocks/power/BW annotate the diagram) directly under the pipeline view,
reusing the Evidence Dashboard timing chart with its diagram cross-probe.
"""
from __future__ import annotations

from typing import Any

import requests
import streamlit as st

from dashboard.components.timing_chart import render_timing_chart, render_timing_summary


def resolve_overlay_evidence_id(
    api_base: str,
    scenario_id: str,
    variant_id: str | None,
    *,
    sim_mode: str,
    sim_evidence_id: str | None,
) -> str | None:
    """Evidence id the viewer overlay refers to, or None when overlay is off."""

    if sim_mode == "specific" and sim_evidence_id:
        return sim_evidence_id
    if sim_mode == "latest":
        items = list_saved_simulation_results(api_base, scenario_id, variant_id, latest=True)
        if items:
            return str(items[0].get("id") or "") or None
    return None


@st.cache_data(ttl=30, show_spinner=False)
def list_saved_simulation_results(
    api_base: str,
    scenario_id: str,
    variant_id: str | None,
    *,
    latest: bool = False,
) -> list[dict[str, Any]]:
    """Saved simulation evidence for the scenario/variant, newest first."""

    params: dict[str, Any] = {"scenario_ref": scenario_id, "limit": 50}
    if variant_id:
        params["variant_ref"] = variant_id
    if latest:
        params["latest"] = "true"
        params["limit"] = 1
    try:
        response = requests.get(
            f"{api_base.rstrip('/')}/simulation/results",
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        return [item for item in response.json().get("items") or [] if isinstance(item, dict)]
    except Exception:
        return []


def saved_evidence_option_label(item: dict[str, Any]) -> str:
    """Compact picker label: id plus headline KPI when present."""

    evidence_id = str(item.get("id") or "")
    kpi = item.get("kpi") if isinstance(item.get("kpi"), dict) else {}
    bits = []
    power = kpi.get("total_power_mw")
    if isinstance(power, (int, float)):
        bits.append(f"{power:.1f}mW")
    critical = kpi.get("critical_path_ms")
    if isinstance(critical, (int, float)):
        bits.append(f"crit {critical:.1f}ms")
    return f"{evidence_id}  ({', '.join(bits)})" if bits else evidence_id


@st.cache_data(ttl=30, show_spinner=False)
def _load_simulation_result(api_base: str, evidence_id: str) -> dict[str, Any] | None:
    try:
        response = requests.get(
            f"{api_base.rstrip('/')}/simulation/results/{evidence_id}",
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def clear_viewer_timing_caches() -> None:
    list_saved_simulation_results.clear()
    _load_simulation_result.clear()


def render_viewer_timing_panel(
    *,
    api_base: str,
    evidence_id: str,
    expanded: bool = False,
) -> None:
    """Timeline of the overlay evidence under the pipeline diagram.

    The embedded workbench chart carries its own diagram pane, so timeline
    clicks cross-probe the topology and semantic zoom drills into modules
    without leaving the viewer.
    """

    with st.expander(f"Simulation Timing - {evidence_id}", expanded=expanded):
        result = _load_simulation_result(api_base, evidence_id)
        if result is None:
            st.warning(
                "Could not load the simulation evidence for the timing view. "
                "Check that the evidence id exists and the API is reachable."
            )
            return
        if not result.get("timeline_events"):
            st.info(
                "This evidence has no timeline events. Re-run the simulation "
                "with timeline_frame_count >= 1 to capture the schedule."
            )
            return
        render_timing_summary(result)
        render_timing_chart(result, key_prefix="viewer_timing", api_base=api_base)
