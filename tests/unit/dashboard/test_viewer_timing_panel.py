"""Viewer timing panel — pure helpers (no Streamlit runtime needed)."""
from __future__ import annotations

import pytest

from dashboard.components.viewer_timing_panel import saved_evidence_option_label

pytestmark = pytest.mark.unit


def test_saved_evidence_option_label_includes_headline_kpis():
    label = saved_evidence_option_label(
        {
            "id": "sim-uc-camera-recording-cam-rec-r1-fhd30-vdis-be67039d",
            "kpi": {"total_power_mw": 170.2674432, "critical_path_ms": 591.4044},
        }
    )
    assert label.startswith("sim-uc-camera-recording-cam-rec-r1-fhd30-vdis-be67039d")
    assert "170.3mW" in label
    assert "crit 591.4ms" in label


def test_saved_evidence_option_label_without_kpi_is_bare_id():
    assert saved_evidence_option_label({"id": "sim-x"}) == "sim-x"
