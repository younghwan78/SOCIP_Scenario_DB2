"""Browser-less UI contract helpers for the Evidence Dashboard."""

from __future__ import annotations

from urllib.parse import urlencode


SIDEBAR_SELECTORS = (
    "SoC Platform",
    "Project / Board",
    "Scenario Category",
    "Scenario",
    "Variant",
)

SIMULATION_RESULT_TOP_TABS = ("Preview Run", "Saved Evidence")

RESULT_BREAKDOWN_TABS = (
    "IP/Node Power",
    "DMA BW",
    "Timing Chart",
    "Timing Table",
    "Timeline Table",
    "Debug Trace",
    "Raw Evidence",
)

PREVIEW_ACTION_LABELS = (
    "Confirm & Save Evidence",
    "Download Preview JSON",
    "Download Preview KPI CSV",
    "Open Scenario in Pipeline Viewer",
)

SAVED_ACTION_LABELS = (
    "Open Pipeline Viewer",
    "Download JSON",
    "Download KPI CSV",
    "Download DMA CSV",
    "Delete Evidence",
)

VIEWER_LINK_LABEL_PREVIEW = "Open Scenario in Pipeline Viewer"
VIEWER_LINK_LABEL_SAVED = "Open Pipeline Viewer"

SEVERE_WARNING_MARKERS = (
    "All compute IP core power is zero",
    "All compute IP HW time is zero",
)


def build_pipeline_viewer_url(
    *,
    api_base: str,
    scenario_id: str,
    variant_id: str,
    soc_id: str | None = None,
    project_id: str | None = None,
    evidence_id: str | None = None,
) -> str:
    """Build the Pipeline Viewer URL used by preview and saved evidence flows."""

    query = {
        "api_base": api_base,
        "soc_id": soc_id,
        "project_id": project_id,
        "scenario_id": scenario_id,
        "variant_id": variant_id,
        "sim_evidence_id": evidence_id,
    }
    clean = {key: value for key, value in query.items() if value not in (None, "")}
    return f"/Pipeline_Viewer?{urlencode(clean)}"


def warning_severity(warnings: list[str]) -> str:
    """Classify dashboard warning display without importing Streamlit."""

    if any(marker in warning for warning in warnings for marker in SEVERE_WARNING_MARKERS):
        return "error"
    if warnings:
        return "warning"
    return "none"
