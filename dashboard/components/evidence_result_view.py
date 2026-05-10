"""Result breakdown rendering for the Evidence Dashboard."""
from __future__ import annotations

from typing import Any

import streamlit as st

from dashboard.components.evidence_dashboard_contract import RESULT_BREAKDOWN_TABS
from dashboard.components.table_actions import render_copyable_dataframe


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


def _timeline_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in result.get("timeline_events") or [] if isinstance(row, dict)]


def _event_id(event: dict[str, Any]) -> str:
    return str(event.get("task_id") or event.get("node_id") or event.get("hw_name") or "task")


def _event_label(event: dict[str, Any], *, include_frame: bool) -> str:
    name = _event_id(event)
    resource = event.get("resource_id") or event.get("task_type") or event.get("constraint_type")
    if resource and resource not in name:
        name = f"{resource} / {name}"
    if include_frame and event.get("frame_index") is not None:
        name = f"F{event.get('frame_index')} / {name}"
    return name


def _constraint_label(event: dict[str, Any]) -> str:
    if event.get("constraint_type"):
        return str(event.get("constraint_type"))
    task_type = str(event.get("task_type") or "")
    if task_type:
        return task_type
    return "task"


OTF_COLOR_FAMILIES = [
    ["#2F6F68", "#3D8A82", "#75B2A8", "#B9D2CC"],
    ["#0F766E", "#14B8A6", "#2DD4BF", "#5EEAD4"],
    ["#7C3AED", "#8B5CF6", "#A78BFA", "#C4B5FD"],
    ["#059669", "#10B981", "#34D399", "#6EE7B7"],
    ["#0284C7", "#0EA5E9", "#38BDF8", "#7DD3FC"],
]
M2M_COLOR_FAMILIES = [
    "#D97706",
    "#EA580C",
    "#BE123C",
    "#A16207",
    "#C2410C",
]
SW_COLOR_FAMILIES = [
    "#9333EA",
    "#C026D3",
    "#DB2777",
    "#7E22CE",
]


def _render_timing_summary(result: dict[str, Any]) -> None:
    events = _timeline_events(result)
    kpi = result.get("kpi") if isinstance(result.get("kpi"), dict) else {}
    if not events:
        st.info("No timeline events are available for this evidence.")
        return

    end_ms = _numeric(kpi.get("timeline_end_ms"))
    if end_ms is None:
        end_ms = max((_numeric(event.get("end_ms")) or 0.0 for event in events), default=0.0)
    critical_ms = _numeric(kpi.get("critical_path_ms"))
    critical_count = _numeric(kpi.get("critical_path_task_count"))
    resource_wait_event = max(events, key=lambda event: _numeric(event.get("resource_wait_ms")) or 0.0)
    token_wait_event = max(events, key=lambda event: _numeric(event.get("token_wait_ms")) or 0.0)
    slack_events = [event for event in events if _numeric(event.get("slack_ms")) is not None]
    tightest_slack_event = min(slack_events, key=lambda event: _numeric(event.get("slack_ms")) or 0.0) if slack_events else None
    cadence_events = [
        event
        for event in events
        if _numeric(event.get("cadence_avg_interval_ms")) is not None
        and _numeric(event.get("cadence_budget_ms")) is not None
    ]
    tightest_cadence_event = (
        min(cadence_events, key=lambda event: _numeric(event.get("cadence_slack_ms")) or 0.0)
        if cadence_events
        else None
    )
    source_events = [
        event
        for event in events
        if event.get("constraint_type") == "source" or _numeric(event.get("v_valid_ms")) is not None
    ]
    sink_events = [
        event
        for event in events
        if event.get("constraint_type") == "sink" or _numeric(event.get("scanout_ms")) is not None
    ]

    cols = st.columns(4)
    cols[0].metric("Timeline End", _format_ms(end_ms))
    critical_detail = f"{int(critical_count)} tasks" if critical_count is not None else "-"
    cols[1].metric("Critical Path", _format_ms(critical_ms), help=critical_detail)
    cols[2].metric(
        "Max Resource Wait",
        _format_ms(resource_wait_event.get("resource_wait_ms")),
        help=_event_id(resource_wait_event),
    )
    cols[3].metric(
        "Max Token Wait",
        _format_ms(token_wait_event.get("token_wait_ms")),
        help=_event_id(token_wait_event),
    )

    cols = st.columns(3)
    if tightest_slack_event:
        cols[0].metric("Tightest Slack", _format_ms(tightest_slack_event.get("slack_ms")), help=_event_id(tightest_slack_event))
    else:
        cols[0].metric("Tightest Slack", "-")
    if source_events:
        source = source_events[0]
        cols[1].metric(
            "Source Window",
            _format_ms(source.get("v_valid_ms") or source.get("duration_ms")),
            help=f"{_event_id(source)} / fps={_format_value(source.get('source_fps'))}",
        )
    else:
        cols[1].metric("Source Window", "-")
    if tightest_cadence_event:
        cols[2].metric(
            "Output Cadence Slack",
            _format_ms(tightest_cadence_event.get("cadence_slack_ms")),
            help=(
                f"{_event_id(tightest_cadence_event)} / "
                f"avg interval={_format_ms(tightest_cadence_event.get('cadence_avg_interval_ms'))} / "
                f"budget={_format_ms(tightest_cadence_event.get('cadence_budget_ms'))}"
            ),
        )
    elif sink_events:
        sink = min(sink_events, key=lambda event: _numeric(event.get("slack_ms")) or 0.0)
        cols[2].metric(
            "Sink Latency Slack",
            _format_ms(sink.get("slack_ms")),
            help=f"{_event_id(sink)} / deadline={_format_ms(sink.get('deadline_ms'))}",
        )
    else:
        cols[2].metric("Output Cadence Slack", "-")


