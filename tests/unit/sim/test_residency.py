"""R-4 / M-5: wake-residency-v1 from the ABOX subsystem wake sources and the config residency coefficients."""

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.models.capability.sim_config import SimConfigRunDefaults
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.residency import ResidencyParams, evaluate_residency
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

MP3 = "uc-aud-mp3-playback-e2600"
OPTS = TimingBudgetOptions(throughput_model="pipelined")
COEF = {"e_wake_mj": 0.2, "t_exit_ms": 0.1, "period_burst_ms": 0.2, "refill_mb_s": 200,
        "mif_active_mw": 40, "mif_self_refresh_mw": 2}
CFG = SimulationRunConfig(residency=COEF)


def _run(variant, config=None, uc=MP3):
    return analyze_timing_budget(_exynos2600_generated_graph(uc, variant), OPTS, config=config)


def test_deep_buffer_wakes_cost_the_cpu_and_little_mif():
    r = _run("audio-flac-hires-screen-off", CFG)
    z = r["residency"]
    assert z["status"] == "ok" and z["wakeups_per_s"] == pytest.approx(50.0)
    assert z["cpu_wake_mw"] == pytest.approx(50 * 0.2)
    ratio = 50 * (0.2 + 0.1) / 1000
    assert z["mif_active_ratio"] == pytest.approx(ratio)
    assert z["mif_state_mw"] == pytest.approx(ratio * 40 + (1 - ratio) * 2, abs=1e-3)
    plain = _run("audio-flac-hires-screen-off")
    assert r["power"]["total_mw"] == pytest.approx(plain["power"]["total_mw"] + z["mw"], abs=0.02)
    assert r["power"]["residency_mw"] == pytest.approx(z["mw"])


def test_offload_refills_wake_a_hundred_times_less():
    z = _run("audio-mp3-screen-off-offload", CFG)["residency"]
    assert z["wakeups_per_s"] == pytest.approx(0.5) and z["cpu_wake_mw"] == pytest.approx(0.1)
    assert z["sources"][0]["burst_ms"] == pytest.approx(0.08 / 200 * 1000)
    assert z["mif_active_ratio"] == pytest.approx(0.5 * (0.4 + 0.1) / 1000)


def test_the_screen_keeps_mif_active():
    z = _run("audio-mp3-screen-on", CFG)["residency"]
    assert z["screen_on"] and z["mif_active_ratio"] == 1.0 and z["mif_state_mw"] == pytest.approx(40.0)


def test_without_coefficients_only_the_wakes_are_reported():
    r = _run("audio-flac-hires-screen-off")
    assert r["residency"]["status"] == "no_coefficients" and "residency_mw" not in r["power"]
    assert r["residency"]["wakeups_per_s"] == pytest.approx(50.0)


def test_no_wake_source_no_residency():
    assert evaluate_residency({"abox": {"wake": {"per_s": 0, "sources": []}}}, ResidencyParams(**COEF), False) is None
    r = analyze_timing_budget(_exynos2600_generated_graph("uc-cam-capture-e2600", "cam-cap-r1-sf"), OPTS, config=CFG)
    assert "residency" not in r


def test_independent_sources_overlap():
    subs = {"a": {"wake": {"sources": [{"kind": "event", "per_s": 1000.0}, {"kind": "event", "per_s": 1000.0}]}}}
    z = evaluate_residency(subs, ResidencyParams(**{**COEF, "period_burst_ms": 0.4, "t_exit_ms": 0.1}), False)
    assert z["mif_active_ratio"] == pytest.approx(1 - (1 - 0.5) ** 2)


@pytest.mark.parametrize("bad", [{**COEF, "refill_mb_s": 0}, {**COEF, "e_wake_mj": float("inf")},
                                 {k: v for k, v in COEF.items() if k != "mif_active_mw"}])
def test_coefficients_are_checked_in_the_profile(bad):
    with pytest.raises(ValidationError):
        SimConfigRunDefaults(residency=bad)


