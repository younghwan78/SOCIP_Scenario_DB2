from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ArtifactKind = Literal["timing_chart", "bw_chart", "simulation_report"]


@dataclass(frozen=True, slots=True)
class ReportContext:
    evidence_id: str
    scenario_ref: str
    variant_ref: str
    project_ref: str | None = None
    scenario_name: str | None = None
    variant_name: str | None = None
    soc_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactFilenames:
    timing_chart: str
    bw_chart: str
    simulation_report: str


@dataclass(frozen=True, slots=True)
class GeneratedReportBundle:
    prefix: str
    timing_chart_html: str | None
    bw_chart_html: str | None
    simulation_report_html: str


@dataclass(frozen=True, slots=True)
class WrittenArtifact:
    type: ArtifactKind
    storage: str
    path: Path
    sha256: str
    bytes: int
    mime: str = "text/html"
    created_at: str | None = None
    prefix: str | None = None
    generator: str = "scenario_db.reporting"


@dataclass(frozen=True, slots=True)
class WrittenReportBundle:
    prefix: str
    output_dir: Path
    artifacts: list[WrittenArtifact]
