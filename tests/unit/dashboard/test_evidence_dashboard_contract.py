from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dashboard.components.evidence_context import (
    category_label,
    default_silicon_rev,
    filter_scenarios_by_category,
    filter_scenarios_by_text,
    scenario_categories,
)
from dashboard.components.evidence_dashboard_contract import (
    PREVIEW_ACTION_LABELS,
    RESULT_BREAKDOWN_TABS,
    SAVED_ACTION_LABELS,
    SIDEBAR_SELECTORS,
    SIMULATION_RESULT_TOP_TABS,
    VIEWER_LINK_LABEL_PREVIEW,
    VIEWER_LINK_LABEL_SAVED,
    build_pipeline_viewer_url,
    readiness_issue_lines,
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
    result_view_source = (root / "dashboard" / "components" / "evidence_result_view.py").read_text(encoding="utf-8")
    actions_source = (root / "dashboard" / "components" / "evidence_actions.py").read_text(encoding="utf-8")
    results_panel_source = (root / "dashboard" / "components" / "evidence_results_panel.py").read_text(encoding="utf-8")
    timing_chart_source = (root / "dashboard" / "components" / "timing_chart.py").read_text(encoding="utf-8")
    tables_source = (root / "dashboard" / "components" / "simulation_tables.py").read_text(encoding="utf-8")
    compare_source = (root / "dashboard" / "components" / "evidence_compare.py").read_text(encoding="utf-8")
    debug_source = (root / "dashboard" / "components" / "evidence_debug_trace.py").read_text(encoding="utf-8")

    assert "render_evidence_results_panel" in source
    assert "VIEWER_LINK_LABEL_PREVIEW" in results_panel_source
    assert "VIEWER_LINK_LABEL_SAVED" in results_panel_source
    assert "RESULT_BREAKDOWN_TABS" in result_view_source
    assert "render_timing_chart" in result_view_source
    assert "def render_timing_chart" in timing_chart_source
    assert "def render_timing_summary" in timing_chart_source
    assert "render_ip_node_power" in result_view_source
    assert "def render_ip_node_power" in tables_source
    assert "def render_dma_bw" in tables_source
    assert "def render_external_device_info" in tables_source
    assert "render_result_breakdown" in results_panel_source
    assert "render_debug_trace" in result_view_source
    assert "def render_debug_trace" in debug_source
    assert "render_preview_actions" in results_panel_source
    assert "render_saved_export_actions" in results_panel_source
    assert "render_preview_saved_comparison" in results_panel_source
    assert "def render_preview_saved_comparison" in compare_source
    assert "def comparison_rows" in compare_source
    assert "SIMULATION_RESULT_TOP_TABS" in results_panel_source
    assert results_panel_source.count("render_viewer_tab_link(") >= 2
    assert "build_pipeline_viewer_url" in actions_source
    assert "PREVIEW_ACTION_LABELS" in actions_source
    assert "SAVED_ACTION_LABELS" in actions_source

    preview_block = results_panel_source[
        results_panel_source.index("def _render_preview_result"):results_panel_source.index("def _render_saved_results")
    ]
    saved_block = results_panel_source[
        results_panel_source.index("def _render_saved_result_detail"):results_panel_source.index("def _after_preview_saved")
    ]
    assert "render_viewer_tab_link(" in preview_block
    assert "render_viewer_tab_link(" in saved_block


def test_evidence_dashboard_page_renders_readiness_component():
    root = Path(__file__).resolve().parents[3]
    source = (root / "dashboard" / "pages" / "4_Evidence_Dashboard.py").read_text(encoding="utf-8")
    context_source = (root / "dashboard" / "components" / "evidence_context.py").read_text(encoding="utf-8")

    assert "render_evidence_context_sidebar" in source
    assert "render_simulation_readiness" in context_source


def test_evidence_dashboard_page_uses_run_form_component():
    root = Path(__file__).resolve().parents[3]
    source = (root / "dashboard" / "pages" / "4_Evidence_Dashboard.py").read_text(encoding="utf-8")
    run_panel_source = (root / "dashboard" / "components" / "evidence_run_panel.py").read_text(encoding="utf-8")
    form_source = (root / "dashboard" / "components" / "simulation_run_form.py").read_text(encoding="utf-8")

    assert "render_evidence_run_panel" in source
    assert "render_simulation_run_form" in run_panel_source
    assert '"Run Preview"' in form_source
    assert "DEFAULT_DVFS_TABLES" in form_source
    assert "THERMAL_PRESETS" in form_source
    assert "persist" in form_source


def test_evidence_dashboard_can_hide_run_panel_for_wide_results():
    root = Path(__file__).resolve().parents[3]
    source = (root / "dashboard" / "pages" / "4_Evidence_Dashboard.py").read_text(encoding="utf-8")

    assert "evidence_run_panel_visible" in source
    assert "Hide Run Simulation" in source
    assert "Show Run Simulation" in source
    assert "st.container()" in source
    assert "render_evidence_results_panel" in source


def test_evidence_dashboard_sidebar_keeps_scenario_search_control():
    root = Path(__file__).resolve().parents[3]
    source = (root / "dashboard" / "pages" / "4_Evidence_Dashboard.py").read_text(encoding="utf-8")
    context_source = (root / "dashboard" / "components" / "evidence_context.py").read_text(encoding="utf-8")

    assert "render_evidence_context_sidebar" in source
    assert '"Scenario Search"' in context_source
    assert "filter_scenarios_by_text" in context_source


def test_db_explorer_sidebar_uses_compact_context_labels():
    root = Path(__file__).resolve().parents[3]
    source = (root / "dashboard" / "pages" / "1_DB_Explorer.py").read_text(encoding="utf-8")

    assert "compact_soc_label" in source
    assert "compact_project_label" in source
    assert "compact_scenario_label" in source
    assert "\n    soc_label,\n" not in source
    assert "\n    project_label,\n" not in source
    assert "scenario_id} - " not in source


def test_evidence_context_filters_scenarios_by_category_and_text():
    scenarios = [
        {"id": "uc-camera-recording", "metadata": {"category": "camera", "name": "Camera Recording"}},
        {"id": "uc-video-playback", "metadata_": {"domain": "video_playback", "name": "Video Playback"}},
        {"id": "uc-audio-call", "metadata": {"category": ["audio", "voice_call"], "name": "Voice Call"}},
    ]

    assert scenario_categories(scenarios) == ["all", "audio", "camera", "video_playback", "voice_call"]
    assert category_label("video_playback") == "Video Playback"
    assert [item["id"] for item in filter_scenarios_by_category(scenarios, "camera")] == ["uc-camera-recording"]
    assert [item["id"] for item in filter_scenarios_by_category(scenarios, "voice_call")] == ["uc-audio-call"]
    assert [item["id"] for item in filter_scenarios_by_text(scenarios, "record")] == ["uc-camera-recording"]
    assert filter_scenarios_by_text(scenarios, "") == scenarios


def test_evidence_context_default_silicon_rev_uses_soc_generation():
    assert default_silicon_rev("soc-exynos2600") == "EVT1.3"
    assert default_silicon_rev("soc-exynos2500") == "EVT0"


def test_readiness_issue_lines_include_blocking_node_reason():
    report = {
        "errors": [
            {
                "code": "MISSING_PPC",
                "node_id": "lme",
                "message": "ppc is required for clock and timing simulation.",
            }
        ],
        "warnings": [
            {
                "code": "MISSING_UNIT_POWER",
                "node_id": "lme",
                "message": "unit_power_mw_mp is zero.",
            }
        ],
    }

    assert readiness_issue_lines(report) == [
        "MISSING_PPC / lme: ppc is required for clock and timing simulation.",
        "MISSING_UNIT_POWER / lme: unit_power_mw_mp is zero.",
    ]
