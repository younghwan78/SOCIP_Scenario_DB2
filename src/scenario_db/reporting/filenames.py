from __future__ import annotations

import re

from scenario_db.reporting.models import ArtifactFilenames, ReportContext


_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_DASH_RUN = re.compile(r"-+")


def safe_report_slug(value: str) -> str:
    text = str(value or "").strip().replace(" ", "_")
    text = _UNSAFE_CHARS.sub("-", text)
    text = _DASH_RUN.sub("-", text).strip("-._")
    return text[:140] or "simulation-report"


def build_report_prefix(context: ReportContext) -> str:
    project = context.project_ref or context.soc_ref or context.scenario_ref
    variant = context.variant_name or context.variant_ref
    return safe_report_slug(f"{project}-{variant}")


def artifact_filenames(prefix: str) -> ArtifactFilenames:
    safe_prefix = safe_report_slug(prefix)
    return ArtifactFilenames(
        timing_chart=f"{safe_prefix}_timing_chart.html",
        bw_chart=f"{safe_prefix}_bw_chart.html",
        simulation_report=f"{safe_prefix}_simulation_result.html",
    )
