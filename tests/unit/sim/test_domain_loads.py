"""D-03 domain loads: GPU / NPU / audio DSP power from a declared work rate (util x f x V^2 + leakage)."""

import pytest

from scenario_db.db.models.definition import Project
from scenario_db.sim.domain_loads import DOMAIN_MODELS, domain_load_config
from scenario_db.sim.engine_revisions import OPT_IN
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

VF = [{"mhz": 200, "mv": 600}, {"mhz": 400, "mv": 700}, {"mhz": 800, "mv": 800}]
CFG = {"coeff_uw_per_mhz_v2": 1000.0, "vf": VF, "leakage": {"mw_at_ref": 10.0, "ref_mv": 800.0, "exponent": 2.0},
       "target_util": 0.8, "idle_gated": 0.5}


def _report(scenario, variant, mutate=None):
    g = _exynos2600_generated_graph(scenario, variant)
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    if mutate:
        mutate(g)
    return analyze_timing_budget(g, TimingBudgetOptions())


def test_the_governor_picks_the_lowest_frequency_within_the_target_and_power_follows():
    m = DOMAIN_MODELS["util-vf-v1"]
    low = m.estimate(node_id="gpu", cfg={**CFG, "mcycles_per_frame": 2.0}, rate_hz=60, pixels=None)
    assert (low["freq_mhz"], low["util"]) == (200.0, 0.6)  # 120 Mcycle/s fits 200 MHz at <= 0.8
    assert low["dynamic_mw"] == pytest.approx(0.6 * 1000 * 200 * 0.6 ** 2 / 1000)
    assert low["static_mw"] == pytest.approx(10 * (600 / 800) ** 2 * (0.6 + 0.4 * 0.5))
    high = m.estimate(node_id="gpu", cfg={**CFG, "mcycles_per_frame": 2.0}, rate_hz=120, pixels=None)
    assert high["freq_mhz"] == 400.0 and high["mw"] > low["mw"]
    # pixel scaling and per-layer work
    big = m.estimate(node_id="gpu", cfg={**CFG, "mcycles_per_frame": 1.0, "ref_pixels": 100, "pixel_exponent": 1.0},
                     rate_hz=60, pixels=400)
    assert big["work_mcycles_s"] == 240.0 and big["pixel_scale"] == 4.0
    layered = m.estimate(node_id="gpu", cfg={**CFG, "mcycles_per_layer": 0.5}, rate_hz=10, pixels=None, layers=4)
    assert layered["work_mcycles_s"] == 20.0


def test_overload_is_infeasible_and_a_fixed_operating_point_is_kept():
    m = DOMAIN_MODELS["util-vf-v1"]
    over = m.estimate(node_id="npu", cfg={**CFG, "mcycles_per_s": 1000.0}, rate_hz=30, pixels=None)
    assert over["freq_mhz"] == 800.0 and over["util"] > 1 and over["feasible"] is False and "reason" in over
    fixed = m.estimate(node_id="abox", cfg={**CFG, "mcycles_per_s": 20.0, "freq_mhz": 400.0}, rate_hz=0, pixels=None)
    assert fixed["freq_by"] == "fixed" and fixed["util"] == 0.05


@pytest.mark.parametrize("cfg,match", [
    ({"vf": VF, "mcycles_per_s": 1}, "coeff"),
    ({**CFG}, "mcycles"),
    ({**CFG, "mcycles_per_layer": 1.0}, "input_layers"),
    ({**CFG, "mcycles_per_s": -1}, "out of range"),
])
def test_incomplete_declarations_are_refused(cfg, match):
    with pytest.raises(ValueError, match=match):
        DOMAIN_MODELS["util-vf-v1"].estimate(node_id="x", cfg=cfg, rate_hz=30, pixels=None)


