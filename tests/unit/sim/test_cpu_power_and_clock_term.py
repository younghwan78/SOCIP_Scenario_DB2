"""SW-task CPU power in the simulation total, and the v2-vf set-clock term."""
from __future__ import annotations

import pathlib
import sys

import pytest

pytest.importorskip("networkx")
pytest.importorskip("simpy")

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_is_v15_camera import graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.models.capability.power_model import PowerModelParams  # noqa: E402
from scenario_db.models.evidence.common import ExecutionContext  # noqa: E402
from scenario_db.sim.adapter import build_simulation_inputs  # noqa: E402
from scenario_db.sim.cpu_power import CpuPowerModel, sw_task_cpu_power  # noqa: E402
from scenario_db.sim.dvfs_resolver import DvfsResolver  # noqa: E402
from scenario_db.sim.models import (  # noqa: E402
    DVFSLevel, DVFSTable, IPSimParams, IPWorkload, SimulationRunConfig,
)
from scenario_db.sim.power_model import resolve_power_model  # noqa: E402
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation  # noqa: E402

DB = ROOT / "db_Exynos2600_SM-S947B"


@pytest.fixture(scope="module")
def graph():
    catalog = {}
    for path in (DB / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="f")
    raw = read(DB / "02_definition" / "uc-cam-recording-e2600.yaml")
    return lambda variant: graph_from_fixture(raw, variant, catalog)


def _params(**extra) -> PowerModelParams:
    return PowerModelParams.model_validate({
        "id": "pmp-test", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-exynos2600",
        **extra,
    })


# --- CPU --------------------------------------------------------------------------
def test_cpu_power_is_off_by_default_and_hash_unchanged(graph):
    inputs = build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"))
    result = run_simulation(inputs)
    assert result.cpu_power_mw == 0.0 and result.cpu_breakdown == []
    assert result.power_breakdown["cpu"] == {"total_mw": 0.0, "by_cluster": {}}
    on = build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"), SimulationRunConfig(include_cpu_power=True))
    assert params_hash(inputs) != params_hash(on)  # the switch itself is part of the physics


def test_sw_tasks_of_a_variant_show_up_once_cpu_is_modelled(graph):
    def total(variant, cpu):
        return run_simulation(build_simulation_inputs(graph(variant), SimulationRunConfig(include_cpu_power=cpu)))

    sdr, vdis = total("cam-rec-r1-uhd30-sdr", None), total("cam-rec-r1-uhd30-vdis", None)
    assert sdr.cpu_power_mw == vdis.cpu_power_mw == 0.0             # v1: SW cost invisible
    sdr, vdis = total("cam-rec-r1-uhd30-sdr", True), total("cam-rec-r1-uhd30-vdis", True)
    sdr_tasks, vdis_tasks = ({row["task"] for row in r.cpu_breakdown} for r in (sdr, vdis))
    assert "eis" in vdis_tasks - sdr_tasks                           # VDIS adds SW stages
    assert vdis.cpu_power_mw > sdr.cpu_power_mw
    assert vdis.total_power_mw == pytest.approx(vdis.core_power_mw + vdis.bw_power_mw + vdis.cpu_power_mw)


def test_cpu_active_time_excludes_included_hw_and_evidence_reports_it(graph):
    result = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"),
                                                    SimulationRunConfig(include_cpu_power=True)))
    rows = {row["task"]: row for row in result.cpu_breakdown}
    lme_ms = next(t.hw_time_ms for t in result.timing_breakdown if t.node_id == "lme")
    assert rows["pre_me_rta"]["active_ms"] == pytest.approx(rows["pre_me_rta"]["wall_ms"] - lme_ms, abs=1e-3)
    breakdown = result.power_breakdown["cpu"]
    assert breakdown["total_mw"] == pytest.approx(result.cpu_power_mw)
    assert set(breakdown["by_task"]) == set(rows) and breakdown["model"]["id"] == "em-v1"
    assert any(rail.startswith("CPU_") for rail in result.vdd_power)
    evidence = build_simulation_evidence(
        result, execution_context=ExecutionContext(silicon_rev="EVT0", sw_baseline_ref="sw-x", thermal="room"))
    assert evidence.kpi["cpu_power_mw"] == pytest.approx(result.cpu_power_mw)


