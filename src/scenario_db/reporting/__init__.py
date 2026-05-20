"""HTML report artifact generation for simulation evidence."""

from scenario_db.reporting.filenames import artifact_filenames, build_report_prefix, safe_report_slug
from scenario_db.reporting.models import ArtifactFilenames, GeneratedReportBundle, ReportContext, WrittenArtifact, WrittenReportBundle

__all__ = [
    "ArtifactFilenames",
    "GeneratedReportBundle",
    "ReportContext",
    "WrittenArtifact",
    "WrittenReportBundle",
    "artifact_filenames",
    "build_report_prefix",
    "safe_report_slug",
]
