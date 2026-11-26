"""M-7: GPU workload DRAM traffic (sim.workload.mb_per_frame) and the MIF min-lock floor (gpu-mif-floor-v1)."""

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.bw_power import BwPowerContext, MifLinearBwModel
from scenario_db.sim.gpu_memory import mif_floor_khz
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from scenario_db.sim.workload_spec import WorkloadSpec
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

GAME = "uc-game-play-e2600"
OPTS = TimingBudgetOptions(throughput_model="pipelined")
TABLE = {"base": 676000, "356000": 1352000, "605000": 2730000, "836000": 4205000}


def _v2() -> SimulationRunConfig:
    with open("db_Exynos2600_SM-S947B/00_hw/pmp-exynos2600-v2.yaml", encoding="utf-8") as fh:
        params = PowerModelParams.model_validate(yaml.safe_load(fh))
    with open("db_Exynos2600_SM-S947B/00_hw/simcfg-proj-sm-s947b-v2.yaml", encoding="utf-8") as fh:
        rc = yaml.safe_load(fh)["run_config"]
    return SimulationRunConfig(**{**{k: v for k, v in rc.items() if k != "power_params_ref"}, "power_params": params})


@pytest.mark.parametrize(("gpu_khz", "floor"), [(298000, (676000, "base")), (356000, (1352000, "356000")),
                                                (604999, (1352000, "356000")), (605000, (2730000, "605000")),
                                                (980000, (4205000, "836000"))])
def test_the_floor_is_the_largest_key_at_or_below_the_gpu_clock(gpu_khz, floor):
    assert mif_floor_khz(TABLE, gpu_khz) == floor


def test_no_table_gives_no_floor():
    assert mif_floor_khz(None, 605000) is None and mif_floor_khz({"x": "y"}, 605000) is None


@pytest.mark.parametrize("raw", [{"mb_per_frame": {"read": -1, "write": 0}}, {"mb_per_frame": {"read": 1}},
                                 {"mb_per_frame": {"read": 1, "write": 1, "llc_weight": 0.5}}, {"mif_floor": "kernel"}])
def test_the_traffic_is_checked(raw):
    with pytest.raises(ValidationError):
        WorkloadSpec.model_validate(raw)


MIF = MifLinearBwModel(e_read=50, e_write=80, opps=((421, 25, 3000), (845, 40, 6000), (1539, 90, 12000), (2730, 150, 21000)))


def _state(**extra):
    return MIF.mif_state(BwPowerContext(total_bw_mbs=1000, extra={"dram_mbs": 1000, **extra}))


def test_no_floor_keeps_the_mif_state():
    assert _state() == _state(dvfs_sn=None)
    assert "min_lock_mhz" not in _state() and _state()["mif_mhz"] == 421


def test_a_floor_lifts_the_level_to_the_next_opp():
    s = _state(min_lock_mhz=1352)
    assert (s["mif_mhz"], s["reason"], s["base_mw"]) == (1539, "min_lock", 90)


def test_a_floor_below_the_governor_level_does_nothing():
    s = MIF.mif_state(BwPowerContext(extra={"dram_mbs": 6000, "min_lock_mhz": 676}))
    assert (s["mif_mhz"], s["reason"]) == (1539, "governor")


def test_a_floor_above_the_top_level_saturates():
    s = _state(min_lock_mhz=4205)
    assert (s["mif_mhz"], s["reason"], s["min_lock_above_top"]) == (2730, "saturated", True)


