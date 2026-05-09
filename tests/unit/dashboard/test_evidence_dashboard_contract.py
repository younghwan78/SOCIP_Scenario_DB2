from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dashboard.components.evidence_dashboard_contract import (
    PREVIEW_ACTION_LABELS,
    RESULT_BREAKDOWN_TABS,
    SAVED_ACTION_LABELS,
    SIDEBAR_SELECTORS,
    SIMULATION_RESULT_TOP_TABS,
    VIEWER_LINK_LABEL_PREVIEW,
    VIEWER_LINK_LABEL_SAVED,
    build_pipeline_viewer_url,
    warning_severity,
)


def test_pipeline_viewer_preview_url_has_no_evidence_overlay():
    url = build_pipeline_viewer_url(
        api_base="http://127.0.0.1:18000/api/v1",
        soc_id="soc-exynos2500",
        project_id="proj-demo-import",
        scenario_id="uc-demo-import-recording",
        variant_id="FHD30-Imported",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.path == "/Pipeline_Viewer"
    assert query["scenario_id"] == ["uc-demo-import-recording"]
    assert query["variant_id"] == ["FHD30-Imported"]
    assert "sim_evidence_id" not in query


def test_pipeline_viewer_saved_url_includes_evidence_overlay():
    url = build_pipeline_viewer_url(
        api_base="http://127.0.0.1:18000/api/v1",
        scenario_id="uc-demo-import-recording",
        variant_id="FHD30-Imported",
        evidence_id="sim-123",
    )

    query = parse_qs(urlparse(url).query)

    assert query["sim_evidence_id"] == ["sim-123"]


def test_required_evidence_dashboard_labels_are_contractually_present():
    assert SIDEBAR_SELECTORS == (
        "SoC Platform",
        "Project / Board",
        "Scenario Category",
        "Scenario",
        "Variant",
    )
    assert SIMULATION_RESULT_TOP_TABS == ("Preview Run", "Saved Evidence")
    assert RESULT_BREAKDOWN_TABS == (
        "External Device Info",
        "IP/Node Power",
        "DMA BW",
        "Timing Chart",
        "Timing Table",
        "Timeline Table",
        "Debug Trace",
        "Raw Evidence",
    )
    assert VIEWER_LINK_LABEL_PREVIEW in PREVIEW_ACTION_LABELS
    assert VIEWER_LINK_LABEL_SAVED in SAVED_ACTION_LABELS


def test_warning_severity_promotes_zero_compute_results_to_error():
    assert warning_severity([]) == "none"
    assert warning_severity(["isp0 has no capabilities.sim"]) == "warning"
    assert warning_severity(["All compute IP core power is zero; check metadata"]) == "error"
    assert warning_severity(["All compute IP HW time is zero; check metadata"]) == "error"


def test_evidence_dashboard_page_uses_shared_contract_for_viewer_links():
    root = Path(__file__).resolve().parents[3]
    source = (root / "dashboard" / "pages" / "4_Evidence_Dashboard.py").read_text(encoding="utf-8")

    assert "VIEWER_LINK_LABEL_PREVIEW" in source
    assert "VIEWER_LINK_LABEL_SAVED" in source
    assert "RESULT_BREAKDOWN_TABS" in source
    assert "SIMULATION_RESULT_TOP_TABS" in source
    assert source.count("_render_viewer_tab_link(") >= 3

    preview_block = source[source.index("with preview_tab:"):source.index("with saved_tab:")]
    saved_block = source[source.index("with saved_tab:"):]
    assert "_render_viewer_tab_link(" in preview_block
    assert "_render_viewer_tab_link(" in saved_block
