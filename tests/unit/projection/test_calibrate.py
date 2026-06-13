from __future__ import annotations

from scenario_db.projection.calibrate import compute_calibration, kpi_scalar, rail_scalar


def test_kpi_scalar_handles_flat_and_measured():
    assert kpi_scalar(2150) == 2150.0
    assert kpi_scalar({"mean": 2200.0, "p95": 2300.0, "n": 5}) == 2200.0
    assert kpi_scalar({"p95": 2300.0}) is None
    assert kpi_scalar("nope") is None


def test_rail_scalar_key_priority():
    assert rail_scalar({"mean_mw": 1100.0}) == 1100.0
    assert rail_scalar({"power_mw": 900.0}) == 900.0
    assert rail_scalar(640.0) == 640.0
    assert rail_scalar({"voltage": 0.7}) is None


def test_compute_calibration_total_rail_and_kpi_factors():
    u_sim = {
        "kpi": {"total_power_mw": 2000, "frame_latency_ms": 30},
        "vdd_power": {"VDD_CPU": {"mean_mw": 1000.0}, "VDD_CAM": {"mean_mw": 800.0}},
    }
    u_meas = {
        "kpi": {"total_power_mw": {"mean": 2200.0, "n": 5}, "frame_latency_ms": 33.0},
        "vdd_power": {"VDD_CPU": {"mean_mw": 1100.0}, "VDD_CAM": {"mean_mw": 840.0}},
    }
    cal = compute_calibration(u_sim, u_meas)
    assert cal.total_power_factor == 1.1
    assert cal.kpi_factors["total_power_mw"] == 1.1
    assert cal.kpi_factors["frame_latency_ms"] == 1.1
    assert cal.rail_factors["VDD_CPU"] == 1.1
    assert cal.rail_factors["VDD_CAM"] == 1.05
    assert cal.detail["rail:VDD_CPU"] == {"sim": 1000.0, "meas": 1100.0, "factor": 1.1}


def test_compute_calibration_empty_when_no_overlap():
    cal = compute_calibration({"kpi": {"a": 1}}, {"kpi": {"b": 2}})
    assert cal.total_power_factor is None
    assert cal.rail_factors == {}
    assert cal.kpi_factors == {}


def test_compute_calibration_skips_zero_sim():
    cal = compute_calibration(
        {"kpi": {"total_power_mw": 0}}, {"kpi": {"total_power_mw": {"mean": 100.0}}}
    )
    assert cal.total_power_factor is None