def _base_task_id(task_id: Any) -> str:
    return str(task_id or "").split("#f", 1)[0]


def _base_otf_group_id(group_id: Any) -> str | None:
    if not group_id:
        return None
    return str(group_id).split("#f", 1)[0]


def _timeline_group_index(value: str | None, fallback: str) -> int:
    text = value or fallback
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return int(digits)
    return sum(ord(ch) for ch in text)


def _timeline_chart_color(event: dict[str, Any]) -> str:
    constraint = event.get("constraint_type")
    if constraint == "source":
        return "#22C55E"
    task_type = str(event.get("task_type") or "").lower()
    if "sw" in task_type:
        index = _timeline_group_index(str(event.get("resource_id") or ""), _base_task_id(event.get("task_id")))
        return SW_COLOR_FAMILIES[index % len(SW_COLOR_FAMILIES)]

    otf_group = _base_otf_group_id(event.get("otf_group_id"))
    if otf_group:
        family = OTF_COLOR_FAMILIES[_timeline_group_index(otf_group, otf_group) % len(OTF_COLOR_FAMILIES)]
        shade_index = _timeline_group_index(None, _base_task_id(event.get("task_id"))) % len(family)
        return family[shade_index]

    if constraint == "sink":
        return "#0284C7"
    edge_type = str(event.get("edge_type") or "").upper()
    if edge_type in {"M2M", "VOTF"}:
        index = _timeline_group_index(str(event.get("resource_id") or edge_type), _base_task_id(event.get("task_id")))
        return M2M_COLOR_FAMILIES[index % len(M2M_COLOR_FAMILIES)]
    if "dma" in task_type or "m2m" in task_type:
        index = _timeline_group_index(str(event.get("resource_id") or ""), _base_task_id(event.get("task_id")))
        return M2M_COLOR_FAMILIES[index % len(M2M_COLOR_FAMILIES)]
    return "#64748B"


def _timeline_legend_name(event: dict[str, Any]) -> str:
    task_type = str(event.get("task_type") or "").lower()
    if "sw" in task_type:
        return "SW Task"
    if event.get("constraint_type") == "source":
        return "Sensor In"
    otf_group = _base_otf_group_id(event.get("otf_group_id"))
    if otf_group:
        return f"HW OTF {otf_group.replace('otf-', '')}"
    edge_type = str(event.get("edge_type") or "").upper()
    if edge_type in {"M2M", "VOTF"}:
        return f"HW {edge_type}"
    if event.get("constraint_type") == "sink":
        return "Display Out"
    return "HW Task"


def _timeline_hover(event: dict[str, Any]) -> str:
    fields = [
        ("task", _event_id(event)),
        ("node", event.get("node_id")),
        ("resource", event.get("resource_id")),
        ("frame", event.get("frame_index")),
        ("edge", event.get("edge_type")),
        ("otf_group", event.get("otf_group_id")),
        ("bottleneck", event.get("bottleneck")),
        ("bottleneck_reason", event.get("bottleneck_reason")),
        ("type", _constraint_label(event)),
        ("start", _format_ms(event.get("start_ms"))),
        ("end", _format_ms(event.get("end_ms"))),
        ("duration", _format_ms(event.get("duration_ms"))),
        ("resource_wait", _format_ms(event.get("resource_wait_ms"))),
        ("token_wait", _format_ms(event.get("token_wait_ms"))),
        ("deadline", _format_ms(event.get("deadline_ms"))),
        ("slack", _format_ms(event.get("slack_ms"))),
        ("cadence_interval", _format_ms(event.get("cadence_interval_ms"))),
        ("cadence_avg_interval", _format_ms(event.get("cadence_avg_interval_ms"))),
        ("cadence_budget", _format_ms(event.get("cadence_budget_ms"))),
        ("cadence_slack", _format_ms(event.get("cadence_slack_ms"))),
    ]
    return "<br>".join(f"{key}: {value}" for key, value in fields if value not in (None, "-"))