def test_power_params_cpu_block_turns_cpu_power_on(graph):
    params = _params(cpu={"clusters": [{"name": n, "coeff_uw_per_mhz_v2": 100.0} for n in ("l", "m", "b", "p")],
                          "freq_mhz": 1000.0, "volt_v": 1.0})
    result = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"), SimulationRunConfig(power_params=params)))
    eis = next(row for row in result.cpu_breakdown if row["task"] == "eis")
    assert eis["power_mw"] == pytest.approx(100.0 * 1000.0 * 1.0 * (3.0 / (1000 / 30)) / 1000.0)
    off = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"),
                                                 SimulationRunConfig(power_params=params, include_cpu_power=False)))
    assert off.cpu_power_mw == 0.0


def test_task_cluster_ratio_and_invocations():
    model = CpuPowerModel()
    warnings: list[str] = []
    rows = sw_task_cpu_power(
        [{"task": "a", "mean_ms": 4.0, "cluster": "prime", "cpu_active_ratio": 0.5},
         {"task": "b", "mean_ms": 2.0, "count_per_frame": 2},
         {"task": "c", "mean_ms": 1.0, "cluster": "cpu4-6"}],
        statistic="mean", period_ms=10.0, hw_time_ms={}, model=model, warnings=warnings,
    )
    by = {r["task"]: r for r in rows}
    assert (by["a"]["active_ms"], by["a"]["cluster"]) == (2.0, "prime")
    assert by["b"]["active_ms"] == 4.0
    assert by["c"]["cluster"] == "mid" and "cpu4-6" in warnings[0]


# --- v2-vf set-clock term ---------------------------------------------------------
def _wl(**kw) -> IPWorkload:
    return IPWorkload(node_id="isp", ip_ref="ip-isp", hw_name="ISP", width=3840, height=2160, fps=30.0,
                      sim_params=IPSimParams(hw_name="ISP", ppc=2, unit_power_mw_mp=10, dvfs_group="CAM", **kw))


TABLE = {"CAM": DVFSTable(domain="CAM", levels=[DVFSLevel(level=0, speed_mhz=600.0, voltages={4: 710.0})])}


def test_v2_equals_v1_without_a_clock_fraction():
    v1 = DvfsResolver(TABLE).resolve([_wl()])["isp"]
    v2 = DvfsResolver(TABLE, power_model=resolve_power_model("v2-vf")).resolve([_wl()])["isp"]
    assert v2.total_power_mw == pytest.approx(v1.total_power_mw) and v2.clock_overhead_mw == 0.0


def test_v2_charges_the_clock_set_above_the_throughput_need():
    v1 = DvfsResolver(TABLE).resolve([_wl()])["isp"]
    cfg = DvfsResolver(TABLE, power_model=resolve_power_model("v2-vf")).resolve([_wl(clock_power_fraction=0.3)])["isp"]
    ratio = cfg.set_clock_mhz / cfg.base_required_clock_mhz
    assert ratio > 1
    assert cfg.total_power_mw == pytest.approx(v1.total_power_mw * (0.7 + 0.3 * ratio))
    assert cfg.clock_overhead_mw == pytest.approx(cfg.total_power_mw - v1.total_power_mw)
    assert cfg.clock_power_fraction == 0.3


def test_v2_default_fraction_comes_from_power_params():
    model = resolve_power_model("v2-vf", _params(ip_model="v2-vf", ip_clock_power_fraction=0.2))
    cfg = DvfsResolver(TABLE, power_model=model).resolve([_wl()])["isp"]
    assert cfg.clock_power_fraction == 0.2 and cfg.clock_overhead_mw > 0
    per_ip = DvfsResolver(TABLE, power_model=model).resolve([_wl(clock_power_fraction=0.0)])["isp"]
    assert per_ip.clock_overhead_mw == 0.0  # the IP's own value wins over the params default


