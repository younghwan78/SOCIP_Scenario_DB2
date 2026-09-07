"""Viewer timing panel — pure helpers (no Streamlit runtime needed)."""
from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import Mock

from dashboard.components import viewer_timing_panel as timing
from dashboard.components.viewer_api_client import ViewerApiError

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


@pytest.fixture(autouse=True)
def clear_caches():
    timing.clear_viewer_timing_caches()
    yield
    timing.clear_viewer_timing_caches()


def _evidence(**changes):
    return {"id": "sim-old", "kind": "evidence.simulation", "scenario_ref": "scenario-a", "variant_ref": "v1", "timeline_events": [], **changes}


def test_latest_is_resolved_once_and_panel_uses_applied_view_metadata(monkeypatch):
    request = Mock(side_effect=[{"items": [_evidence()]}, {"items": [_evidence(id="sim-new")]}])
    monkeypatch.setattr(timing, "_request_json", request)
    evidence_id = timing.resolve_overlay_evidence_id("http://api", "scenario-a", "v1", sim_mode="latest", sim_evidence_id=None)
    assert evidence_id == "sim-old"
    view = SimpleNamespace(scenario_id="scenario-a", variant_id="v1", metadata={"simulation_evidence_id": evidence_id})
    assert timing.view_overlay_evidence_id(view, "scenario-a", "v1") == "sim-old"
    assert request.call_count == 1


def test_base_scenario_does_not_query_all_variants(monkeypatch):
    request = Mock()
    monkeypatch.setattr(timing, "_request_json", request)
    assert timing.list_saved_simulation_results("http://api", "scenario-a", None) == []
    assert timing.resolve_overlay_evidence_id("http://api", "scenario-a", None, sim_mode="latest", sim_evidence_id=None) is None
    with pytest.raises(ViewerApiError):
        timing.resolve_overlay_evidence_id("http://api", "scenario-a", None, sim_mode="specific", sim_evidence_id="sim-old")
    request.assert_not_called()


def test_failed_list_is_not_cached_as_empty(monkeypatch):
    request = Mock(side_effect=[ViewerApiError("temporarily unavailable"), {"items": [_evidence()]}])
    monkeypatch.setattr(timing, "_request_json", request)
    with pytest.raises(ViewerApiError):
        timing.list_saved_simulation_results("http://api", "scenario-a", "v1")
    assert timing.list_saved_simulation_results("http://api", "scenario-a", "v1")[0]["id"] == "sim-old"
    assert request.call_count == 2
    assert request.call_args.kwargs["params"]["variant_ref"] == "v1"


def test_failed_detail_is_not_cached_and_success_is_cached(monkeypatch):
    request = Mock(side_effect=[ViewerApiError("temporarily unavailable"), _evidence()])
    monkeypatch.setattr(timing, "_request_json", request)
    with pytest.raises(ViewerApiError):
        timing._load_simulation_result("http://api", "sim-old", "scenario-a", "v1")
    assert timing._load_simulation_result("http://api", "sim-old", "scenario-a", "v1")["id"] == "sim-old"
    timing._load_simulation_result("http://api", "sim-old", "scenario-a", "v1")
    assert request.call_count == 2


@pytest.mark.parametrize("changes", [
    {"kind": "evidence.measurement"}, {"scenario_ref": "other"}, {"variant_ref": "v2"},
    {"id": "other-id"}, {"timeline_events": {}},
])
def test_detail_rejects_wrong_identity_and_malformed_events(monkeypatch, changes):
    monkeypatch.setattr(timing, "_request_json", Mock(return_value=_evidence(**changes)))
    with pytest.raises(ViewerApiError):
        timing._load_simulation_result("http://api", "sim-old", "scenario-a", "v1")


@pytest.mark.parametrize("payload", [{}, {"items": None}, {"items": ["bad"]}, {"items": [_evidence(variant_ref="v2")]}])
def test_list_rejects_malformed_or_foreign_items(monkeypatch, payload):
    monkeypatch.setattr(timing, "_request_json", Mock(return_value=payload))
    with pytest.raises(ViewerApiError):
        timing.list_saved_simulation_results("http://api", "scenario-a", "v1")


def test_empty_success_and_foreign_view_context_are_distinct(monkeypatch):
    monkeypatch.setattr(timing, "_request_json", Mock(return_value={"items": []}))
    assert timing.list_saved_simulation_results("http://api", "scenario-a", "v1") == []
    view = SimpleNamespace(scenario_id="other", variant_id="v1", metadata={"simulation_evidence_id": "sim-old"})
    with pytest.raises(ViewerApiError):
        timing.view_overlay_evidence_id(view, "scenario-a", "v1")
