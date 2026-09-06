"""Result breakdown rendering for the Evidence Dashboard."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_dashboard_contract import RESULT_BREAKDOWN_TABS
from dashboard.components.evidence_debug_trace import render_debug_trace
from dashboard.components.simulation_report_actions import render_simulation_report_tab
from dashboard.components.simulation_tables import (
    render_dma_bw,
    render_external_device_info,
    render_ip_node_power,
    render_timeline_table,
    render_timing_table,
)
from dashboard.components.timing_chart import render_timing_chart, render_timing_summary


def render_result_breakdown(
    result: dict[str, Any],
    *,
    key_prefix: str = "stored",
    api_base: str | None = None,
    project_ref: str | None = None,
    soc_ref: str | None = None,
) -> None:
    """Render the selected result breakdown section for a simulation evidence result."""

    evidence_id = str(result.get("id") or "simulation-evidence")
    key = f"{key_prefix}_{_safe_key(evidence_id)}_result_breakdown_view"
    current = selected_breakdown_label(st.session_state.get(key))
    selected = st.pills(
        "Result breakdown",
        options=list(RESULT_BREAKDOWN_TABS),
        default=current,
        selection_mode="single",
        key=key,
        label_visibility="collapsed",
        width="stretch",
    )
    render_selected_result_breakdown(
        result,
        selected_label=selected_breakdown_label(selected),
        key_prefix=key_prefix,
        api_base=api_base,
        project_ref=project_ref,
        soc_ref=soc_ref,
    )


def selected_breakdown_label(label: Any) -> str:
    """Return a valid breakdown label, falling back to the first contract label."""

    text = str(label or "")
    if text in RESULT_BREAKDOWN_TABS:
        return text
    return RESULT_BREAKDOWN_TABS[0]


def render_selected_result_breakdown(
    result: dict[str, Any],
    *,
    selected_label: str,
    key_prefix: str = "stored",
    api_base: str | None = None,
    project_ref: str | None = None,
    soc_ref: str | None = None,
) -> None:
    """Dispatch only the selected breakdown renderer.

    Streamlit tabs render every tab body during each rerun. Keeping this dispatch
    explicit prevents hidden heavy views such as Plotly charts and report HTML
    previews from being rebuilt while the user is looking at another section.
    """

    label = selected_breakdown_label(selected_label)
    if label == RESULT_BREAKDOWN_TABS[0]:
        render_external_device_info(result, key_prefix=key_prefix)
    elif label == RESULT_BREAKDOWN_TABS[1]:
        render_ip_node_power(result, key_prefix=key_prefix)
    elif label == RESULT_BREAKDOWN_TABS[2]:
        render_dma_bw(result, key_prefix=key_prefix)
    elif label == RESULT_BREAKDOWN_TABS[3]:
        render_timing_summary(result)
        render_timing_chart(result, key_prefix=key_prefix, api_base=api_base)
    elif label == RESULT_BREAKDOWN_TABS[4]:
        render_timing_table(result, key_prefix=key_prefix)
    elif label == RESULT_BREAKDOWN_TABS[5]:
        render_timeline_table(result, key_prefix=key_prefix)
    elif label == RESULT_BREAKDOWN_TABS[6]:
        render_simulation_report_tab(
            result,
            api_base=api_base,
            key_prefix=key_prefix,
            project_ref=project_ref,
            soc_ref=soc_ref,
        )
    elif label == RESULT_BREAKDOWN_TABS[7]:
        render_debug_trace(result)
    elif label == RESULT_BREAKDOWN_TABS[8]:
        st.json(result)


def _safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in value)[:160]
