"""Result breakdown rendering for the Evidence Dashboard."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_dashboard_contract import RESULT_BREAKDOWN_TABS
from dashboard.components.evidence_debug_trace import render_debug_trace
from dashboard.components.simulation_tables import (
    render_dma_bw,
    render_external_device_info,
    render_ip_node_power,
    render_timeline_table,
    render_timing_table,
)
from dashboard.components.timing_chart import render_timing_chart, render_timing_summary


def render_result_breakdown(result: dict[str, Any], *, key_prefix: str = "stored") -> None:
    """Render all result breakdown tabs for a simulation preview or saved evidence."""

    tabs = st.tabs(list(RESULT_BREAKDOWN_TABS))
    with tabs[0]:
        render_external_device_info(result, key_prefix=key_prefix)
    with tabs[1]:
        render_ip_node_power(result, key_prefix=key_prefix)
    with tabs[2]:
        render_dma_bw(result, key_prefix=key_prefix)
    with tabs[3]:
        render_timing_summary(result)
        render_timing_chart(result, key_prefix=key_prefix)
    with tabs[4]:
        render_timing_table(result, key_prefix=key_prefix)
    with tabs[5]:
        render_timeline_table(result, key_prefix=key_prefix)
    with tabs[6]:
        render_debug_trace(result)
    with tabs[7]:
        st.json(result)