def _timeline_frame_outputs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    predecessor_ids = {
        str(predecessor)
        for event in events
        for predecessor in (event.get("predecessors") or [])
        if predecessor is not None
    }
    by_frame: dict[int, list[dict[str, Any]]] = {}
    for event in events:
        frame_value = _numeric(event.get("frame_index"))
        frame_index = int(frame_value) if frame_value is not None else 0
        by_frame.setdefault(frame_index, []).append(event)

    outputs: list[dict[str, Any]] = []
    for frame_index, frame_events in sorted(by_frame.items()):
        source_events = [
            event
            for event in frame_events
            if event.get("constraint_type") == "source" or _numeric(event.get("v_valid_ms")) is not None
        ]
        start_source = source_events if source_events else frame_events
        if not start_source:
            continue
        start_ms = min(_numeric(event.get("start_ms")) or 0.0 for event in start_source)
        candidates = [
            event
            for event in frame_events
            if event.get("constraint_type") == "sink"
            or _numeric(event.get("scanout_ms")) is not None
            or str(event.get("task_id")) not in predecessor_ids
        ]
        if not candidates:
            candidates = frame_events
        output = max(candidates, key=lambda event: (_numeric(event.get("end_ms")) or 0.0, _numeric(event.get("start_ms")) or 0.0))
        output_ms = _numeric(output.get("end_ms")) or 0.0
        outputs.append(
            {
                "frame_index": frame_index,
                "start_ms": start_ms,
                "output_ms": output_ms,
                "latency_ms": output_ms - start_ms,
                "output_task": _event_id(output),
            }
        )
    return outputs


def _render_timing_chart_metrics(events: list[dict[str, Any]]) -> None:
    outputs = _timeline_frame_outputs(events)
    if not outputs:
        return
    preferred = next((item for item in outputs if item["frame_index"] == 1), outputs[0])
    intervals = [
        {
            "from": previous["frame_index"],
            "to": current["frame_index"],
            "interval_ms": current["output_ms"] - previous["output_ms"],
        }
        for previous, current in zip(outputs, outputs[1:], strict=False)
    ]

    cols = st.columns(3)
    cols[0].metric(
        f"Frame {preferred['frame_index']} Latency",
        _format_ms(preferred["latency_ms"]),
        help=(
            f"start={_format_ms(preferred['start_ms'])} / "
            f"output={_format_ms(preferred['output_ms'])} / "
            f"task={preferred['output_task']}"
        ),
    )
    if intervals:
        avg_interval = sum(item["interval_ms"] for item in intervals) / len(intervals)
        last_interval = intervals[-1]
        cols[1].metric(
            "Avg Output Interval",
            _format_ms(avg_interval),
            help=f"{len(intervals)} intervals across {len(outputs)} frames",
        )
        cols[2].metric(
            f"F{last_interval['from']} -> F{last_interval['to']} Interval",
            _format_ms(last_interval["interval_ms"]),
        )
    else:
        cols[1].metric("Avg Output Interval", "-")
        cols[2].metric("Last Output Interval", "-")


