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
    assert z["sources"][0]["burst_ms"] == pytest.approx(0.4 / 200 * 1000)
    assert z["mif_active_ratio"] == pytest.approx(0.5 * (2.0 + 0.1) / 1000)


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
