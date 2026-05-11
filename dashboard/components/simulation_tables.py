"""Simulation evidence table row builders and renderers."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.table_actions import render_copyable_dataframe


IP_POWER_PRIORITY = [
    "node_id",
    "hw_name",
    "mode",
    "ip_ref",
    "power_mw",
    "power_ma",
    "set_clock_mhz",
    "required_clock_mhz",
    "size",
    "format",
    "dvfs_level",
    "vdd",
    "set_voltage_mv",
    "unit_power_mw_mp",
    "active_power_mw",
    "vdd_leader",
    "ppc",
    "resolution_mp",
    "fps",
    "base_required_clock_mhz",
    "clock_correction_mhz",
    "clock_correction_reason",
]

DMA_PRIORITY = [
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
]

EXTERNAL_DEVICE_PRIORITY = [
    "device_type",
    "node_id",
    "ip_ref",
    "role",
    "place",
    "mode",
    "name",
    "size",
    "catalog_size",
    "active_size",
    "active_size_source",
    "format",
    "bitwidth",
    "fps",
    "v_valid_ms",
    "v_valid_source",
    "pclk",
    "line_length_pck",
    "phy_type",
    "mipi_speed",
    "sbwc",
    "layout",
    "refresh_hz",
    "scanout_ms",
    "panel_type",
    "ppi",
]

TIMELINE_PRIORITY = [
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
    "bottleneck_reason",
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
    "cadence_interval_ms",
    "cadence_avg_interval_ms",
    "cadence_budget_ms",
    "cadence_slack_ms",
    "cadence_violation",
    "source_fps",
    "v_valid_ms",
    "refresh_hz",
    "scanout_ms",
    "predecessors",
]


def render_external_device_info(result: dict[str, Any], *, key_prefix: str) -> None:
    rows = external_device_rows(result)
    if not rows:
        st.info("No external sensor/display device metadata is stored for this result.")
        return
    st.caption("Sensor/display conditions used as source/sink constraints. External devices are excluded from IP core power.")
    render_copyable_dataframe(rows, key=f"{key_prefix}_external_device_info", use_container_width=True, hide_index=True, height=table_height(rows))


def render_ip_node_power(result: dict[str, Any], *, key_prefix: str) -> None:
    st.caption("Power is calculated per scenario node / hardware role. `ip_ref` is the catalog source and can repeat for multiple ISP roles.")
    rows = ip_power_rows(result)
    render_copyable_dataframe(rows, key=f"{key_prefix}_ip_node_power", use_container_width=True, hide_index=True, height=table_height(rows))


def render_dma_bw(result: dict[str, Any], *, key_prefix: str) -> None:
    rows = dma_rows(result)
    render_copyable_dataframe(rows, key=f"{key_prefix}_dma_bw", use_container_width=True, hide_index=True, height=table_height(rows))


def render_timing_table(result: dict[str, Any], *, key_prefix: str) -> None:
    rows = result.get("timing_breakdown") or []
    render_copyable_dataframe(
        rows,
        key=f"{key_prefix}_timing_table",
        use_container_width=True,
        hide_index=True,
        height=table_height(rows if isinstance(rows, list) else []),
    )


def render_timeline_table(result: dict[str, Any], *, key_prefix: str) -> None:
    rows = ordered_table(result.get("timeline_events") or [], TIMELINE_PRIORITY)
    render_copyable_dataframe(rows, key=f"{key_prefix}_timeline_table", use_container_width=True, hide_index=True, height=table_height(rows))


def ip_power_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    dvfs_rows = result.get("dvfs_breakdown") if isinstance(result.get("dvfs_breakdown"), list) else []
    if dvfs_rows:
        rows = ordered_table(
            [
                {
                    "node_id": row.get("node_id"),
                    "hw_name": row.get("hw_name"),
                    "mode": row.get("mode"),
                    "ip_ref": row.get("ip_ref"),
                    "power_mw": row.get("total_power_mw"),
                    "power_ma": power_ma(row, result),
                    "active_power_mw": row.get("active_power_mw"),
                    "required_clock_mhz": row.get("required_clock_mhz"),
                    "base_required_clock_mhz": row.get("base_required_clock_mhz"),
                    "clock_correction_mhz": row.get("clock_correction_mhz"),
                    "clock_correction_reason": row.get("clock_correction_reason"),
                    "set_clock_mhz": row.get("set_clock_mhz"),
                    "size": size_text_from_row(row),
                    "format": row.get("format"),
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
            IP_POWER_PRIORITY,
        )
        if rows:
            rows.append(
                {
                    "node_id": "total",
                    "hw_name": "",
                    "mode": "",
                    "ip_ref": "",
                    "power_mw": sum(numeric(row.get("power_mw")) or 0.0 for row in rows),
                    "power_ma": sum(numeric(row.get("power_ma")) or 0.0 for row in rows),
                    "active_power_mw": sum(numeric(row.get("active_power_mw")) or 0.0 for row in rows),
                }
            )
        return rows
    return ordered_table(result.get("ip_breakdown") or [], ["ip", "instance_index", "power_mW", "submodules"])


def dma_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rank = topology_rank(result)
    rows = [row for row in result.get("dma_breakdown") or [] if isinstance(row, dict)]
    rows.sort(key=lambda row: (rank.get(str(row.get("node_id")), 10_000), str(row.get("node_id") or ""), str(row.get("port") or "")))
    return ordered_table(rows, DMA_PRIORITY)


def external_device_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("external_devices") if isinstance(result.get("external_devices"), list) else []
    if rows:
        return ordered_table([row for row in rows if isinstance(row, dict)], EXTERNAL_DEVICE_PRIORITY)
    trace = result.get("calculation_trace") if isinstance(result.get("calculation_trace"), dict) else {}
    trace_rows = trace.get("external_devices") if isinstance(trace.get("external_devices"), list) else []
    return [row for row in trace_rows if isinstance(row, dict)]


def topology_rank(result: dict[str, Any]) -> dict[str, int]:
    explicit = result.get("topology_order")
    if isinstance(explicit, list) and explicit:
        return {str(node_id): index for index, node_id in enumerate(explicit)}
    rank: dict[str, int] = {}
    for source in (result.get("timeline_events"), result.get("dvfs_breakdown"), result.get("dma_breakdown")):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            node_id = item.get("node_id")
            if node_id is not None and str(node_id) not in rank:
                rank[str(node_id)] = len(rank)
    return rank


def size_text_from_row(row: dict[str, Any]) -> str | None:
    if row.get("size"):
        return str(row["size"])
    width = numeric(row.get("width"))
    height = numeric(row.get("height"))
    if width and height:
        return f"{int(width)}x{int(height)}"
    return None


def power_ma(row: dict[str, Any], result: dict[str, Any]) -> float | None:
    direct = numeric(row.get("total_power_ma") or row.get("power_ma"))
    if direct is not None:
        return direct
    kpi = result.get("kpi") if isinstance(result.get("kpi"), dict) else {}
    total_mw = numeric(kpi.get("total_power_mw") or kpi.get("power_mw"))
    total_ma = numeric(kpi.get("total_power_ma") or kpi.get("power_ma"))
    power_mw = numeric(row.get("total_power_mw") or row.get("power_mw"))
    if total_mw and total_ma is not None and power_mw is not None:
        return power_mw * total_ma / total_mw
    return None


def ordered_table(rows: list[dict[str, Any]], priority: list[str]) -> list[dict[str, Any]]:
    ordered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {key: row.get(key) for key in priority if key in row}
        for key, value in row.items():
            if key not in item:
                item[key] = value
        ordered.append(item)
    return ordered


def table_height(rows: list[dict[str, Any]], *, row_height: int = 35) -> int:
    return max(120, row_height * (len(rows) + 1) + 12)


def numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
