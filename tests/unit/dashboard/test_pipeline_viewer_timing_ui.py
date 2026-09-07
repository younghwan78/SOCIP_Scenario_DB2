from pathlib import Path
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard.components import elk_viewer, ui_theme, viewer_api_client, viewer_timing_panel
from dashboard.components.viewer_api_client import ViewerApiError
from scenario_db.view.demo.sample_data import build_sample_level0

PAGE = Path(__file__).resolve().parents[3] / "dashboard/pages/2_Pipeline_Viewer.py"


@pytest.fixture(autouse=True)
def clear_caches():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def _install_api(monkeypatch, *, fail_view_once=False):
    calls = []
    latest_calls = 0
    failed = False

    def request(method, base, path, **kwargs):
        nonlocal latest_calls, failed
        params = kwargs.get("params", {})
        calls.append((path, dict(params)))
        if path == "/soc-platforms":
            return {"items": [{"id": "soc-a"}]}
        if path == "/projects":
            return {"items": [{"id": "project-a", "metadata_": {"soc_ref": "soc-a"}}]}
        if path == "/scenarios":
            return {"items": [{"id": "scenario-a", "metadata_": {"name": "Scenario A"}}]}
        if path.endswith("/variants"):
            return {"items": [{"id": "v1", "design_conditions": {"fps": 30}}]}
        if path == "/simulation/results":
            latest_calls += 1
            return {"items": [{"id": f"sim-{latest_calls}", "kind": "evidence.simulation", "scenario_ref": "scenario-a", "variant_ref": "v1"}]}
        if path.endswith("/view"):
            if fail_view_once and not failed:
                failed = True
                raise ViewerApiError("temporary view failure")
            view = build_sample_level0()
            view.scenario_id, view.variant_id, view.level = "scenario-a", "v1", params["level"]
            view.summary.scenario_id, view.summary.variant_id = "scenario-a", "v1"
            view.mode = params.get("mode", "architecture")
            evidence_id = params.get("sim_evidence_id")
            if evidence_id:
                view.metadata["simulation_evidence_id"] = evidence_id
                view.overlays_available = ["simulation"]
            return view.model_dump(mode="json")
        if path.startswith("/simulation/results/"):
            return {"id": path.rsplit("/", 1)[-1], "kind": "evidence.simulation", "scenario_ref": "scenario-a", "variant_ref": "v1", "timeline_events": [{"task_id": "a", "start_ms": 0, "end_ms": 1}]}
        raise AssertionError(path)

    monkeypatch.setattr(viewer_api_client, "_request_json", request)
    monkeypatch.setattr(viewer_timing_panel, "_request_json", request)
    monkeypatch.setattr(ui_theme, "apply_app_theme", lambda **kwargs: None)
    monkeypatch.setattr(elk_viewer, "render_elk_view", lambda view, **kwargs: st.caption(f"diagram evidence: {view.metadata.get('simulation_evidence_id')}"))
    monkeypatch.setattr(viewer_timing_panel, "render_timing_summary", lambda result: st.caption(f"timing evidence: {result['id']}"))
    monkeypatch.setattr(viewer_timing_panel, "render_timing_chart", lambda *args, **kwargs: None)
    return calls


def _app():
    app = AppTest.from_file(str(PAGE), default_timeout=15)
    app.query_params.update({"scenario_id": "scenario-a", "variant_id": "v1", "sim": "latest", "panel": "timing"})
    return app


def test_full_viewer_pins_one_latest_evidence_across_diagrams_and_timing(monkeypatch):
    calls = _install_api(monkeypatch)
    app = _app().run()
    assert not app.exception
    assert not app.error
    assert len([path for path, _ in calls if path == "/simulation/results"]) == 1
    views = [params for path, params in calls if path.endswith("/view")]
    assert len(views) == 2
    assert {params.get("sim_evidence_id") for params in views} == {"sim-1"}
    assert all("sim" not in params for params in views)
    assert any(path == "/simulation/results/sim-1" for path, _ in calls)
    assert any(caption.value == "timing evidence: sim-1" for caption in app.caption)


def test_view_failure_recovers_on_rerun_without_waiting_for_cache_ttl(monkeypatch):
    _install_api(monkeypatch, fail_view_once=True)
    app = _app().run()
    assert not app.exception
    assert app.error
    app.run()
    assert not app.exception
    assert not app.error
    assert any(caption.value == "timing evidence: sim-1" for caption in app.caption)


def _panel_app():
    from dashboard.components.viewer_timing_panel import render_viewer_timing_panel
    render_viewer_timing_panel(api_base="http://api", evidence_id="sim-a", scenario_id="scenario-a", variant_id="v1", expanded=True)


def test_timing_retry_button_recovers_and_empty_result_is_information(monkeypatch):
    payload = {"id": "sim-a", "kind": "evidence.simulation", "scenario_ref": "scenario-a", "variant_ref": "v1", "timeline_events": []}
    request = Mock(side_effect=[ViewerApiError("temporary failure"), payload])
    monkeypatch.setattr(viewer_timing_panel, "_request_json", request)
    app = AppTest.from_function(_panel_app).run()
    assert not app.exception
    assert app.error
    assert app.button[0].label == "Retry simulation timing"
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert "no timeline events" in app.info[0].value
    assert request.call_count == 2
