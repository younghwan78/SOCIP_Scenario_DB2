"""Timing summary and chart rendering for simulation evidence."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.table_actions import render_copyable_dataframe


OTF_COLOR_FAMILIES = [
    ["#2F6F68", "#3D8A82", "#75B2A8", "#B9D2CC"],
    ["#0F766E", "#14B8A6", "#2DD4BF", "#5EEAD4"],
    ["#7C3AED", "#8B5CF6", "#A78BFA", "#C4B5FD"],
    ["#059669", "#10B981", "#34D399", "#6EE7B7"],
    ["#0284C7", "#0EA5E9", "#38BDF8", "#7DD3FC"],
]
M2M_COLOR_FAMILIES = ["#D97706", "#EA580C", "#BE123C", "#A16207", "#C2410C"]
SW_COLOR_FAMILIES = ["#9333EA", "#C026D3", "#DB2777", "#7E22CE"]


def render_timing_summary(result: dict[str, Any]) -> None:
    events = timeline_events(result)
    kpi = result.get("kpi") if isinstance(result.get("kpi"), dict) else {}
    if not events:
        st.info("No timeline events are available for this evidence.")
        return

    end_ms = numeric(kpi.get("timeline_end_ms"))
    if end_ms is None:
        end_ms = max((numeric(event.get("end_ms")) or 0.0 for event in events), default=0.0)
    critical_ms = numeric(kpi.get("critical_path_ms"))
    critical_count = numeric(kpi.get("critical_path_task_count"))
    resource_wait_event = max(events, key=lambda event: numeric(event.get("resource_wait_ms")) or 0.0)
    token_wait_event = max(events, key=lambda event: numeric(event.get("token_wait_ms")) or 0.0)
    slack_events = [event for event in events if numeric(event.get("slack_ms")) is not None]
    tightest_slack_event = min(slack_events, key=lambda event: numeric(event.get("slack_ms")) or 0.0) if slack_events else None
    cadence_events = [
        event
        for event in events
        if numeric(event.get("cadence_avg_interval_ms")) is not None and numeric(event.get("cadence_budget_ms")) is not None
    ]
    tightest_cadence_event = (
        min(cadence_events, key=lambda event: numeric(event.get("cadence_slack_ms")) or 0.0)
        if cadence_events
        else None
    )
    source_events = [
        event
        for event in events
        if event.get("constraint_type") == "source" or numeric(event.get("v_valid_ms")) is not None
    ]
    sink_events = [
        event
        for event in events
        if event.get("constraint_type") == "sink" or numeric(event.get("scanout_ms")) is not None
    ]

    cols = st.columns(4)
    cols[0].metric("Timeline End", format_ms(end_ms))
    critical_detail = f"{int(critical_count)} tasks" if critical_count is not None else "-"
    cols[1].metric("Critical Path", format_ms(critical_ms), help=critical_detail)
    cols[2].metric("Max Resource Wait", format_ms(resource_wait_event.get("resource_wait_ms")), help=event_id(resource_wait_event))
    cols[3].metric("Max Token Wait", format_ms(token_wait_event.get("token_wait_ms")), help=event_id(token_wait_event))

    cols = st.columns(3)
    if tightest_slack_event:
        cols[0].metric("Tightest Slack", format_ms(tightest_slack_event.get("slack_ms")), help=event_id(tightest_slack_event))
    else:
        cols[0].metric("Tightest Slack", "-")
    if source_events:
        source = source_events[0]
        cols[1].metric(
            "Source Window",
            format_ms(source.get("v_valid_ms") or source.get("duration_ms")),
            help=f"{event_id(source)} / fps={format_value(source.get('source_fps'))}",
        )
    else:
        cols[1].metric("Source Window", "-")
    if tightest_cadence_event:
        cols[2].metric(
            "Output Cadence Slack",
            format_ms(tightest_cadence_event.get("cadence_slack_ms")),
            help=(
                f"{event_id(tightest_cadence_event)} / "
                f"avg interval={format_ms(tightest_cadence_event.get('cadence_avg_interval_ms'))} / "
                f"budget={format_ms(tightest_cadence_event.get('cadence_budget_ms'))}"
            ),
        )
    elif sink_events:
        sink = min(sink_events, key=lambda event: numeric(event.get("slack_ms")) or 0.0)
        cols[2].metric(
            "Sink Latency Slack",
            format_ms(sink.get("slack_ms")),
            help=f"{event_id(sink)} / deadline={format_ms(sink.get('deadline_ms'))}",
        )
    else:
        cols[2].metric("Output Cadence Slack", "-")


def render_timing_chart(result: dict[str, Any], *, key_prefix: str = "stored") -> None:
    events = timeline_events(result)
    if not events:
        st.info("No timeline events are available for chart rendering.")
        return
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.warning("Plotly is not installed in this environment. The timeline table is shown instead.")
        render_copyable_dataframe(events, key=f"{key_prefix}_timing_chart_fallback", use_container_width=True, hide_index=True)
        return

    evidence_id = safe_filename(str(result.get("id") or "selected"))
    frame_values = sorted({int(value) for value in (numeric(event.get("frame_index")) for event in events) if value is not None})
    if len(frame_values) > 1:
        frame_options = ["All", *[str(value) for value in frame_values]]
        frame_choice = st.selectbox("Frame", frame_options, key=f"{key_prefix}_timing_chart_frame_{evidence_id}", index=0)
    else:
        frame_choice = "All"
    show_waits = st.checkbox("Show queue waits", value=True, key=f"{key_prefix}_timing_chart_waits_{evidence_id}")
    show_deadlines = st.checkbox("Show deadlines", value=True, key=f"{key_prefix}_timing_chart_deadlines_{evidence_id}")
    render_timing_chart_metrics(events)

    event_order = {id(event): index for index, event in enumerate(events)}
    visible_events = events
    if frame_choice != "All":
        frame_index = int(frame_choice)
        visible_events = [
            event
            for event in events
            if numeric(event.get("frame_index")) is not None and int(numeric(event.get("frame_index")) or 0) == frame_index
        ]
    visible_events = sorted(
        visible_events,
        key=lambda event: (
            numeric(event.get("frame_index")) or 0.0,
            numeric(event.get("start_ms")) or 0.0,
            event_order.get(id(event), 0),
        ),
    )
    include_frame = frame_choice == "All" and len(frame_values) > 1
    labels = [event_label(event, include_frame=include_frame) for event in visible_events]
    fig = go.Figure()
    legend_seen: set[str] = set()

    for label, event in zip(labels, visible_events, strict=False):
        start = numeric(event.get("start_ms")) or 0.0
        end = numeric(event.get("end_ms"))
        duration = numeric(event.get("duration_ms"))
        if duration is None and end is not None:
            duration = max(0.0, end - start)
        duration = duration or 0.0
        color = timeline_chart_color(event)
        segment_name = timeline_legend_name(event)
        showlegend = segment_name not in legend_seen
        legend_seen.add(segment_name)
        fig.add_trace(
            go.Bar(
                x=[duration],
                y=[label],
                base=[start],
                orientation="h",
                name=segment_name,
                marker={
                    "color": color,
                    "line": {"color": "#B91C1C" if event.get("critical") else color, "width": 2 if event.get("critical") else 0},
                },
                hovertext=[timeline_hover(event)],
                hoverinfo="text",
                showlegend=showlegend,
            )
        )

        if show_waits:
            _add_wait_segments(fig, event, label, legend_seen)

    if show_deadlines:
        _add_deadline_markers(fig, visible_events, labels)

    height = max(420, min(900, 120 + 30 * max(1, len(labels))))
    fig.update_layout(
        height=height,
        barmode="overlay",
        bargap=0.28,
        margin={"l": 16, "r": 16, "t": 24, "b": 32},
        xaxis_title="Time (ms)",
        yaxis_title="Task",
        legend_title_text="Segment",
        hovermode="closest",
    )
    fig.update_xaxes(rangemode="tozero", showgrid=True, gridcolor="#E5E7EB")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_timing_chart_plot_{evidence_id}_{frame_choice}")
    render_timing_issue_tables(visible_events, key_prefix=key_prefix)


def render_timing_chart_metrics(events: list[dict[str, Any]]) -> None:
    outputs = timeline_frame_outputs(events)
    if not outputs:
        return
    preferred = next((item for item in outputs if item["frame_index"] == 1), outputs[0])
    intervals = [
        {"from": previous["frame_index"], "to": current["frame_index"], "interval_ms": current["output_ms"] - previous["output_ms"]}
        for previous, current in zip(outputs, outputs[1:], strict=False)
    ]

    cols = st.columns(3)
    cols[0].metric(
        f"Frame {preferred['frame_index']} Latency",
        format_ms(preferred["latency_ms"]),
        help=f"start={format_ms(preferred['start_ms'])} / output={format_ms(preferred['output_ms'])} / task={preferred['output_task']}",
    )
    if intervals:
        avg_interval = sum(item["interval_ms"] for item in intervals) / len(intervals)
        last_interval = intervals[-1]
        cols[1].metric("Avg Output Interval", format_ms(avg_interval), help=f"{len(intervals)} intervals across {len(outputs)} frames")
        cols[2].metric(f"F{last_interval['from']} -> F{last_interval['to']} Interval", format_ms(last_interval["interval_ms"]))
    else:
        cols[1].metric("Avg Output Interval", "-")
        cols[2].metric("Last Output Interval", "-")


def render_timing_issue_tables(visible_events: list[dict[str, Any]], *, key_prefix: str) -> None:
    critical_rows = ordered_table(
        [event for event in visible_events if event.get("critical")],
        [
            "critical_path_rank",
            "task_id",
            "node_id",
            "resource_id",
            "edge_type",
            "otf_group_id",
            "bottleneck",
            "bottleneck_reason",
            "frame_index",
            "start_ms",
            "end_ms",
            "duration_ms",
            "resource_wait_ms",
            "token_wait_ms",
            "slack_ms",
            "cadence_interval_ms",
            "cadence_avg_interval_ms",
            "cadence_budget_ms",
            "cadence_slack_ms",
            "cadence_violation",
        ],
    )
    issue_rows = ordered_table(
        sorted(
            visible_events,
            key=lambda event: (
                -((numeric(event.get("resource_wait_ms")) or 0.0) + (numeric(event.get("token_wait_ms")) or 0.0)),
                numeric(event.get("slack_ms")) if numeric(event.get("slack_ms")) is not None else 1e12,
            ),
        )[:12],
        [
            "task_id",
            "node_id",
            "resource_id",
            "frame_index",
            "resource_wait_ms",
            "token_wait_ms",
            "deadline_ms",
            "slack_ms",
            "cadence_interval_ms",
            "cadence_avg_interval_ms",
            "cadence_slack_ms",
            "cadence_violation",
            "bottleneck_reason",
            "predecessors",
        ],
    )
    st.caption("Critical path")
    render_copyable_dataframe(critical_rows, key=f"{key_prefix}_critical_path_rows", use_container_width=True, hide_index=True)
    st.caption("Top wait/slack candidates")
    render_copyable_dataframe(issue_rows, key=f"{key_prefix}_wait_slack_rows", use_container_width=True, hide_index=True)


def timeline_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in result.get("timeline_events") or [] if isinstance(row, dict)]


def event_id(event: dict[str, Any]) -> str:
    return str(event.get("task_id") or event.get("node_id") or event.get("hw_name") or "task")


def event_label(event: dict[str, Any], *, include_frame: bool) -> str:
    name = event_id(event)
    resource = event.get("resource_id") or event.get("task_type") or event.get("constraint_type")
    if resource and resource not in name:
        name = f"{resource} / {name}"
    if include_frame and event.get("frame_index") is not None:
        name = f"F{event.get('frame_index')} / {name}"
    return name


def constraint_label(event: dict[str, Any]) -> str:
    if event.get("constraint_type"):
        return str(event.get("constraint_type"))
    task_type = str(event.get("task_type") or "")
    if task_type:
        return task_type
    return "task"


def base_task_id(task_id: Any) -> str:
    return str(task_id or "").split("#f", 1)[0]


def base_otf_group_id(group_id: Any) -> str | None:
    if not group_id:
        return None
    return str(group_id).split("#f", 1)[0]


def timeline_group_index(value: str | None, fallback: str) -> int:
    text = value or fallback
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return int(digits)
    return sum(ord(ch) for ch in text)


def timeline_chart_color(event: dict[str, Any]) -> str:
    constraint = event.get("constraint_type")
    if constraint == "source":
        return "#22C55E"
    task_type = str(event.get("task_type") or "").lower()
    if "sw" in task_type:
        index = timeline_group_index(str(event.get("resource_id") or ""), base_task_id(event.get("task_id")))
        return SW_COLOR_FAMILIES[index % len(SW_COLOR_FAMILIES)]
    edge_type = str(event.get("edge_type") or "").lower()
    otf_group = base_otf_group_id(event.get("otf_group_id"))
    if "otf" in edge_type or otf_group:
        family = OTF_COLOR_FAMILIES[timeline_group_index(otf_group, otf_group or "") % len(OTF_COLOR_FAMILIES)]
        shade_index = timeline_group_index(None, base_task_id(event.get("task_id"))) % len(family)
        return family[shade_index]
    if constraint == "sink":
        return "#0EA5E9"
    if "dma" in task_type or "m2m" in task_type:
        index = timeline_group_index(str(event.get("resource_id") or edge_type), base_task_id(event.get("task_id")))
        return M2M_COLOR_FAMILIES[index % len(M2M_COLOR_FAMILIES)]
    if "dma" in edge_type or "m2m" in edge_type:
        index = timeline_group_index(str(event.get("resource_id") or ""), base_task_id(event.get("task_id")))
        return M2M_COLOR_FAMILIES[index % len(M2M_COLOR_FAMILIES)]
    return "#64748B"


def timeline_legend_name(event: dict[str, Any]) -> str:
    constraint = event.get("constraint_type")
    if constraint == "source":
        return "Sensor In"
    if constraint == "sink":
        return "Display Out"
    task_type = str(event.get("task_type") or "").lower()
    if "sw" in task_type:
        return "SW"
    otf_group = base_otf_group_id(event.get("otf_group_id"))
    edge_type = str(event.get("edge_type") or "").upper()
    if "OTF" in edge_type or otf_group:
        return f"OTF {otf_group}" if otf_group else "OTF"
    if "M2M" in edge_type or "dma" in task_type or "m2m" in task_type:
        resource = event.get("resource_id")
        return f"M2M {resource}" if resource else "M2M"
    return constraint_label(event).title()


def timeline_hover(event: dict[str, Any]) -> str:
    lines = [
        f"task: {event_id(event)}",
        f"node: {event.get('node_id') or '-'}",
        f"type: {event.get('task_type') or event.get('constraint_type') or '-'}",
        f"edge: {event.get('edge_type') or '-'}",
        f"otf_group: {event.get('otf_group_id') or '-'}",
        f"frame: {event.get('frame_index') if event.get('frame_index') is not None else '-'}",
        f"start: {format_ms(event.get('start_ms'))}",
        f"end: {format_ms(event.get('end_ms'))}",
        f"duration: {format_ms(event.get('duration_ms'))}",
        f"ready: {format_ms(event.get('ready_ms'))}",
        f"resource_wait: {format_ms(event.get('resource_wait_ms'))}",
        f"token_wait: {format_ms(event.get('token_wait_ms'))}",
        f"deadline: {format_ms(event.get('deadline_ms'))}",
        f"slack: {format_ms(event.get('slack_ms'))}",
        f"cadence_interval: {format_ms(event.get('cadence_interval_ms'))}",
        f"cadence_avg: {format_ms(event.get('cadence_avg_interval_ms'))}",
        f"cadence_budget: {format_ms(event.get('cadence_budget_ms'))}",
        f"cadence_slack: {format_ms(event.get('cadence_slack_ms'))}",
        f"bottleneck: {event.get('bottleneck_reason') or '-'}",
    ]
    return "<br>".join(lines)


def timeline_frame_outputs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frames = sorted({int(value) for value in (numeric(event.get("frame_index")) for event in events) if value is not None})
    if not frames:
        return []
    predecessor_ids: set[str] = set()
    for event in events:
        for predecessor in event.get("predecessors") or []:
            predecessor_ids.add(str(predecessor))
    outputs = []
    for frame_index in frames:
        frame_events = [
            event
            for event in events
            if numeric(event.get("frame_index")) is not None and int(numeric(event.get("frame_index")) or 0) == frame_index
        ]
        source_events = [
            event
            for event in frame_events
            if event.get("constraint_type") == "source" or numeric(event.get("v_valid_ms")) is not None
        ]
        start_source = source_events if source_events else frame_events
        if not start_source:
            continue
        start_ms = min(numeric(event.get("start_ms")) or 0.0 for event in start_source)
        candidates = [
            event
            for event in frame_events
            if event.get("constraint_type") == "sink"
            or numeric(event.get("scanout_ms")) is not None
            or str(event.get("task_id")) not in predecessor_ids
        ]
        if not candidates:
            candidates = frame_events
        output = max(candidates, key=lambda event: (numeric(event.get("end_ms")) or 0.0, numeric(event.get("start_ms")) or 0.0))
        output_ms = numeric(output.get("end_ms")) or 0.0
        outputs.append(
            {
                "frame_index": frame_index,
                "start_ms": start_ms,
                "output_ms": output_ms,
                "latency_ms": output_ms - start_ms,
                "output_task": event_id(output),
            }
        )
    return outputs


def _add_wait_segments(fig: Any, event: dict[str, Any], label: str, legend_seen: set[str]) -> None:
    ready = numeric(event.get("ready_ms"))
    token_wait = numeric(event.get("token_wait_ms")) or 0.0
    if ready is not None and token_wait > 0:
        showlegend = "Token Wait" not in legend_seen
        legend_seen.add("Token Wait")
        fig.add_trace(
            _bar_trace(
                x=[token_wait],
                y=[label],
                base=[max(0.0, ready - token_wait)],
                name="Token Wait",
                marker={"color": "#FDBA74", "pattern": {"shape": "/"}},
                hovertext=[f"token_wait: {format_ms(token_wait)}<br>task: {event_id(event)}"],
                showlegend=showlegend,
            )
        )
    resource_wait = numeric(event.get("resource_wait_ms")) or 0.0
    if ready is not None and resource_wait > 0:
        showlegend = "Resource Wait" not in legend_seen
        legend_seen.add("Resource Wait")
        fig.add_trace(
            _bar_trace(
                x=[resource_wait],
                y=[label],
                base=[ready],
                name="Resource Wait",
                marker={"color": "#CBD5E1", "pattern": {"shape": "x"}},
                hovertext=[f"resource_wait: {format_ms(resource_wait)}<br>task: {event_id(event)}"],
                showlegend=showlegend,
            )
        )


def _add_deadline_markers(fig: Any, visible_events: list[dict[str, Any]], labels: list[str]) -> None:
    deadline_x: list[float] = []
    deadline_y: list[str] = []
    deadline_text: list[str] = []
    deadline_color: list[str] = []
    for label, event in zip(labels, visible_events, strict=False):
        deadline = numeric(event.get("deadline_ms"))
        if deadline is None:
            continue
        slack = numeric(event.get("slack_ms"))
        cadence_slack = numeric(event.get("cadence_slack_ms"))
        deadline_x.append(deadline)
        deadline_y.append(label)
        deadline_text.append(
            f"latency deadline: {format_ms(deadline)}<br>"
            f"latency slack: {format_ms(slack)}<br>"
            f"avg cadence: {format_ms(event.get('cadence_avg_interval_ms'))}<br>"
            f"cadence slack: {format_ms(cadence_slack)}<br>"
            f"task: {event_id(event)}"
        )
        effective_slack = cadence_slack if cadence_slack is not None else slack
        deadline_color.append("#16A34A" if effective_slack is None or effective_slack >= 0 else "#DC2626")
    if deadline_x:
        import plotly.graph_objects as go

        fig.add_trace(
            go.Scatter(
                x=deadline_x,
                y=deadline_y,
                mode="markers",
                name="Deadline",
                marker={"symbol": "x", "size": 10, "color": deadline_color, "line": {"width": 2}},
                hovertext=deadline_text,
                hoverinfo="text",
            )
        )


def _bar_trace(**kwargs: Any) -> Any:
    import plotly.graph_objects as go

    return go.Bar(orientation="h", hoverinfo="text", **kwargs)


def numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_ms(value: Any) -> str:
    number = numeric(value)
    if number is None:
        return "-"
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    return f"{text} ms"


def format_value(value: Any, suffix: str = "") -> str:
    number = numeric(value)
    if number is None:
        return "-"
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


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


def safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ".-" else "_" for ch in value)[:160]