def test_the_e2600_profile_declares_assumed_coefficients():
    with open("db_Exynos2600_SM-S947B/00_hw/simcfg-proj-sm-s947b-v2.yaml", encoding="utf-8") as fh:
        rc = yaml.safe_load(fh)["run_config"]
    assert ResidencyParams.model_validate(rc["residency"]).value_source == "assumed"
    assert SimulationRunConfig(**{k: v for k, v in rc.items() if k != "power_params_ref"}).residency is not None


def test_coefficients_change_the_request_hash_only_when_set():
    from scenario_db.sim.service import _request_hash
    from tests.unit.sim.test_service_hash import _inputs, _request

    inputs = _inputs()
    base = _request_hash(inputs, _request())
    assert _request_hash(inputs, _request(config=SimulationRunConfig(asv_group=4))) == base
    assert _request_hash(inputs, _request(config=SimulationRunConfig(asv_group=4, residency=COEF))) != base


def test_the_residency_bucket_is_in_the_total_and_the_shares():
    p = _run("audio-mp3-screen-on", CFG)["power"]
    assert p["total_mw"] == pytest.approx(p["cpu_mw"] + p["hw_mw"] + p["bw_mw"] + p["residency_mw"], abs=0.02)
    assert p["share_pct"]["residency"] == pytest.approx(100 * p["residency_mw"] / p["total_mw"], abs=0.1)
    assert sum(p["share_pct"].values()) == pytest.approx(100, abs=0.3)


def test_the_profile_cpu_model_re_total_keeps_the_residency(monkeypatch):
    from scenario_db.sim import timing_budget as tb

    def retotal(report, *_a):      # what apply_profile_cpu does: CPU + HW + BW again
        p = report["power"]
        p["cpu_mw"] = 30.0
        p["total_mw"] = round(p["cpu_mw"] + p["hw_mw"] + p["bw_mw"], 2)

    monkeypatch.setattr(tb, "_profile_cpu", retotal)
    r = analyze_timing_budget(_exynos2600_generated_graph(MP3, "audio-mp3-screen-on"),
                              TimingBudgetOptions(throughput_model="pipelined", cpu_model="profile"), config=CFG)
    p = r["power"]
    assert p["total_mw"] == pytest.approx(30.0 + p["hw_mw"] + p["bw_mw"] + r["residency"]["mw"], abs=0.02)


def test_exploration_cases_carry_the_residency_term():
    from scenario_db.sim.arch_exploration import _case, _slice

    r = _run("audio-mp3-screen-on", CFG)
    s = _slice(r, "p50", 1.0)
    zero = {"delta_mw": 0.0, "delta_mbs": 0.0, "delta_ip_mw": 0.0, "delta_ip_mbs": 0.0, "delta_cpu_mw": 0.0,
            "delta_cpu_mbs": 0.0, "buffers": [], "modes": {}, "lossy": False, "assumed": False}
    case = _case(s, zero, {"delta_mw": 0.0, "levels": {}, "raises": 0})
    assert case["total_mw"] == pytest.approx(r["power"]["total_mw"], abs=0.02)


def test_concurrent_members_add_wakes_and_share_one_mif_state():
    from scenario_db.sim.concurrency import compose

    a = _run("audio-flac-hires-screen-off", CFG)
    b = _run("audio-mp3-screen-off-offload", CFG)
    c = compose([("a", a), ("b", b)])
    ra, rb = a["residency"], b["residency"]
    ratio = 1 - (1 - ra["mif_active_ratio"]) * (1 - rb["mif_active_ratio"])
    mif = ratio * 40 + (1 - ratio) * 2
    z = c["residency"]
    assert z["cpu_wake_mw"] == pytest.approx(ra["cpu_wake_mw"] + rb["cpu_wake_mw"], abs=1e-3)
    assert z["mif_state_mw"] == pytest.approx(mif, abs=1e-3)
    parts = sum(c["power"][k] for k in ("cpu_mw", "hw_mw", "bw_mw", "dvfs_raise_mw"))
    assert c["power"]["total_mw"] == pytest.approx(parts + z["mw"], abs=0.03)
    assert c["power"]["total_mw"] < c["power"]["sum_of_members_mw"]      # the self-refresh floor is paid once
    assert any("residency" in x for x in c["limits"])