def test_the_workload_traffic_is_two_ports_at_the_run_rate():
    inputs = build_simulation_inputs(_exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr"), None)
    ports = {p.port: p for p in inputs.port_transfers if p.node_id == "gpu"}
    assert (ports["GPU_WORKLOAD_RD"].mb_per_frame, ports["GPU_WORKLOAD_WR"].mb_per_frame) == (36, 12)
    r = analyze_timing_budget(_exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr"), OPTS)
    assert r["bw"]["mif"]["gpu_workload_mbs"] == {"GPU_WORKLOAD_RD": pytest.approx(4320), "GPU_WORKLOAD_WR": pytest.approx(1440)}


def test_legacy_coeff_reports_the_floor_only():
    m = analyze_timing_budget(_exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr"), OPTS)["bw"]["mif"]
    assert (m["gpu_mhz"], m["floor_mhz"], m["applied"]) == (605.0, 2730.0, False) and "level_mhz" not in m


def _light_traffic(variant):
    graph = _exynos2600_generated_graph(GAME, variant)
    graph.variant.node_configs["gpu"]["sim"]["workload"]["mb_per_frame"] = {"read": 1, "write": 1}
    return graph


def test_mif_linear_applies_the_floor_and_adds_only_its_power():
    lifted = analyze_timing_budget(_light_traffic("game-fhd-120fps-sdr"), OPTS, config=_v2())
    m = lifted["bw"]["mif"]
    assert (m["level_mhz"], m["level_reason"], m["level_without_floor_mhz"]) == (2730, "min_lock", 845)
    assert m["floor_extra_mw"] == pytest.approx(150 - 40)
    off = _light_traffic("game-fhd-120fps-sdr")
    off.variant.node_configs["gpu"]["sim"]["workload"]["mif_floor"] = "none"
    plain = analyze_timing_budget(off, OPTS, config=_v2())
    assert plain["bw"]["mif"]["status"] == "off" and "mif_floor_mw" not in plain["power"]
    assert lifted["power"]["bw_mw"] == pytest.approx(plain["power"]["bw_mw"] + 110, abs=0.02)
    assert lifted["power"]["mif_floor_mw"] == pytest.approx(110)
    shares = lifted["power"]["share_pct"]
    assert shares["bw"] == pytest.approx(100 * lifted["power"]["bw_mw"] / lifted["power"]["total_mw"], abs=0.1)


def test_a_floor_above_the_modelled_levels_is_a_note():
    r = analyze_timing_budget(_exynos2600_generated_graph(GAME, "game-uhd-60fps-sdr"), OPTS, config=_v2())
    assert r["bw"]["mif"]["floor_mhz"] == 4205 and any("above the highest modelled MIF level" in n for n in r["verdict"]["notes"])


def test_scenarios_without_a_gpu_workload_have_no_mif_report():
    for uc, v in (("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr"), ("uc-game-streaming-e2600", "game-stream-fhd60-hevc")):
        assert "mif" not in analyze_timing_budget(_exynos2600_generated_graph(uc, v), OPTS)["bw"]


def test_the_condition_hash_follows_the_floor_inputs(monkeypatch):
    from types import SimpleNamespace

    from scenario_db.api.services import timing_budget as svc

    monkeypatch.setattr(svc, "build_simulation_inputs", lambda graph, config: None)
    monkeypatch.setattr(svc, "_request_hash", lambda *a, **k: "same-simulation-inputs")
    shim = SimpleNamespace(config=None)
    base = _exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr")
    off = _exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr")
    off.variant.node_configs["gpu"]["sim"]["workload"]["mif_floor"] = "none"
    assert svc._condition_hash(base, OPTS, shim, {}) != svc._condition_hash(off, OPTS, shim, {})


def test_the_gpu_peak_uses_its_domain_busy_time():
    r = analyze_timing_budget(_exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr"), OPTS)
    util = r["power"]["domain_loads"]["gpu"]["util"]
    assert r["bw"]["peak"]["by_ip"]["gpu"] == pytest.approx(r["bw"]["hw_by_ip"]["gpu"] / util, rel=1e-3)


def test_more_traffic_never_lowers_the_mif_linear_bw_power():
    powers = []
    for read in (13, 14):
        graph = _exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr")
        graph.variant.node_configs["gpu"]["sim"]["workload"]["mb_per_frame"] = {"read": read, "write": 1}
        r = analyze_timing_budget(graph, OPTS, config=_v2())
        powers.append(r["power"]["bw_mw"])
        assert r["power"]["mif_base_mw"] == pytest.approx(r["bw"]["mif"]["base_mw"])
    assert powers[1] > powers[0]


def test_gpu_traffic_is_not_held_frame_memory():
    graph = _exynos2600_generated_graph(GAME, "game-fhd-60fps-sdr")
    with_traffic = analyze_timing_budget(graph, OPTS)["bw"]["write_mb_frame"]
    graph.variant.node_configs["gpu"]["sim"]["workload"].pop("mb_per_frame")
    assert analyze_timing_budget(graph, OPTS)["bw"]["write_mb_frame"] == pytest.approx(with_traffic)


def test_no_mif_levels_means_the_floor_is_not_applied():
    cfg = _v2()
    cfg = cfg.model_copy(update={"power_params": cfg.power_params.model_copy(
        update={"bw": cfg.power_params.bw.model_copy(update={"mif_opps": []})})})
    m = analyze_timing_budget(_exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr"), OPTS, config=cfg)["bw"]["mif"]
    assert m["applied"] is False and m["level_mhz"] is None and "mif_opps" in m["not_applied"]
