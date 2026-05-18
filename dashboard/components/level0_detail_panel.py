"""Scenario context helpers for the Pipeline Viewer side panel."""
from __future__ import annotations

from scenario_db.api.schemas.view import ViewResponse


def scenario_context_description(view: ViewResponse) -> str:
    if view.level0_resource_overview:
        return (
            "Review selected scenario resources, endpoint context, and the "
            "active topology graph. Node and edge tooltips carry per-resource "
            "buffer, operation, and placement details."
        )
    return (
        "Review the selected graph. Node and edge tooltips carry operation, "
        "buffer, placement, and simulation details when the API provides them."
    )


def scenario_context_rows(view: ViewResponse) -> list[tuple[str, str]]:
    summary = view.summary
    rows = [
        ("Scenario", summary.name),
        ("Variant", summary.variant_id),
    ]
    if _has_video_timing_context(view):
        if summary.resolution and summary.resolution.lower() not in {"unknown", "n/a", "-"}:
            rows.append(("Resolution", summary.resolution))
        if summary.fps:
            rows.append(("Frame Rate", f"{summary.fps} fps"))
        if summary.period_ms:
            rows.append(("Period", f"{summary.period_ms:g} ms"))
        if summary.budget_ms:
            rows.append(("Budget", f"{summary.budget_ms:g} ms"))
    return rows


def _has_video_timing_context(view: ViewResponse) -> bool:
    overview = view.level0_resource_overview
    if overview is None:
        return True
    subsystems = {row.subsystem for row in overview.rows}
    if overview.sensors:
        return True
    return bool(subsystems & {"camera", "video", "display", "game", "ai"})
