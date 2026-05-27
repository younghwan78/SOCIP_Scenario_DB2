from __future__ import annotations

from pathlib import Path

from scenario_db.config import Settings
from scenario_db.reporting.filenames import (
    artifact_filenames,
    build_report_prefix,
    safe_report_slug,
)
from scenario_db.reporting.models import ReportContext


def test_safe_report_slug_preserves_legacy_readable_names():
    assert safe_report_slug("projectA-FHD30_Recording") == "projectA-FHD30_Recording"
    assert safe_report_slug("uc-camera-recording/UHD60 HDR10 H.265") == "uc-camera-recording-UHD60_HDR10_H.265"


def test_report_prefix_prefers_project_and_variant_name_when_available():
    context = ReportContext(
        evidence_id="sim-1",
        scenario_ref="uc-camera-recording",
        variant_ref="FHD30-SDR-H265",
        project_ref="projectA",
        scenario_name="Camera Recording",
        variant_name="FHD30 Recording",
    )

    assert build_report_prefix(context) == "projectA-FHD30_Recording"


def test_report_prefix_falls_back_to_scenario_and_variant_id():
    context = ReportContext(
        evidence_id="sim-1",
        scenario_ref="uc-camera-recording",
        variant_ref="cam-rec-f1-fhd30",
        project_ref=None,
        scenario_name=None,
        variant_name=None,
    )

    assert build_report_prefix(context) == "uc-camera-recording-cam-rec-f1-fhd30"


def test_artifact_filenames_match_legacy_suffixes():
    names = artifact_filenames("projectA-FHD30_Recording")

    assert names.timing_chart == "projectA-FHD30_Recording_timing_chart.html"
    assert names.bw_chart == "projectA-FHD30_Recording_bw_chart.html"
    assert names.simulation_report == "projectA-FHD30_Recording_simulation_result.html"


def test_report_dir_setting_defaults_to_output_simulation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///report-settings.db")
    settings = Settings()

    assert Path(settings.report_dir).as_posix().endswith("output_simulation")
