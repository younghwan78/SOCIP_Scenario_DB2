from __future__ import annotations

import pytest

from scenario_db.projection.calibrate import compute_calibration
from scenario_db.projection.models import ClusterScaling, ProjectionRecipe
from scenario_db.projection.project import (
    assemble_projection,
    generate_projection_id,
    project_power,
    project_sw_timing,
)
from scenario_db.models.evidence.simulation import SimulationEvidence


def _cal():
    return compute_calibration(
        {"kpi": {"total_power_mw": 2000}, "vdd_power": {"VDD_CPU": {"mean_mw": 1000.0}}},
        {"kpi": {"total_power_mw": {"mean": 2200.0, "n": 5}}, "vdd_power": {"VDD_CPU": {"mean_mw": 1100.0}}},
    )


def test_cluster_scaling_derives_time_scale_from_capacity():
    cs = ClusterScaling(u_capacity_mhz=3000, v_capacity_mhz=3750)
    assert cs.time_scale == 0.8


def test_cluster_scaling_requires_scale_or_capacities():
    with pytest.raises(ValueError, match="time_scale"):
        ClusterScaling()


def test_project_power_scales_kpi_vdd_and_ip():
    cal = _cal()
    v_sim = {
        "kpi": {"total_power_mw": 3000, "frame_latency_ms": 28},
        "vdd_power": {"VDD_CPU": {"mean_mw": 1500.0}, "VDD_GPU": {"mean_mw": 500.0}},
        "ip_breakdown": [{"ip": "ip-isp-v13", "power_mW": 800, "submodules": [{"sub": "ISP.TNR", "power_mW": 300}]}],
    }
    out = project_power(v_sim, cal, scale_ip_breakdown=True)
    # total power scaled by 1.1
    assert out["kpi"]["total_power_mw"] == 3300.0
    # frame_latency has no factor here (cal only had total + VDD_CPU) -> unchanged
    assert out["kpi"]["frame_latency_ms"] == 28
    assert "frame_latency_ms" in out["trace"]["unscaled_kpi"]
    # VDD_CPU uses its own rail factor; VDD_GPU falls back to total factor
    assert out["vdd_power"]["VDD_CPU"]["mean_mw"] == 1650.0
    assert out["vdd_power"]["VDD_GPU"]["mean_mw"] == 550.0
    assert out["trace"]["scaled_rails"]["VDD_CPU"]["source"] == "rail"
    assert out["trace"]["scaled_rails"]["VDD_GPU"]["source"] == "total"
    # ip_breakdown uniform-scaled by total factor
    assert out["ip_breakdown"][0]["power_mW"] == 880.0
    assert out["ip_breakdown"][0]["submodules"][0]["power_mW"] == 330.0


def test_project_power_passthrough_ip_when_disabled():
    cal = _cal()
    v_sim = {"kpi": {"total_power_mw": 3000}, "ip_breakdown": [{"ip": "ip-x", "power_mW": 100}]}
    out = project_power(v_sim, cal, scale_ip_breakdown=False)
    assert out["ip_breakdown"][0]["power_mW"] == 100
    assert out["trace"]["ip_breakdown"]["mode"] == "passthrough"


def test_project_sw_timing_scales_by_cluster():
    recipe = ProjectionRecipe.model_validate(
        {
            "sources": {"u_measurement": "a", "u_simulation": "b", "v_simulation": "c"},
            "target": {"project_ref": "proj-v", "scenario_ref": "uc-x-v", "variant_ref": "v1", "sw_baseline_ref": "sw-vendor-v1.3.0"},
            "cluster_scaling": {"BIG": {"time_scale": 0.8}},
        }
    )
    u_meas = {
        "sw_task_timing": [
            {"task": "eis_warp", "cluster": "BIG", "mean_ms": 8.0, "p95_ms": 10.0, "max_ms": 14.0, "samples": 1500},
            {"task": "misc", "cluster": "LIT", "mean_ms": 2.0},  # LIT not in scaling -> unscaled
        ]
    }
    out = project_sw_timing(u_meas, recipe)
    eis = next(t for t in out["sw_task_timing"] if t["task"] == "eis_warp")
    assert eis["mean_ms"] == 6.4
    assert eis["p95_ms"] == 8.0
    assert eis["max_ms"] == 11.2
    assert eis["samples"] == 1500  # counts unchanged
    misc = next(t for t in out["sw_task_timing"] if t["task"] == "misc")
    assert misc["mean_ms"] == 2.0
    assert "misc" in out["trace"]["missing_cluster_scale"]


def test_generate_projection_id():
    recipe = ProjectionRecipe.model_validate(
        {
            "sources": {"u_measurement": "a", "u_simulation": "b", "v_simulation": "c"},
            "target": {"project_ref": "proj-v", "scenario_ref": "uc-camera-recording-v", "variant_ref": "cam-rec-uhd30-vdis", "sw_baseline_ref": "sw-vendor-v1.3.0"},
        }
    )
    assert generate_projection_id(recipe) == "sim-uc-camera-recording-v-cam-rec-uhd30-vdis-PRE-SI-projection"


def test_assemble_projection_is_valid_simulation_evidence():
    cal = _cal()
    recipe = ProjectionRecipe.model_validate(
        {
            "sources": {"u_measurement": "a", "u_simulation": "b", "v_simulation": "c"},
            "target": {"project_ref": "proj-v-nextgen", "scenario_ref": "uc-camera-recording-v", "variant_ref": "cam-rec-uhd30-vdis", "sw_baseline_ref": "sw-vendor-v1.3.0"},
            "cluster_scaling": {"BIG": {"time_scale": 0.8}},
        }
    )
    u_meas = {"id": "meas-uc-x-v1-EVT1-20260610", "sw_task_timing": [{"task": "eis_warp", "cluster": "BIG", "mean_ms": 8.0}]}
    u_sim = {"id": "sim-uc-x-v1-EVT1-20260601"}
    v_sim = {
        "id": "sim-uc-x-v1-PRESI-20260612",
        "execution_context": {"thermal": "room"},
        "kpi": {"total_power_mw": 3000},
        "vdd_power": {"VDD_CPU": {"mean_mw": 1500.0}},
    }
    doc = assemble_projection(recipe, u_meas, u_sim, v_sim, cal)

    assert doc["kind"] == "evidence.simulation"
    assert doc["execution_context"]["method"] == "projection"
    assert doc["project_ref"] == "proj-v-nextgen"
    assert doc["derived_from"] == [u_meas["id"], u_sim["id"], v_sim["id"]]
    assert doc["kpi"]["total_power_mw"] == 3300.0
    assert doc["sw_task_timing"][0]["mean_ms"] == 6.4
    assert doc["calculation_trace"]["projection"]["calibration"]["total_power_factor"] == 1.1

    # validates against the contract (sw_task_timing now allowed on sim evidence)
    SimulationEvidence.model_validate(doc)
