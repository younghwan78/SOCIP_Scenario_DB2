"""Pure payload/selection helpers for the Scenario Workbench component.

This module must stay free of streamlit imports so the logic is unit-testable
with the plain dev dependency group.
"""
from __future__ import annotations

from statistics import median
from typing import Any

DEFAULT_FRAME_INTERVAL_MS = 33.333


def numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def event_start(event: dict[str, Any]) -> float:
    return numeric(event.get("start_ms")) or 0.0


def event_end(event: dict[str, Any]) -> float:
    end = numeric(event.get("end_ms"))
    if end is not None:
        return end
    return event_start(event) + (numeric(event.get("duration_ms")) or 0.0)


def derive_frame_interval_ms(events: list[dict[str, Any]]) -> float:
    """Frame band interval: 1000/source_fps when available, else the median
    spacing between per-frame first starts, else the 30fps default."""

    for event in events:
        fps = numeric(event.get("source_fps"))
        if fps and fps > 0:
            return 1000.0 / fps

    frame_starts: dict[int, float] = {}
    for event in events:
        frame = numeric(event.get("frame_index"))
        if frame is None:
            continue
        index = int(frame)
        start = event_start(event)
        if index not in frame_starts or start < frame_starts[index]:
            frame_starts[index] = start
    if len(frame_starts) >= 2:
        starts = [frame_starts[key] for key in sorted(frame_starts)]
        diffs = [after - before for before, after in zip(starts, starts[1:], strict=False) if after > before]
        if diffs:
            return float(median(diffs))
    return DEFAULT_FRAME_INTERVAL_MS


def build_component_args(
    events: list[dict[str, Any]],
    *,
    show_waits: bool = True,
    show_deadlines: bool = True,
    theme: str = "light",
    frame_interval_ms: float | None = None,
    export_name: str = "timeline",
) -> dict[str, Any]:
    interval = frame_interval_ms if frame_interval_ms and frame_interval_ms > 0 else derive_frame_interval_ms(events)
    safe_name = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in export_name)[:120] or "timeline"
    return {
        "events": [event for event in events if isinstance(event, dict)],
        "exportName": safe_name,
        "options": {
            "showWaits": bool(show_waits),
            "showDeadlines": bool(show_deadlines),
            "theme": theme if theme in {"light", "dark"} else "light",
            "frameIntervalMs": interval,
        },
    }


_LAYOUT_NODE_TYPES = {"lane_bg", "lane_label", "stage_header"}


def build_graph_payload(view: dict[str, Any] | None) -> dict[str, Any] | None:
    """Slim a ViewResponse payload into the workbench diagram-pane graph.

    Keeps only what the pane renders: node id/label/type/layer and edge
    endpoints with flow type. Returns None when there is nothing to draw.
    """

    if not isinstance(view, dict):
        return None
    nodes = []
    for node in view.get("nodes") or []:
        data = node.get("data") if isinstance(node, dict) else None
        if not isinstance(data, dict):
            continue
        node_type = str(data.get("type") or "")
        if node_type in _LAYOUT_NODE_TYPES:
            continue
        nodes.append(
            {
                "id": str(data.get("id") or ""),
                "label": str(data.get("label") or data.get("id") or ""),
                "type": node_type,
                "layer": str(data.get("layer") or ""),
            }
        )
    node_ids = {node["id"] for node in nodes}
    edges = []
    for index, edge in enumerate(view.get("edges") or []):
        data = edge.get("data") if isinstance(edge, dict) else None
        if not isinstance(data, dict):
            continue
        source = str(data.get("source") or "")
        target = str(data.get("target") or "")
        if source not in node_ids or target not in node_ids:
            continue
        edges.append(
            {
                "id": str(data.get("id") or f"g-{index}"),
                "source": source,
                "target": target,
                "flow_type": str(data.get("flow_type") or "M2M"),
            }
        )
    if not nodes:
        return None
    return {"nodes": nodes, "edges": edges}


def filter_events_by_range(events: list[dict[str, Any]], start_ms: float, end_ms: float) -> list[dict[str, Any]]:
    """Events whose [start, end) interval intersects the selected range.

    Matches the component-side eventsInRange semantics so the Streamlit tables
    show exactly what the brush selection covers.
    """

    lo, hi = min(start_ms, end_ms), max(start_ms, end_ms)
    return [event for event in events if event_end(event) > lo and event_start(event) < hi]


def normalize_selection(raw: Any) -> dict[str, Any] | None:
    """Normalize the component return value into snake_case Python fields."""

    if not isinstance(raw, dict):
        return None
    task_id = raw.get("selectedTaskId")
    start = numeric(raw.get("rangeStartMs"))
    end = numeric(raw.get("rangeEndMs"))
    if start is None or end is None:
        start = end = None
    stats = raw.get("rangeStats") if isinstance(raw.get("rangeStats"), dict) else None
    if task_id is None and start is None:
        return None
    return {
        "selected_task_id": str(task_id) if task_id is not None else None,
        "range_start_ms": start,
        "range_end_ms": end,
        "range_stats": stats,
    }
