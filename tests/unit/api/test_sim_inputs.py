from __future__ import annotations

from types import SimpleNamespace

import pytest

from scenario_db.api.services.sim_inputs import build_sim_inputs
from scenario_db.sim.driver_models import evaluate_graph
from tests.unit.sim.test_adapter_runner import _fixture_graph

REC = "uc-cam-recording-e2600"


@pytest.fixture(scope="module")
def graph():
    return _fixture_graph("db_Exynos2600_SM-S947B", REC, "cam-rec-r1-uhd30-vdis")


def test_abox_is_an_independent_cadence_row_with_driver_model_power(graph):
    out = build_sim_inputs(graph, driver=evaluate_graph(graph))
    abox = next(r for r in out["rows"] if r["node_id"] == "abox")
    assert abox["kind"] == "hw"
    assert abox["cadence"]["path"] == "independent"
    assert abox["cadence"]["rate_hz"] == pytest.approx(50.0)
    assert abox["cadence"]["per_frame"] == pytest.approx(50.0 / 30.0, rel=1e-3)
    assert abox["duration"] == {"mean_ms": 0.8, "basis": "node_config", "value_source": "assumed"}
    assert abox["load"] == {"duty_pct": pytest.approx(4.0)}
    # ABOX power model is not calibrated yet: the row says so instead of inventing a number
    assert abox["power"] == {"mw": None, "basis": "driver_model", "status": "uncalibrated"}
    assert abox["bw_mbs"] == {"read": 0.0, "write": 0.192}
    assert out["totals"]["independent_nodes"] == 1
    assert any(c["kind"] == "info" and c["node_id"] == "abox" for c in out["checks"])


def test_frame_path_rows_use_fps_sw_timing_and_simulation(graph):
    sim = SimpleNamespace(id="sim-x", timing_breakdown=[{"node_id": "mfc_enc", "hw_time_ms": 7.5}],
                          ip_breakdown=[], dma_breakdown=[{"node_id": "mfc_enc", "direction": "read", "bw_mbs": 120.0}])
    out = build_sim_inputs(graph, sim=sim)
    rows = {r["node_id"]: r for r in out["rows"]}
    assert out["fps"] == 30.0 and out["simulation_ref"] == "sim-x"
    mfc = rows["mfc_enc"]
    assert mfc["cadence"]["path"] == "frame" and mfc["cadence"]["per_frame"] == pytest.approx(1.0)
    assert mfc["duration"]["basis"] == "simulation"
    assert mfc["load"] == {"duty_pct": pytest.approx(7.5 * 30 / 10)}
    assert mfc["bw_mbs"] == {"read": 120.0, "write": 0.0}
    eis = rows["eis"]
    assert eis["kind"] == "sw" and eis["duration"]["basis"] == "sw_timing"
    assert eis["load"]["cpu_ms_per_s"] == pytest.approx(eis["duration"]["mean_ms"] * 30)
    assert out["totals"]["sw_cpu_ms_per_s"] == pytest.approx(
        sum(r["load"]["cpu_ms_per_s"] for r in out["rows"] if r["kind"] == "sw" and r["load"]))


def test_defined_sw_timing_far_from_measurement_is_a_value_check(graph):
    measured = ("meas-1", {"eis_warp": {"task": "eis_warp", "mean_ms": 7.8}, "hal_request_thread": {"mean_ms": 2.3}})
    out = build_sim_inputs(graph, measured=measured)
    checks = [c for c in out["checks"] if c["kind"] == "value"]
    assert [c["node_id"] for c in checks] == ["eis"]
    assert "eis_warp" in checks[0]["detail"] and "meas-1" in checks[0]["detail"]
    assert out["measurement_ref"] == "meas-1"


def test_sw_cpu_load_excludes_included_hw_like_the_cpu_power_model(graph):
    """pre_me_rta wall time includes LME: CPU ms/s follows sim.cpu_power (wall − included HW) × active ratio."""
    sim = SimpleNamespace(id="sim-x", timing_breakdown=[{"node_id": "lme", "hw_time_ms": 1.5}], ip_breakdown=[], dma_breakdown=[])
    rows = {r["node_id"]: r for r in build_sim_inputs(graph, sim=sim)["rows"]}
    rta = rows["pre_me_rta"]
    mean = rta["duration"]["mean_ms"]
    assert rta["load"]["wall_ms_per_s"] == pytest.approx(mean * 30, abs=1e-3)
    assert rta["load"]["included_hw_ms"] == pytest.approx(1.5)
    assert rta["load"]["cpu_ms_per_s"] == pytest.approx((mean - 1.5) * rta["load"]["cpu_active_ratio"] * 30, abs=1e-3)
