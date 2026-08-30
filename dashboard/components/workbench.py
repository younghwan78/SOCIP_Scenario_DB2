"""Streamlit bridge for the Scenario Workbench custom component.

The component frontend lives in ``frontend/`` and its built assets are
committed under ``dashboard/components/workbench_frontend/component`` so the
dashboard runs without a Node toolchain. Rebuild with ``npm run build`` from
``frontend/`` after frontend changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

from dashboard.components.workbench_data import build_component_args, normalize_selection

COMPONENT_PATH = Path(__file__).resolve().parent / "workbench_frontend" / "component"

_component_func = None


def workbench_available() -> bool:
    return (COMPONENT_PATH / "index.html").is_file()


def _get_component():
    global _component_func
    if _component_func is None:
        _component_func = components.declare_component("scenario_workbench", path=str(COMPONENT_PATH))
    return _component_func


def render_workbench_timeline(
    events: list[dict[str, Any]],
    *,
    key: str,
    show_waits: bool = True,
    show_deadlines: bool = True,
    theme: str = "light",
    export_name: str = "timeline",
    graph: dict[str, Any] | None = None,
    drill_node: str | None = None,
    baseline_events: list[dict[str, Any]] | None = None,
    baseline_name: str | None = None,
) -> dict[str, Any] | None:
    """Render the interactive timeline pane and return the normalized selection.

    ``graph`` (from :func:`workbench_data.build_graph_payload`) enables the
    side diagram pane with timeline<->topology cross-probing.

    Returns ``None`` when nothing is selected; otherwise a dict with
    ``selected_task_id``, ``range_start_ms``, ``range_end_ms``, ``range_stats``.
    """

    args = build_component_args(
        events,
        show_waits=show_waits,
        show_deadlines=show_deadlines,
        theme=theme,
        export_name=export_name,
    )
    if graph:
        args["graph"] = graph
    if drill_node:
        args["drillNode"] = drill_node
    if baseline_events:
        args["baselineEvents"] = [event for event in baseline_events if isinstance(event, dict)]
        args["baselineName"] = str(baseline_name or "baseline")
    component = _get_component()
    raw = component(key=key, default=None, **args)
    return normalize_selection(raw)
