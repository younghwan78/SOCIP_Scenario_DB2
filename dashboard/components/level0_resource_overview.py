"""Level 0 resource overview tables for the Pipeline Viewer."""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from scenario_db.api.schemas.view import IoSummary, ViewResponse


DOMAIN_LABELS = {
    "external_source": "External Source",
    "soc_resource": "SoC Resource",
    "memory": "Buffer / Memory",
    "external_sink": "External Sink",
}

SUBSYSTEM_ROW_COLORS = {
    "camera": "#EAF6F0",
    "display": "#EDF4FF",
    "video": "#FFF4E6",
    "audio": "#F5F0FF",
    "ai": "#EEFDF6",
    "game": "#F0F9FF",
    "compute": "#F7F8FA",
    "memory": "#ECFDF9",
}


def render_level0_resource_overview(view: ViewResponse) -> None:
    """Render the resource-first Level 0 overview when the API provides it."""

    if not view.level0_resource_overview:
        return

    st.markdown("#### Scenario Resource Overview")
    resource_rows = resource_overview_rows(view)
    buffer_rows = buffer_handoff_rows(view)
    sensor_rows = sensor_summary_rows(view)
    display_rows = display_summary_rows(view)
    layer_rows = display_layer_rows(view)
    metric_rows = metric_breakdown_rows(view)

    if resource_rows:
        st.dataframe(styled_resource_overview(resource_rows), use_container_width=True, hide_index=True)

    if metric_rows:
        st.markdown("#### Subsystem Summary")
        st.dataframe(metric_rows, use_container_width=True, hide_index=True)

    endpoint_tabs = st.tabs(["Buffers", "Sensor", "Display"])
    with endpoint_tabs[0]:
        if buffer_rows:
            st.dataframe(buffer_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No active buffer handoff in this projection.")
    with endpoint_tabs[1]:
        if sensor_rows:
            st.dataframe(sensor_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No sensor endpoint summary in this projection.")
    with endpoint_tabs[2]:
        if display_rows:
            st.dataframe(display_rows, use_container_width=True, hide_index=True)
            if layer_rows:
                st.dataframe(layer_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No display composition summary in this projection.")


def resource_overview_rows(view: ViewResponse) -> list[dict[str, str]]:
    overview = view.level0_resource_overview
    if not overview:
        return []
    return [
        {
            "Step": str(row.sequence_index),
            "Domain": DOMAIN_LABELS.get(row.resource_domain, row.resource_domain),
            "Resource": row.label,
            "Kind": row.resource_kind.upper(),
            "Subsystem": row.subsystem,
            "Input": _io_text(row.input),
            "Output": _io_text(row.output),
            "Flow": row.flow,
            "Buffers": ", ".join(row.buffer_refs),
            "Badges": " | ".join(row.badges),
            "Status": row.status,
        }
        for row in overview.rows
    ]


def styled_resource_overview(rows: list[dict[str, str]]):
    return pd.DataFrame(rows).style.apply(resource_overview_row_style, axis=1)


def resource_overview_row_style(row: Any) -> list[str]:
    subsystem = str(_row_value(row, "Subsystem") or "").lower()
    bg = SUBSYSTEM_ROW_COLORS.get(subsystem, "#FFFFFF")
    css = f"background-color: {bg}; color: #1F2937;"
    return [css for _ in range(len(row))]


def _row_value(row: Any, key: str) -> Any:
    if hasattr(row, "get"):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, TypeError):
        return None


def buffer_handoff_rows(view: ViewResponse) -> list[dict[str, str]]:
    overview = view.level0_resource_overview
    if not overview:
        return []
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in overview.rows:
        for buffer_ref in row.buffer_refs:
            key = (row.node_id, buffer_ref)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "Buffer": buffer_ref,
                    "Producer": row.node_id,
                    "Subsystem": row.subsystem,
                    "Output": _io_text(row.output),
                }
            )
    return rows


def sensor_summary_rows(view: ViewResponse) -> list[dict[str, str]]:
    overview = view.level0_resource_overview
    if not overview:
        return []
    return [
        {
            "Sensor": sensor.node_id,
            "Mode": _text(sensor.sensor_mode),
            "Module": _text(sensor.module_ref),
            "Output": _io_text(sensor.output),
            "Downstream": ", ".join(sensor.downstream),
        }
        for sensor in overview.sensors
    ]


def display_summary_rows(view: ViewResponse) -> list[dict[str, str]]:
    overview = view.level0_resource_overview
    if not overview:
        return []
    return [
        {
            "Display": display.node_id,
            "Composer": _text(display.composer),
            "Layers": _text(display.layer_count),
            "Panel Mode": _text(display.panel_mode),
            "Output": _io_text(display.output),
        }
        for display in overview.displays
    ]


def display_layer_rows(view: ViewResponse) -> list[dict[str, str]]:
    overview = view.level0_resource_overview
    if not overview:
        return []
    rows: list[dict[str, str]] = []
    for display in overview.displays:
        for layer in display.layers:
            rows.append(
                {
                    "Display": display.node_id,
                    "Layer": layer.name,
                    "Buffer": _text(layer.buffer_ref),
                    "Format": _text(layer.format),
                    "Src": _text(layer.src_frame),
                    "Dst": _text(layer.dst_frame),
                    "Transform": _text(layer.transform),
                }
            )
    return rows


def metric_breakdown_rows(view: ViewResponse) -> list[dict[str, str]]:
    overview = view.level0_resource_overview
    if not overview:
        return []
    return [
        {
            "Subsystem": metric.subsystem,
            "Nodes": str(metric.node_count),
            "Power": _number(metric.power_mw, "mW"),
            "BW": _number(metric.bw_total_mbs, "MB/s"),
            "HW Time": _number(metric.hw_time_ms, "ms"),
            "Warnings": str(metric.warning_count),
        }
        for metric in overview.metric_breakdown
    ]


def _io_text(io: IoSummary | None) -> str:
    if io is None:
        return "-"
    bits: list[str] = []
    if io.width and io.height:
        size = f"{io.width}x{io.height}"
        if io.fps is not None:
            size = f"{size} @ {_num_text(io.fps)}fps"
        bits.append(size)
    elif io.size_label:
        bits.append(str(io.size_label))
    for value in (io.format, f"{io.bitdepth}b" if io.bitdepth is not None else None, io.compression):
        if value:
            bits.append(str(value))
    return " / ".join(bits) if bits else "-"


def _number(value: Any, suffix: str) -> str:
    if value is None:
        return "-"
    return f"{_num_text(value)} {suffix}"


def _num_text(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{numeric:g}"


def _text(value: Any) -> str:
    if value is None:
        return "-"
    return str(value)
