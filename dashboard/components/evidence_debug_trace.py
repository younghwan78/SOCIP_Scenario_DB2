"""Calculation trace rendering for simulation evidence."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.table_actions import render_copyable_dataframe


def render_debug_trace(result: dict[str, Any]) -> None:
    """Render formula-level debug trace tables for a simulation result."""

    trace = result.get("calculation_trace")
    if not isinstance(trace, dict):
        st.info("No calculation trace is stored for this result. Run a simulation preview with Debug trace enabled, then confirm/save it if needed.")
        return

    st.caption("Formula-level trace for KPI, IP power/performance, DMA bandwidth, and timing scheduling inputs.")
    config = trace.get("config") if isinstance(trace.get("config"), dict) else {}
    if config:
        with st.expander("Run config used by calculations", expanded=False):
            st.json(config)

    evidence_id = _safe_filename(str(result.get("id") or "preview"))
    _render_section(
        "KPI formulas",
        kpi_trace_rows(trace),
        key=f"debug_kpi_rows_{evidence_id}",
    )
    _render_section(
        "IP power / DVFS / performance trace",
        ip_trace_rows(trace),
        key=f"debug_ip_rows_{evidence_id}",
    )
    _render_section(
        "DMA bandwidth trace",
        dma_trace_rows(trace),
        key=f"debug_dma_rows_{evidence_id}",
    )
    _render_section(
        "Timing / OTF group trace",
        otf_group_trace_rows(trace),
        key=f"debug_otf_rows_{evidence_id}",
    )
    with st.expander("Raw calculation trace", expanded=False):
        st.json(trace)


def kpi_trace_rows(trace: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, item in (trace.get("kpi") or {}).items():
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "kpi": name,
                "formula": item.get("formula"),
                "inputs": item.get("inputs"),
                "result": item.get("result"),
            }
        )
    return rows


def ip_trace_rows(trace: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in trace.get("ip") or []:
        if not isinstance(item, dict):
            continue
        required = item.get("required_clock") if isinstance(item.get("required_clock"), dict) else {}
        dvfs = item.get("dvfs") if isinstance(item.get("dvfs"), dict) else {}
        power = item.get("power") if isinstance(item.get("power"), dict) else {}
        timing = item.get("timing") if isinstance(item.get("timing"), dict) else {}
        rows.append(
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
    return rows


def dma_trace_rows(trace: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in trace.get("dma") or []:
        if not isinstance(item, dict):
            continue
        inputs = item.get("inputs") if isinstance(item.get("inputs"), dict) else {}
        intermediate = item.get("intermediate") if isinstance(item.get("intermediate"), dict) else {}
        result_values = item.get("result") if isinstance(item.get("result"), dict) else {}
        rows.append(
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
    return rows


def otf_group_trace_rows(trace: dict[str, Any]) -> list[dict[str, Any]]:
    timeline = trace.get("timeline") if isinstance(trace.get("timeline"), dict) else {}
    rows = timeline.get("otf_groups") if isinstance(timeline.get("otf_groups"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _render_section(title: str, rows: list[dict[str, Any]], *, key: str) -> None:
    if not rows:
        return
    st.markdown(f"**{title}**")
    render_copyable_dataframe(rows, key=key, use_container_width=True, hide_index=True)


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in value)[:160]
