from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from dashboard.components.camera_review import (
    BASIC_KPIS,
    coverage,
    evidence_notes,
    kpi_label,
    review_groups,
    scenario_variants,
    workload_factors,
)


def variant(variant_id="rear-fhd30", **design):
    return {
        "project_id": "project-a", "scenario_id": "camera-recording",
        "scenario_name": "Camera Recording", "category": ["camera"],
        "variant_id": variant_id, "severity": "heavy",
        "design_conditions": {"resolution": "FHD", "fps": 30, **design},
        "viewer_query": {"project_id": "project-a", "scenario_id": "camera-recording", "variant_id": variant_id},
    }


def test_basic_coverage_does_not_count_special_modes_or_other_projects():
    base = variant()
    other = {**base, "project_id": "project-b"}
    items = [base, other, variant("portrait", portrait=True), variant("dual", camera_mode="dual_async")]
    scoped = scenario_variants(base, items)
    assert other not in scoped
    assert coverage(scoped, "recording", BASIC_KPIS)["FHD30"] == 1
    assert coverage(items, "portrait", ("FHD30",))["FHD30"] == 1


def test_mode_classification_supports_combined_workloads_and_false_flags():
    assert set(review_groups(variant(portrait=True, camera_mode="dual_sync", fps=120))) == {"portrait", "dual", "slow"}
    assert review_groups(variant(portrait="false", pro_video="off", histogram_enabled=False)) == ("recording",)
    assert review_groups(variant(camera_mode="pro_video", histogram_enabled=True)) == ("pro",)
    assert review_groups(variant("cam-rec-rtriple-fhd30", camera_mode="triple")) == ("other",)
    assert review_groups({**variant(), "scenario_id": "camera-preview", "scenario_name": "Camera Preview"}) == ("other",)
    assert review_groups({**variant(), "category": ["video_playback"]}) == ()
    for purpose in ("capture", "preview"):
        shared_flag = {**variant(is_scenario="IS_SCENARIO_PRO_VIDEO"), "scenario_id": f"camera-{purpose}", "scenario_name": purpose}
        assert review_groups(shared_flag) == ("other",)
    assert review_groups(variant(is_scenario="IS_SCENARIO_PRO_VIDEO")) == ("pro",)


@pytest.mark.parametrize("fps", [None, False, 0, -30, "unknown", "nan", "inf"])
def test_bad_or_missing_fps_never_inferred_from_id(fps):
    item = variant("cam-rec-r1-8k30", resolution="8K", fps=fps)
    assert kpi_label(item) == "KPI 조건 미상"
    assert coverage([item], "recording", BASIC_KPIS)["8K30"] == 0


def test_explicit_fps_wins_over_subscenario_and_resolution_must_be_present():
    assert kpi_label(variant(resolution="8K", fps=24, subscenario="8K_30FPS_VIDEO")) == "8K24"
    assert kpi_label(variant("cam-rec-f1-uhd120", resolution=None, fps=120)) == "KPI 조건 미상"
    assert kpi_label(variant(resolution="3840x2160", fps="60")) == "UHD60"


def test_workload_explanation_preserves_stored_grade_and_processing_assumptions():
    item = variant("portrait", portrait=True, portrait_hw_source="assumed_VPS_SEG_CPU_bokeh", fps=240, sensor_input_fps=120)
    before = deepcopy(item)
    text = " ".join(detail for _, detail in workload_factors(item))
    assert "assumed_VPS_SEG_CPU_bokeh" in text
    assert "Sensor 120 fps / 목표 240 fps" in text
    assert "4.17 ms" in text
    assert item == before
    assert evidence_notes({**item, "tags": ["assumed-sw-timing", "uncalibrated-power"]}) == ["SW 시간: 가정값", "전력: 미보정"]


def test_review_panels_can_select_empty_pro_and_filter_kpi():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
import streamlit as st
from dashboard.components.camera_review_view import render_camera_matrix
items = st.session_state["items"]
visible = render_camera_matrix(items)
st.text("visible=" + str(len(visible)))
''')
    app.session_state["items"] = [variant(), variant("uhd60", resolution="UHD", fps=60), variant("portrait", portrait=True)]
    app.run()
    assert not app.exception
    app.selectbox(key="camera_matrix_kpi_all").select("UHD60").run()
    assert not app.exception
    assert app.text[0].value == "visible=1"
    app.session_state["camera_matrix_group"] = "pro"
    app.run()
    assert not app.exception
    assert app.text[0].value == "visible=0"
    assert len(app.info) == 1
    app.session_state["camera_matrix_group"] = "portrait"
    app.run()
    assert not app.exception
    assert app.text[0].value == "visible=1"


def test_full_explorer_page_renders_and_keeps_non_camera_navigation(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from dashboard.components import explorer_api_client, viewer_api_client

    camera = variant()
    playback = {**variant("play"), "category": ["video_playback"], "scenario_id": "playback", "scenario_name": "Video Playback"}
    scenarios = [{**item, "variant_count": 1, "severity_counts": {"heavy": 1}} for item in [camera, playback]]
    summary = {"category_counts": [{"key": "camera", "count": 1}, {"key": "video_playback", "count": 1}], "severity_counts": [{"key": "heavy", "count": 2}]}
    monkeypatch.setattr(viewer_api_client, "list_soc_platforms", lambda *a, **k: [])
    monkeypatch.setattr(viewer_api_client, "list_projects", lambda *a, **k: [])
    monkeypatch.setattr(explorer_api_client, "get_summary", lambda *a, **k: summary)
    def scoped(items, filters):
        return [item for item in items if not filters.get("category") or item["category"][0] in filters["category"]]
    def catalog(*args, **filters):
        rows = scoped(scenarios, filters)
        return {"items": rows, "total": len(rows)}
    def matrix(*args, **filters):
        rows = scoped([camera, playback], filters)
        return {"items": rows, "total": len(rows), "axis_keys": ["resolution", "fps"]}
    monkeypatch.setattr(explorer_api_client, "get_scenario_catalog", catalog)
    monkeypatch.setattr(explorer_api_client, "get_variant_matrix", matrix)
    monkeypatch.setattr(explorer_api_client, "get_import_health", lambda *a, **k: {})
    page = Path(__file__).resolve().parents[3] / "dashboard/pages/1_DB_Explorer.py"
    app = AppTest.from_file(str(page)).run(timeout=20)
    assert not app.exception
    filters = next(element for element in app.expander if element.label.startswith("추가 필터"))
    assert not filters.proto.expanded
    assert any("Key conditions" in element.value for element in app.markdown)
    assert not any("Camera 검토 현황" in element.value for element in app.markdown)
    assert not any(str(element.key).startswith("camera_matrix_") for element in app.selectbox)
    for category, visible in [("camera", True), ("__all__", False), ("camera", True), ("video_playback", False)]:
        app.session_state["explorer_category_choice"] = category
        app.run(timeout=20)
        assert not app.exception
        assert any("Camera 검토 현황" in element.value for element in app.markdown) == visible
        assert any(str(element.key).startswith("camera_matrix_") for element in app.selectbox) == visible



def test_catalog_html_escapes_untrusted_project_data():
    from dashboard.components.camera_review_view import badge, catalog_camera_summary
    assert "<script>" not in badge("<script>alert(1)</script>")
    item = variant(portrait=True)
    assert "Portrait video" in catalog_camera_summary(item, [item])