def test_v2_run_through_the_runner_records_overhead(graph):
    params = _params(ip_model="v2-vf", ip_clock_power_fraction=0.25)
    cfg = SimulationRunConfig(power_model="v2-vf", power_params=params)
    v2 = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"), cfg))
    v1 = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis")))
    overhead = v2.power_breakdown["ip"]["clock_overhead_mw"]
    assert overhead > 0
    assert v2.core_power_mw == pytest.approx(v1.core_power_mw + overhead, rel=1e-6)
    assert v2.power_breakdown["model"]["id"] == "v2-vf"


def test_clock_reference_counts_physical_needs_but_not_alignment():
    from scenario_db.sim.clock_models import ClockConstraint

    model = resolve_power_model("v2-vf")
    need = _wl(clock_power_fraction=0.3)
    throughput = DvfsResolver({}, power_model=model).resolve([need])["isp"].base_required_clock_mhz
    vvalid = need.model_copy(update={"clock_constraints": [ClockConstraint(kind="vvalid_stream", mhz=throughput * 2)],
                                     "clock_correction_mhz": throughput * 2})
    cfg = DvfsResolver({}, power_model=model).resolve([vvalid])["isp"]
    assert cfg.clock_ref_mhz == pytest.approx(throughput * 2) and cfg.clock_overhead_mw == pytest.approx(0.0)
    aligned = need.model_copy(update={"clock_constraints": [ClockConstraint(kind="otf_align", mhz=throughput * 2)],
                                      "clock_correction_mhz": throughput * 2})
    cfg = DvfsResolver({}, power_model=model).resolve([aligned])["isp"]
    assert cfg.clock_ref_mhz == pytest.approx(throughput) and cfg.clock_overhead_mw > 0


def test_power_hash_covers_cpu_statistic_and_physical_constraints(graph):
    from scenario_db.sim.clock_models import ClockConstraint

    inputs = build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"), SimulationRunConfig(include_cpu_power=True))
    assert params_hash(inputs) != params_hash(inputs.model_copy(update={"sw_timing_case": "max"}))
    inputs.config = SimulationRunConfig(power_model="v2-vf")
    before = params_hash(inputs)
    inputs.workloads[0].clock_constraints.append(ClockConstraint(kind="vvalid_stream", mhz=900))
    assert params_hash(inputs) != before


def test_prediction_attribution_explains_clock_only_power_change():
    from copy import deepcopy
    from scenario_db.sim.power_attribution import attribute

    old = {"power": {"total_mw": 100, "hw_mw": 100, "cpu_mw": 0, "bw_mw": 0},
           "ips": [{"node": "isp", "power_mw": 100, "activity_mw": 100, "voltage_mv": 710,
                    "set_clock_mhz": 400, "ref_clock_mhz": 400, "clock_power_fraction": 0.5}]}
    new = deepcopy(old)
    new["power"].update(total_mw=150, hw_mw=150)
    new["ips"][0].update(power_mw=150, set_clock_mhz=800)
    result = attribute(old, new)
    assert result["by_category"]["IP clock"] == pytest.approx(50)
    assert result["residual_mw"] == pytest.approx(0)


def test_debug_trace_explains_cpu_and_clock_power(graph):
    params = _params(ip_model="v2-vf", ip_clock_power_fraction=0.25)
    config = SimulationRunConfig(power_model="v2-vf", power_params=params, include_cpu_power=True, debug_trace=True)
    result = run_simulation(build_simulation_inputs(graph("cam-rec-r1-uhd30-vdis"), config))
    trace = result.calculation_trace
    total = trace["kpi"]["total_power_mw"]
    assert total["inputs"]["cpu_power_mw"] == result.cpu_power_mw
    assert sum(total["inputs"].values()) == pytest.approx(total["result"])
    for row in trace["ip"]:
        power = row["power"]
        if power["inputs"].get("clock_power_fraction"):
            assert "set_clock_mhz / ref_clock_mhz" in power["formula"]