def _render_timing_chart(result: dict[str, Any], *, key_prefix: str = "stored") -> None:
    events = _timeline_events(result)
    if not events:
        st.info("No timeline events are available for chart rendering.")
        return
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.warning("Plotly is not installed in this environment. The timeline table is shown instead.")
        render_copyable_dataframe(
            events,
            key=f"{key_prefix}_timing_chart_fallback",
            use_container_width=True,
            hide_index=True,
        )
        return

    evidence_id = _safe_filename(str(result.get("id") or "selected"))
    frame_values = sorted(
        {
            int(value)
            for value in (_numeric(event.get("frame_index")) for event in events)
            if value is not None
        }
    )
    if len(frame_values) > 1:
        frame_options = ["All", *[str(value) for value in frame_values]]
        frame_choice = st.selectbox("Frame", frame_options, key=f"{key_prefix}_timing_chart_frame_{evidence_id}", index=0)
    else:
        frame_choice = "All"
    show_waits = st.checkbox("Show queue waits", value=True, key=f"{key_prefix}_timing_chart_waits_{evidence_id}")
    show_deadlines = st.checkbox("Show deadlines", value=True, key=f"{key_prefix}_timing_chart_deadlines_{evidence_id}")
    _render_timing_chart_metrics(events)

    event_order = {id(event): index for index, event in enumerate(events)}
    visible_events = events
    if frame_choice != "All":
        frame_index = int(frame_choice)
        visible_events = [
            event
            for event in events
            if _numeric(event.get("frame_index")) is not None and int(_numeric(event.get("frame_index")) or 0) == frame_index
        ]
    visible_events = sorted(
        visible_events,
        key=lambda event: (
            _numeric(event.get("frame_index")) or 0.0,
            _numeric(event.get("start_ms")) or 0.0,
            event_order.get(id(event), 0),
        ),
    )
    include_frame = frame_choice == "All" and len(frame_values) > 1
    labels = [_event_label(event, include_frame=include_frame) for event in visible_events]
    fig = go.Figure()
    legend_seen: set[str] = set()

    for label, event in zip(labels, visible_events, strict=False):
        start = _numeric(event.get("start_ms")) or 0.0
        end = _numeric(event.get("end_ms"))
        duration = _numeric(event.get("duration_ms"))
        if duration is None and end is not None:
            duration = max(0.0, end - start)
        duration = duration or 0.0
        color = _timeline_chart_color(event)
        segment_name = _timeline_legend_name(event)
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
                hovertext=[_timeline_hover(event)],
                hoverinfo="text",
                showlegend=showlegend,
            )
        )

        if show_waits:
            ready = _numeric(event.get("ready_ms"))
            token_wait = _numeric(event.get("token_wait_ms")) or 0.0
            if ready is not None and token_wait > 0:
                showlegend = "Token Wait" not in legend_seen
                legend_seen.add("Token Wait")
                fig.add_trace(
                    go.Bar(
                        x=[token_wait],
                        y=[label],
                        base=[max(0.0, ready - token_wait)],
                        orientation="h",
                        name="Token Wait",
                        marker={"color": "#FDBA74", "pattern": {"shape": "/"}},
                        hovertext=[f"token_wait: {_format_ms(token_wait)}<br>task: {_event_id(event)}"],
                        hoverinfo="text",
                        showlegend=showlegend,
                    )
                )
            resource_wait = _numeric(event.get("resource_wait_ms")) or 0.0
            if ready is not None and resource_wait > 0:
                showlegend = "Resource Wait" not in legend_seen
                legend_seen.add("Resource Wait")
                fig.add_trace(
                    go.Bar(
                        x=[resource_wait],
                        y=[label],
                        base=[ready],
                        orientation="h",
                        name="Resource Wait",
                        marker={"color": "#CBD5E1", "pattern": {"shape": "x"}},
                        hovertext=[f"resource_wait: {_format_ms(resource_wait)}<br>task: {_event_id(event)}"],
                        hoverinfo="text",
                        showlegend=showlegend,
                    )
                )

    if show_deadlines:
        deadline_x: list[float] = []
        deadline_y: list[str] = []
        deadline_text: list[str] = []
        deadline_color: list[str] = []
        for label, event in zip(labels, visible_events, strict=False):
            deadline = _numeric(event.get("deadline_ms"))
            if deadline is None:
                continue
            slack = _numeric(event.get("slack_ms"))
            cadence_slack = _numeric(event.get("cadence_slack_ms"))
            deadline_x.append(deadline)
            deadline_y.append(label)
            deadline_text.append(
                f"latency deadline: {_format_ms(deadline)}<br>"
                f"latency slack: {_format_ms(slack)}<br>"
                f"avg cadence: {_format_ms(event.get('cadence_avg_interval_ms'))}<br>"
                f"cadence slack: {_format_ms(cadence_slack)}<br>"
                f"task: {_event_id(event)}"
            )
            effective_slack = cadence_slack if cadence_slack is not None else slack
            deadline_color.append("#16A34A" if effective_slack is None or effective_slack >= 0 else "#DC2626")
        if deadline_x:
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

    critical_rows = [
        row
        for row in _ordered_table(
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
    ]
    issue_rows = _ordered_table(
        sorted(
            visible_events,
            key=lambda event: (
                -((_numeric(event.get("resource_wait_ms")) or 0.0) + (_numeric(event.get("token_wait_ms")) or 0.0)),
                _numeric(event.get("slack_ms")) if _numeric(event.get("slack_ms")) is not None else 1e12,
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
    render_copyable_dataframe(
        critical_rows,
        key=f"{key_prefix}_critical_path_rows",
        use_container_width=True,
        hide_index=True,
    )
    st.caption("Top wait/slack candidates")
    render_copyable_dataframe(
        issue_rows,
        key=f"{key_prefix}_wait_slack_rows",
        use_container_width=True,
        hide_index=True,
    )


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
        _render_timing_summary(result)
        _render_timing_chart(result, key_prefix=key_prefix)
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