def test_merge_order_catalog_then_pipeline_node_then_variant_and_opt_out():
    caps = {"power_model": {"profiler_dynamic_coeff": 500, "vf_table_sample": VF},
            "dvfs_model": {"freq_table_khz": [200000, 400000]}}
    assert domain_load_config(caps, {"id": "gpu"}, {}) is None  # no declaration = not opted in
    cfg = domain_load_config(caps, {"id": "gpu", "domain_load": {"coeff_uw_per_mhz_v2": 900, "mcycles_per_frame": 1}},
                             {"sim": {"domain_load": {"mcycles_per_frame": 3}}})
    assert (cfg["coeff_uw_per_mhz_v2"], cfg["mcycles_per_frame"], cfg["freqs_mhz"]) == (900, 3, [200.0, 400.0])
    abox = domain_load_config({}, {"id": "abox", "domain_load": {"mcycles_per_s": 5}}, {"dvfs": {"aud_freq_khz": 200000}})
    assert abox["freq_mhz"] == 200.0  # the node's declared AUD operating point
    assert domain_load_config(caps, {"id": "gpu", "domain_load": {"mcycles_per_s": 1}}, {"sim": {"domain_load": "none"}}) is None
    with pytest.raises(ValueError, match="unknown domain_load keys"):
        domain_load_config(caps, {"id": "gpu", "domain_load": {"gamma": 1}}, {})


def test_e2600_game_gpu_power_rises_with_fps_and_is_no_longer_zero():
    r60 = _report("uc-game-play-e2600", "game-fhd-60fps-sdr")
    r120 = _report("uc-game-play-e2600", "game-fhd-120fps-sdr")
    g60, g120 = r60["power"]["domain_loads"]["gpu"], r120["power"]["domain_loads"]["gpu"]
    assert g60["value_source"] == "assumed" and g120["freq_mhz"] > g60["freq_mhz"] and g120["mw"] > g60["mw"]
    assert "gpu" not in r60["power"]["zero_power_ips"]
    assert r60["power"]["hw_by_ip"]["gpu"] == pytest.approx(g60["mw"], abs=1e-3)
    assert r60["power"]["hw_mw"] == pytest.approx(sum(r60["power"]["hw_by_ip"].values()), abs=0.01)


def test_a_gpu_task_timed_by_sw_timing_is_not_charged_as_cpu_work():
    with_load = _report("uc-disp-gallery-e2600", "disp-gallery-fhd-sdr-gpu-heavy")
    assert "gpu" in with_load["power"]["domain_loads"] and "gpu" not in with_load["power"]["cpu_by_task"]

    def opt_out(g):
        g.variant.node_configs.setdefault("gpu", {}).setdefault("sim", {})["domain_load"] = "none"
    without = _report("uc-disp-gallery-e2600", "disp-gallery-fhd-sdr-gpu-heavy", opt_out)
    assert "domain_loads" not in without["power"] and without["power"]["cpu_by_task"].get("gpu", 0) > 0
    # its time stays in the chain either way
    assert [s["sw_ms"] for s in with_load["stages"]] == [s["sw_ms"] for s in without["stages"]]


def test_an_infeasible_domain_load_fails_the_verdict():
    def heavy(g):
        g.variant.node_configs["gpu"]["sim"]["domain_load"] = {"mcycles_per_frame": 100.0}
    r = _report("uc-game-play-e2600", "game-fhd-60fps-sdr", heavy)
    assert r["verdict"]["status"] == "fail" and any("domain 부하" in x for x in r["verdict"]["reasons"])


def test_audio_offload_costs_abox_power_at_its_fixed_operating_point():
    on = _report("uc-aud-mp3-playback-e2600", "audio-mp3-screen-on")["power"]["domain_loads"]["abox"]
    off = _report("uc-aud-mp3-playback-e2600", "audio-mp3-screen-off-offload")["power"]["domain_loads"]["abox"]
    assert (on["freq_by"], on["freq_mhz"], off["freq_mhz"]) == ("fixed", 400.0, 200.0)
    assert off["work_mcycles_s"] > on["work_mcycles_s"]  # the decode runs on ABOX


def test_recorded_as_opt_in():
    assert any("domain load" in o["change"] for o in OPT_IN)
