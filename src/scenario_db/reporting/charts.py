from __future__ import annotations

from typing import Any


def timing_chart_records(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for event in _events(evidence):
        frame = event.get("frame_index")
        otf_group = _base_group(event.get("otf_group_id"))
        rows.append(
            {
                "task_id": str(event.get("task_id") or ""),
                "node_id": str(event.get("node_id") or ""),
                "hw_name": str(event.get("hw_name") or event.get("node_id") or "task"),
                "label": _timing_label(event, include_frame=frame is not None),
                "frame_index": frame,
                "start_ms": _float(event.get("start_ms")),
                "end_ms": _float(event.get("end_ms")),
                "duration_ms": _duration(event),
                "task_type": str(event.get("task_type") or ""),
                "constraint_type": event.get("constraint_type"),
                "edge_type": str(event.get("edge_type") or ""),
                "otf_group_id": otf_group,
                "critical": bool(event.get("critical")),
                "hover": _timing_hover(event),
            }
        )
    return sorted(
        rows,
        key=lambda row: (row["frame_index"] or 0, row["start_ms"], row["end_ms"], row["label"]),
    )


def bw_chart_records(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    event_by_node = _timeline_window_by_node(evidence)
    rows = []
    for item in _dict_rows(evidence.get("dma_breakdown")):
        node_id = str(item.get("node_id") or "")
        window = event_by_node.get(node_id)
        if window is None:
            continue
        direction = str(item.get("direction") or "").lower()
        bw_mbs = _float(item.get("bw_mbs"))
        rows.append(
            {
                "node_id": node_id,
                "hw_name": str(item.get("hw_name") or node_id),
                "port": str(item.get("port") or ""),
                "direction": "Read" if direction == "read" else "Write" if direction == "write" else "OTF",
                "start_ms": window["start_ms"],
                "end_ms": window["end_ms"],
                "duration_ms": max(0.0, window["end_ms"] - window["start_ms"]),
                "frame_index": window.get("frame_index"),
                "bw_mbs": bw_mbs,
                "bw_gbps": bw_mbs / 1000.0,
                "bw_power_mw": _float(item.get("bw_power_mw")),
                "bw_power_ma": _float(item.get("bw_power_ma")),
            }
        )
    rank = {str(node): index for index, node in enumerate(evidence.get("topology_order") or [])}
    return sorted(
        rows,
        key=lambda row: (row["frame_index"] or 0, rank.get(row["node_id"], 10_000), row["start_ms"], row["port"]),
    )


def timing_sequence_annotations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotations = []
    for _, frame_rows in _records_by_frame(records).items():
        ordered = sorted(frame_rows, key=lambda row: (row["start_ms"], row["end_ms"], row["label"]))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current["start_ms"] < previous["end_ms"]:
                continue
            annotations.append(
                {
                    "x": current["start_ms"],
                    "y": current["label"],
                    "ax": previous["end_ms"],
                    "ay": previous["label"],
                    "xref": "x",
                    "yref": "y",
                    "axref": "x",
                    "ayref": "y",
                    "showarrow": True,
                    "arrowhead": 2,
                    "arrowwidth": 1,
                    "arrowcolor": "#64748B",
                    "opacity": 0.8,
                }
            )
    return annotations


def timing_frame_bands(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bands = []
    colors = ("#F8FAFC", "#EAF2FF")
    for index, (frame, frame_rows) in enumerate(_records_by_frame(records).items()):
        bands.append(
            {
                "frame_index": frame,
                "x0": min(row["start_ms"] for row in frame_rows),
                "x1": max(row["end_ms"] for row in frame_rows),
                "fillcolor": colors[index % len(colors)],
            }
        )
    return bands


def timing_frame_separator_lines(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _records_by_frame(records)
    if len(grouped) <= 1:
        return []
    max_end = max((row["end_ms"] for row in records), default=0.0)
    return [
        {
            "label": _frame_separator_label(frame),
            "x0": 0.0,
            "x1": max_end,
        }
        for index, frame in enumerate(grouped)
        if index > 0
    ]


def timing_yaxis_category_order(records: list[dict[str, Any]]) -> list[str]:
    categories = []
    grouped = _records_by_frame(records)
    for index, (frame, frame_rows) in enumerate(grouped.items()):
        if index > 0:
            categories.append(_frame_separator_label(frame))
        for row in sorted(frame_rows, key=lambda item: (item["start_ms"], item["end_ms"], item["label"])):
            if row["label"] not in categories:
                categories.append(row["label"])
    return categories


def timeline_tick_ms(max_end_ms: float) -> int:
    return 5 if max_end_ms <= 50 else 10


def bw_axis_max_gbps(records: list[dict[str, Any]]) -> float:
    peak = max(_instantaneous_bw_peak_gbps(records), max((row["bw_gbps"] for row in records), default=0.0))
    for bucket in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0):
        if peak <= bucket:
            return bucket
    return float(int(peak) + 1)


def generate_timing_chart_html(evidence: dict[str, Any], *, title: str) -> str:
    import plotly.graph_objects as go

    records = timing_chart_records(evidence)
    if not records:
        return _empty_html(title, "No timeline events are available. Run simulation with timeline enabled.")

    fig = go.Figure()
    colors = _timing_colors()
    legend_seen: set[str] = set()
    for row in records:
        color = _timing_color(row, colors)
        legend = _timing_legend(row)
        fig.add_trace(
            go.Bar(
                x=[row["duration_ms"]],
                y=[row["label"]],
                base=[row["start_ms"]],
                orientation="h",
                name=legend,
                marker={
                    "color": color,
                    "line": {
                        "color": "#B91C1C" if row["critical"] else color,
                        "width": 2 if row["critical"] else 0,
                    },
                },
                hovertemplate=row["hover"] + "<extra></extra>",
                text=row["task_id"].split("#f", 1)[0],
                textposition="inside",
                showlegend=legend not in legend_seen,
            )
        )
        legend_seen.add(legend)
    for separator in timing_frame_separator_lines(records):
        fig.add_trace(
            go.Scatter(
                x=[separator["x0"], separator["x1"]],
                y=[separator["label"], separator["label"]],
                mode="lines",
                line={"color": "#94A3B8", "width": 2, "dash": "dash"},
                hoverinfo="skip",
                showlegend=False,
            )
        )
    for band in timing_frame_bands(records):
        fig.add_vrect(
            x0=band["x0"],
            x1=band["x1"],
            fillcolor=band["fillcolor"],
            opacity=0.45,
            line_width=0,
            layer="below",
        )
        if band["x0"] > 0:
            fig.add_vline(x=band["x0"], line_color="#CBD5E1", line_dash="dash", line_width=1)
    max_end_ms = max((row["end_ms"] for row in records), default=0.0)
    fig.update_layout(
        title=title,
        xaxis_title="Time (ms)",
        yaxis_title="Hardware",
        barmode="overlay",
        height=max(420, min(1100, 300 + len({row["label"] for row in records}) * 40)),
        margin={"t": 60, "r": 160, "b": 40, "l": 120},
        annotations=timing_sequence_annotations(records),
    )
    fig.update_xaxes(rangemode="tozero", showgrid=True, gridcolor="#D7DEE8", dtick=timeline_tick_ms(max_end_ms), tick0=0)
    fig.update_yaxes(
        autorange="reversed",
        categoryorder="array",
        categoryarray=timing_yaxis_category_order(records),
    )
    return fig.to_html(full_html=True, include_plotlyjs="cdn")


def generate_bw_chart_html(evidence: dict[str, Any], *, title: str) -> str:
    from plotly.subplots import make_subplots

    records = bw_chart_records(evidence)
    if not records:
        return _empty_html(title, "No DMA timeline records are available. Run simulation with timeline enabled.")

    ips = _unique(row["hw_name"] for row in records)
    total_power_mw = sum(row["bw_power_mw"] for row in records)
    total_power_ma = sum(row["bw_power_ma"] for row in records)
    total_bw_gbps = sum(row["bw_gbps"] for row in records)
    subplot_titles = [f"Total BW (Avg: {total_bw_gbps:.2f} GB/s, Power: {total_power_mw:.1f} mW / {total_power_ma:.1f} mA)"]
    for ip in ips:
        ip_rows = [row for row in records if row["hw_name"] == ip]
        subplot_titles.append(
            f"{ip} BW ({sum(row['bw_gbps'] for row in ip_rows):.2f} GB/s, "
            f"{sum(row['bw_power_mw'] for row in ip_rows):.1f} mW / "
            f"{sum(row['bw_power_ma'] for row in ip_rows):.1f} mA)"
        )

    fig = make_subplots(
        rows=1 + len(ips),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=subplot_titles,
    )
    palette = _bw_palettes()
    _add_bw_traces(fig, records, row=1, show_legend=True, palette=palette)
    for index, ip in enumerate(ips, start=2):
        _add_bw_traces(fig, [row for row in records if row["hw_name"] == ip], row=index, show_legend=False, palette=palette)

    y_max = bw_axis_max_gbps(records)
    for row_index in range(1, 2 + len(ips)):
        fig.update_yaxes(title_text="GB/s", range=[0, y_max], dtick=0.5 if y_max <= 3.0 else 1.0, row=row_index, col=1)
    fig.update_xaxes(title_text="Time (ms)", row=1 + len(ips), col=1)
    fig.update_layout(
        title=title,
        barmode="stack",
        height=260 + (1 + len(ips)) * 360,
        showlegend=True,
        legend={"orientation": "v", "yanchor": "top", "y": 1.0, "xanchor": "left", "x": 1.02, "font": {"size": 9}},
        margin={"t": 70, "r": 220, "b": 40, "l": 70},
    )
    return fig.to_html(full_html=True, include_plotlyjs="cdn")


def _add_bw_traces(
    fig: Any,
    records: list[dict[str, Any]],
    *,
    row: int,
    show_legend: bool,
    palette: dict[str, list[str]],
) -> None:
    import plotly.graph_objects as go

    for index, item in enumerate(records):
        direction = item["direction"]
        colors = palette["read"] if direction == "Read" else palette["write"]
        color = colors[index % len(colors)]
        fig.add_trace(
            go.Bar(
                x=[(item["start_ms"] + item["end_ms"]) / 2.0],
                y=[item["bw_gbps"]],
                width=[item["duration_ms"]],
                name=f"{item['port']} ({direction[:1]})",
                marker={"color": color, "line": {"color": color.replace("0.75", "1.0"), "width": 1}},
                showlegend=show_legend,
                hovertemplate=(
                    f"{item['hw_name']} / {item['port']}<br>"
                    f"Direction: {direction}<br>"
                    f"BW: {item['bw_gbps']:.2f} GB/s ({item['bw_mbs']:.1f} MB/s)<br>"
                    f"Start: {item['start_ms']:.3f} ms<br>"
                    f"End: {item['end_ms']:.3f} ms<br>"
                    f"Duration: {item['duration_ms']:.3f} ms<br>"
                    f"Power: {item['bw_power_mw']:.2f} mW / {item['bw_power_ma']:.2f} mA<br>"
                    f"Frame: {item['frame_index'] if item['frame_index'] is not None else '-'}"
                    "<extra></extra>"
                ),
            ),
            row=row,
            col=1,
        )


def _records_by_frame(records: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in records:
        frame = row.get("frame_index")
        frame_key = int(frame) if frame is not None else 0
        grouped.setdefault(frame_key, []).append(row)
    return dict(sorted(grouped.items()))


def _instantaneous_bw_peak_gbps(records: list[dict[str, Any]]) -> float:
    events = []
    for row in records:
        start = _float(row.get("start_ms"))
        end = _float(row.get("end_ms"))
        bw = _float(row.get("bw_gbps"))
        if end <= start or bw <= 0:
            continue
        events.append((start, 1, bw))
        events.append((end, 0, -bw))
    current = 0.0
    peak = 0.0
    for _, _, delta in sorted(events):
        current += delta
        peak = max(peak, current)
    return peak


def _timeline_window_by_node(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for event in _events(evidence):
        node_id = str(event.get("node_id") or "")
        if not node_id or node_id in result:
            continue
        result[node_id] = {
            "start_ms": _float(event.get("start_ms")),
            "end_ms": _float(event.get("end_ms")),
            "frame_index": event.get("frame_index"),
        }
    return result


def _events(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return _dict_rows(evidence.get("timeline_events"))


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _timing_label(event: dict[str, Any], *, include_frame: bool) -> str:
    name = str(event.get("hw_name") or event.get("node_id") or event.get("task_id") or "task")
    prefix = f"F{event.get('frame_index')} / " if include_frame else ""
    if event.get("constraint_type") == "source":
        return prefix + "Sensor In"
    if event.get("constraint_type") == "sink":
        return prefix + "Display Out"
    group = _base_group(event.get("otf_group_id"))
    return prefix + (group or name)


def _frame_separator_label(frame: int) -> str:
    return f"---- Frame {frame} start ----"


def _base_group(value: Any) -> str | None:
    if not value:
        return None
    return str(value).split("#f", 1)[0]


def _duration(event: dict[str, Any]) -> float:
    duration = _float(event.get("duration_ms"))
    if duration:
        return duration
    return max(0.0, _float(event.get("end_ms")) - _float(event.get("start_ms")))


def _timing_hover(event: dict[str, Any]) -> str:
    return "<br>".join(
        [
            f"task: {event.get('task_id') or '-'}",
            f"node: {event.get('node_id') or '-'}",
            f"hw: {event.get('hw_name') or '-'}",
            f"start: {_float(event.get('start_ms')):.3f} ms",
            f"end: {_float(event.get('end_ms')):.3f} ms",
            f"duration: {_duration(event):.3f} ms",
            f"edge: {event.get('edge_type') or '-'}",
        ]
    )


def _timing_legend(row: dict[str, Any]) -> str:
    if row["constraint_type"] == "source":
        return "Sensor In"
    if row["constraint_type"] == "sink":
        return "Display Out"
    if row["otf_group_id"]:
        return f"OTF {row['otf_group_id']}"
    if row["edge_type"].upper() == "M2M":
        return "M2M"
    if "sw" in row["task_type"].lower():
        return "SW"
    return "HW"


def _timing_color(row: dict[str, Any], colors: dict[str, str]) -> str:
    legend = _timing_legend(row)
    if legend.startswith("OTF"):
        return colors["otf"]
    return colors.get(legend.lower().replace(" ", "_"), colors["hw"])


def _timing_colors() -> dict[str, str]:
    return {
        "sensor_in": "#22C55E",
        "display_out": "#0EA5E9",
        "otf": "#2F6F68",
        "m2m": "#D97706",
        "sw": "#9333EA",
        "hw": "#64748B",
    }


def _bw_palettes() -> dict[str, list[str]]:
    return {
        "read": [
            "rgba(33, 113, 181, 0.75)",
            "rgba(35, 139, 69, 0.75)",
            "rgba(66, 146, 198, 0.75)",
            "rgba(49, 163, 84, 0.75)",
        ],
        "write": [
            "rgba(228, 26, 28, 0.75)",
            "rgba(255, 191, 0, 0.75)",
            "rgba(227, 74, 51, 0.75)",
            "rgba(255, 127, 0, 0.75)",
        ],
    }


def _unique(values: Any) -> list[str]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _empty_html(title: str, message: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body><h1>{title}</h1><p>{message}</p></body></html>"
    )


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
