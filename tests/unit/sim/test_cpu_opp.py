"""S-05 CPU OPP: SW runtime and CPU power at a declared cluster frequency; the cpu_opp exploration lever."""

import pytest

from scenario_db.api.schemas.scenario_whatif import WhatIfChange
from scenario_db.api.services.design_axes import EXPLORABLE_KINDS
from scenario_db.api.services.whatif_conditions import CHANGE_KINDS, apply_whatif_changes, whatif_targets
from scenario_db.db.models.definition import Project
from scenario_db.sim.cpu_opp import DEFAULT_MEM_BOUND, cpu_opp_condition, factor, opp_mv
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

YT = ("uc-vid-youtube-e2600", "yt-4k60-vp9-hdr10")


def _graph(scenario, variant, **design):
    g = _exynos2600_generated_graph(scenario, variant)
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    g.variant.design_conditions.update(design)
    return g


def _sw(report):
    return {i["task"]: i["runtime_ms"] for s in report["stages"] for i in s["sw_items"] if i["kind"] == "sw"}


def test_runtime_and_voltage_rules():
    assert factor(2000, 2000, 0.3) == 1.0
    assert factor(2000, 1000, 0.3) == pytest.approx(0.7 * 2 + 0.3)
    assert factor(2000, 1000, 1.0) == 1.0  # fully memory-bound: the clock does not matter
    assert (opp_mv(1000), opp_mv(1200), opp_mv(2000)) == (650.0, 720.0, 800.0)
    with pytest.raises(ValueError, match="above the OPP table"):
        opp_mv(2400)
    assert cpu_opp_condition({}) is None
    c = cpu_opp_condition({"cpu_opp_mhz": 1000, "cpu_opp_mv": 700, "cpu_mem_bound": 0.5})
    assert (c["mhz"], c["mv"], c["mem_bound"], c["mv_source"]) == (1000.0, 700.0, 0.5, "design_conditions")
    assert cpu_opp_condition({"cpu_opp_mhz": 1600})["mem_bound"] == DEFAULT_MEM_BOUND
    with pytest.raises(ValueError, match="out of range"):
        cpu_opp_condition({"cpu_opp_mhz": 1000, "cpu_mem_bound": 1.5})


def test_a_lower_opp_stretches_the_cpu_sw_and_lowers_cpu_power():
    base = analyze_timing_budget(_graph(*YT), TimingBudgetOptions())
    low = analyze_timing_budget(_graph(*YT, cpu_opp_mhz=1000), TimingBudgetOptions())
    assert "cpu_opp" not in base
    k = factor(2000, 1000, DEFAULT_MEM_BOUND)
    for task, ms in _sw(base).items():
        assert _sw(low)[task] == pytest.approx(ms * k, rel=1e-3)
    assert low["power"]["cpu_mw"] < base["power"]["cpu_mw"]
    assert low["power"]["cpu_model"]["freq_mhz"] == 1000.0 and low["power"]["cpu_model"]["volt_v"] == 0.65
    assert low["cpu_opp"]["tasks"]["network"]["factor"] == pytest.approx(k, rel=1e-3)
    # the reference OPP reproduces the base result
    same = analyze_timing_budget(_graph(*YT, cpu_opp_mhz=2000), TimingBudgetOptions())
    strip = lambda p: {k: v for k, v in p.items() if k != "cpu_model"}  # noqa: E731 (the model source names the OPP)
    assert strip(same["power"]) == strip(base["power"]) and _sw(same) == _sw(base)


def test_a_gpu_task_timed_by_sw_timing_keeps_its_runtime():
    sc, v = "uc-disp-gallery-e2600", "disp-gallery-fhd-sdr-gpu-heavy"
    base, low = (analyze_timing_budget(_graph(sc, v, **d), TimingBudgetOptions()) for d in ({}, {"cpu_opp_mhz": 1000}))
    assert "gpu" not in low["cpu_opp"]["tasks"] and _sw(low).get("gpu") == _sw(base).get("gpu")


def test_the_profile_cpu_model_refuses_an_opp():
    with pytest.raises(ValueError, match="flat CPU model"):
        analyze_timing_budget(_graph(*YT, cpu_opp_mhz=1000), TimingBudgetOptions(cpu_model="profile"))


def test_the_lever_is_registered_and_sets_the_condition():
    g = _graph(*YT)
    kind = CHANGE_KINDS["cpu_opp"]
    assert "cpu_opp" in EXPLORABLE_KINDS and kind.selector is None
    choices = kind.discover(whatif_targets(g))
    assert choices and set(choices[0]["tasks"]) >= {"network", "sw_demux"} and choices[0]["ladder"][-1] == 2000.0
    cand, _, _ = apply_whatif_changes(g, [WhatIfChange(target="cpu_opp", value=1600)], SimulationRunConfig())
    assert cand.variant.design_conditions["cpu_opp_mhz"] == 1600.0 and "cpu_opp_mhz" not in g.variant.design_conditions
    for bad in (100, 2400):
        with pytest.raises(ValueError):
            apply_whatif_changes(g, [WhatIfChange(target="cpu_opp", value=bad)], SimulationRunConfig())


def test_a_cpu_opp_axis_is_explored_like_any_resim_lever():
    from scenario_db.api.services.design_axes import build_design_plan
    from scenario_db.sim.arch_exploration import LeverAxis

    plan = build_design_plan(_graph(*YT), SimulationRunConfig(),
                             [LeverAxis(lever="cpu_opp", params={}, values=[1000.0, 1600.0])])
    sets = plan["sets"]
    assert len(sets) == 2 and not any("error" in s for s in sets)  # one set per OPP value
