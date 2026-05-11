"""Result breakdown rendering for the Evidence Dashboard."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_dashboard_contract import RESULT_BREAKDOWN_TABS
from dashboard.components.table_actions import render_copyable_dataframe
from dashboard.components.timing_chart import render_timing_chart, render_timing_summary


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in value)[:160]


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


def _ordered_table(rows: list[dict[str, Any]], priority: list[str]) -> list[dict[str, Any]]:
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


def _table_height(rows: list[dict[str, Any]], *, row_height: int = 35) -> int:
    return max(120, row_height * (len(rows) + 1) + 12)


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
        render_copyable_dataframe(
            kpi_rows,
            key=f"debug_kpi_rows_{_safe_filename(str(result.get('id') or 'preview'))}",
            use_container_width=True,
            hide_index=True,
        )

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
        render_copyable_dataframe(
            ip_rows,
            key=f"debug_ip_rows_{_safe_filename(str(result.get('id') or 'preview'))}",
            use_container_width=True,
            hide_index=True,
        )

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
        render_copyable_dataframe(
            dma_rows,
            key=f"debug_dma_rows_{_safe_filename(str(result.get('id') or 'preview'))}",
            use_container_width=True,
            hide_index=True,
        )

    timeline = trace.get("timeline") if isinstance(trace.get("timeline"), dict) else {}
    otf_groups = timeline.get("otf_groups") if isinstance(timeline.get("otf_groups"), list) else []
    if otf_groups:
        st.markdown("**Timing / OTF group trace**")
        render_copyable_dataframe(
            otf_groups,
            key=f"debug_otf_rows_{_safe_filename(str(result.get('id') or 'preview'))}",
            use_container_width=True,
            hide_index=True,
        )
    with st.expander("Raw calculation trace", expanded=False):
        st.json(trace)


def _topology_rank(result: dict[str, Any]) -> dict[str, int]:
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


def _size_text_from_row(row: dict[str, Any]) -> str | None:
    if row.get("size"):
        return str(row["size"])
    width = _numeric(row.get("width"))
    height = _numeric(row.get("height"))
    if width and height:
        return f"{int(width)}x{int(height)}"
    return None


def _power_ma(row: dict[str, Any], result: dict[str, Any]) -> float | None:
    direct = _numeric(row.get("total_power_ma") or row.get("power_ma"))
    if direct is not None:
        return direct
    kpi = result.get("kpi") if isinstance(result.get("kpi"), dict) else {}
    total_mw = _numeric(kpi.get("total_power_mw") or kpi.get("power_mw"))
    total_ma = _numeric(kpi.get("total_power_ma") or kpi.get("power_ma"))
    power_mw = _numeric(row.get("total_power_mw") or row.get("power_mw"))
    if total_mw and total_ma is not None and power_mw is not None:
        return power_mw * total_ma / total_mw
    return None


def _ip_power_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    dvfs_rows = result.get("dvfs_breakdown") if isinstance(result.get("dvfs_breakdown"), list) else []
    if dvfs_rows:
        rows = _ordered_table(
            [
                {
                    "node_id": row.get("node_id"),
                    "hw_name": row.get("hw_name"),
                    "mode": row.get("mode"),
                    "ip_ref": row.get("ip_ref"),
                    "power_mw": row.get("total_power_mw"),
                    "power_ma": _power_ma(row, result),
                    "active_power_mw": row.get("active_power_mw"),
                    "required_clock_mhz": row.get("required_clock_mhz"),
                    "base_required_clock_mhz": row.get("base_required_clock_mhz"),
                    "clock_correction_mhz": row.get("clock_correction_mhz"),
                    "clock_correction_reason": row.get("clock_correction_reason"),
                    "set_clock_mhz": row.get("set_clock_mhz"),
                    "size": _size_text_from_row(row),
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
            [
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
            ],
        )
        if rows:
            rows.append(
                {
                    "node_id": "total",
                    "hw_name": "",
                    "mode": "",
                    "ip_ref": "",
                    "power_mw": sum(_numeric(row.get("power_mw")) or 0.0 for row in rows),
                    "power_ma": sum(_numeric(row.get("power_ma")) or 0.0 for row in rows),
                    "active_power_mw": sum(_numeric(row.get("active_power_mw")) or 0.0 for row in rows),
                }
            )
        return rows
    return _ordered_table(
        result.get("ip_breakdown") or [],
        ["ip", "instance_index", "power_mW", "submodules"],
    )


def _dma_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rank = _topology_rank(result)
    rows = [row for row in result.get("dma_breakdown") or [] if isinstance(row, dict)]
    rows.sort(
        key=lambda row: (
            rank.get(str(row.get("node_id")), 10_000),
            str(row.get("node_id") or ""),
            str(row.get("port") or ""),
        )
    )
    return _ordered_table(
        rows,
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
    )


def _external_device_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("external_devices") if isinstance(result.get("external_devices"), list) else []
    if rows:
        return _ordered_table(
            [row for row in rows if isinstance(row, dict)],
            [
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
            ],
        )
    trace = result.get("calculation_trace") if isinstance(result.get("calculation_trace"), dict) else {}
    trace_rows = trace.get("external_devices") if isinstance(trace.get("external_devices"), list) else []
    return [row for row in trace_rows if isinstance(row, dict)]


def render_result_breakdown(result: dict[str, Any], *, key_prefix: str = "stored") -> None:
    """Render all result breakdown tabs for a simulation preview or saved evidence."""

    tabs = st.tabs(list(RESULT_BREAKDOWN_TABS))
    with tabs[0]:
        rows = _external_device_rows(result)
        if not rows:
            st.info("No external sensor/display device metadata is stored for this result.")
        else:
            st.caption("Sensor/display conditions used as source/sink constraints. External devices are excluded from IP core power.")
            render_copyable_dataframe(
                rows,
                key=f"{key_prefix}_external_device_info",
                use_container_width=True,
                hide_index=True,
                height=_table_height(rows),
            )
    with tabs[1]:
        st.caption("Power is calculated per scenario node / hardware role. `ip_ref` is the catalog source and can repeat for multiple ISP roles.")
        rows = _ip_power_rows(result)
        render_copyable_dataframe(
            rows,
            key=f"{key_prefix}_ip_node_power",
            use_container_width=True,
            hide_index=True,
            height=_table_height(rows),
        )
    with tabs[2]:
        rows = _dma_rows(result)
        render_copyable_dataframe(
            rows,
            key=f"{key_prefix}_dma_bw",
            use_container_width=True,
            hide_index=True,
            height=_table_height(rows),
        )
    with tabs[3]:
        render_timing_summary(result)
        render_timing_chart(result, key_prefix=key_prefix)
    with tabs[4]:
        rows = result.get("timing_breakdown") or []
        render_copyable_dataframe(
            rows,
            key=f"{key_prefix}_timing_table",
            use_container_width=True,
            hide_index=True,
            height=_table_height(rows if isinstance(rows, list) else []),
        )
    with tabs[5]:
        rows = _ordered_table(
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
            ],
        )
        render_copyable_dataframe(
            rows,
            key=f"{key_prefix}_timeline_table",
            use_container_width=True,
            hide_index=True,
            height=_table_height(rows),
        )
    with tabs[6]:
        _render_debug_trace(result)
    with tabs[7]:
        st.json(result)