def test_an_explicit_null_turns_the_profile_residency_off():
    from tests.unit.sim import test_config_profile as tc

    db, row = tc._stored_profile()
    row.run_config = {**row.run_config, "residency": COEF}
    on = tc._request()
    tc._apply_config_profile(db, on)
    off = tc._request(residency=None)
    tc._apply_config_profile(db, off)
    assert on.config.residency is not None and off.config.residency is None


def test_an_explicit_null_survives_a_dump_and_rebuild():
    off = SimulationRunConfig(residency=None)
    dumped = off.model_dump(mode="json")
    assert "residency" in dumped and dumped["residency"] is None
    assert "residency" in SimulationRunConfig(**dumped).model_fields_set
    assert "residency" not in SimulationRunConfig().model_dump(mode="json")
    assert "residency" not in SimulationRunConfig().model_dump(mode="json", exclude_unset=True)


def test_a_rebuilt_concurrent_member_keeps_the_model_off():
    from scenario_db.api.schemas.timing_budget import TimingBudgetConcurrentRequest, TimingBudgetRequest

    req = TimingBudgetConcurrentRequest(members=[{"scenario_id": "s1", "variant_id": "a"},
                                                 {"scenario_id": "s2", "variant_id": "b"}],
                                        config={"residency": None})
    base = req.model_dump(exclude={"members", "options"})
    one = TimingBudgetRequest(**base, scenario_id="s1", variant_id="a")
    assert one.config.residency is None and "residency" in one.config.model_fields_set


def test_the_attribution_names_the_residency_term():
    from scenario_db.sim.power_attribution import attribute

    def payload(res):
        return {"power": {"total_mw": 10.0 + res, "cpu_mw": 4.0, "hw_mw": 3.0, "bw_mw": 3.0,
                          **({"residency_mw": res} if res else {})}, "ips": [], "cpu_by_task": {"t": 4.0}}

    out = attribute(payload(0.0), payload(50.0))
    assert out["components"]["residency_mw"] == pytest.approx(50.0)
    assert abs(out["residual_mw"]) < 1e-6 and out["by_category"]["Wake residency"] == pytest.approx(50.0)


def test_exploration_payload_carries_the_residency_term():
    from scenario_db.sim.arch_exploration import _case, _slice

    s = _slice(_run("audio-mp3-screen-on", CFG), "p50", 1.0)
    zero = {"delta_mw": 0.0, "delta_mbs": 0.0, "delta_ip_mw": 0.0, "delta_ip_mbs": 0.0, "delta_cpu_mw": 0.0,
            "delta_cpu_mbs": 0.0, "buffers": [], "modes": {}, "lossy": False, "assumed": False}
    assert _case(s, zero, {"delta_mw": 0.0, "levels": {}, "raises": 0})["residency_mw"] == pytest.approx(50.0)


@pytest.mark.parametrize("raw,on", [("false", False), ("0", False), ("off", False), ("true", True), (None, True)])
def test_a_string_screen_flag_is_read_as_the_viewer_reads_it(raw, on):
    graph = _exynos2600_generated_graph(MP3, "audio-mp3-screen-off-offload")
    dc = dict(graph.variant.design_conditions or {})
    dc.pop("screen_on", None)
    if raw is not None:
        dc["screen_on"] = raw
    graph.variant.design_conditions = dc
    z = analyze_timing_budget(graph, OPTS, config=CFG)["residency"]
    assert z["screen_on"] is on and (z["mif_active_ratio"] == 1.0) is on
