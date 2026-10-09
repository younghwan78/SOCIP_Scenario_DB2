"""Project review policy: throughput default, power reference judgement, thermal-watch reduction menu."""

from __future__ import annotations

import pytest

from scenario_db.api.services.review import judge_power, plan_for, reduction_menu
from scenario_db.api.services.review_policy import apply_throughput, policy_view
from scenario_db.models.definition.project import Project, ReviewPolicy
from scenario_db.sim.timing_budget import TimingBudgetOptions


def test_policy_fills_throughput_only_when_the_request_did_not_set_it():
    pol = ReviewPolicy(throughput_model="pipelined")
    assert apply_throughput(TimingBudgetOptions(), pol).throughput_model == "pipelined"
    assert apply_throughput(TimingBudgetOptions(throughput_model="stage"), pol).throughput_model == "stage"
    assert apply_throughput(TimingBudgetOptions(), None).throughput_model == "stage"
    assert apply_throughput(TimingBudgetOptions(), ReviewPolicy()).throughput_model == "stage"
    assert policy_view(None) == {"declared": False, "throughput_model": "stage", "max_latency_frames": None,
                                 "power_reference": None, "thermal_watch": []}


def test_project_yaml_accepts_review_policy_and_stays_optional():
    base = {"id": "proj-x", "schema_version": "2.2", "kind": "project", "metadata": {"name": "x", "soc_ref": "soc-x"}}
    assert Project.model_validate(base).globals is None
    p = Project.model_validate(base | {"globals": {"review_policy": {
        "throughput_model": "pipelined", "register_baseline": "iq_keep",
        "power_reference": {"values_mw": {"v1": 1000}, "tolerance_pct": 3},
        "thermal_watch": [{"scenario_ref": "uc-x", "variant_ref": "v1"}]}}})
    rp = p.globals.review_policy
    assert rp.thermal_watch[0].reduction_pct == [10.0, 20.0] and rp.power_reference.values_mw == {"v1": 1000.0}
    with pytest.raises(ValueError):
        Project.model_validate(base | {"globals": {"review_policy": {"throughput_model": "frame"}}})


def test_power_judgement_against_previous_project():
    ref = {"mw": 1000.0, "source": "explicit"}
    assert judge_power(990, ref, 3)["status"] == "ok"
    assert judge_power(1020, ref, 3)["status"] == "similar"
    j = judge_power(1050, ref, 3)
    assert j["status"] == "over" and j["delta_mw"] == 50 and j["delta_pct"] == 5.0
    assert judge_power(1000, None, 3) is None and judge_power(None, ref, 3) is None


def _variant():
    return {
        "tiers": {"keep": {"best": {"total_mw": 1000.0}}, "trade": {"best": {"compression": ["PYRAMID_L0"]}},
                  "trade_gain": {"delta_mw": -80.0}},
        "power_options": {"marginal": [
            {"key": "knob:pyramid_l0=skip", "label": "L0 skip", "dimension": "knob:pyramid_l0", "mean_mw": -60.0,
             "min_mw": -65.0, "max_mw": -55.0, "always_beneficial": True},
            {"key": "mode:mtnr=LowPower", "label": "MTNR LP", "dimension": "mode:mtnr", "mean_mw": -5.0,
             "min_mw": -6.0, "max_mw": -4.0, "always_beneficial": True}]},
    }


def test_reduction_menu_orders_free_levers_first_and_skips_fps_drops():
    dvfs = [{"domain": "CAM", "shift": -1, "level": 5, "mhz": 333, "verdict": "ok", "delta_mw": -30.0},
            {"domain": "CAM", "shift": -2, "level": 6, "mhz": 266, "verdict": "fail", "delta_mw": -70.0, "reasons": ["preview interval"]},
            {"domain": "INT", "shift": 1, "level": 3, "mhz": 400, "verdict": "ok", "delta_mw": 10.0}]
    menu = reduction_menu(_variant(), 1000.0, dvfs)
    assert [m["key"] for m in menu] == ["dvfs:CAM:L5", "lossy", "knob:pyramid_l0=skip", "mode:mtnr=LowPower", "dvfs:CAM:L6"]
    assert menu[-1]["feasible"] is False and "fps drop" in menu[-1]["cost"]
    p10 = plan_for(menu, 1000.0, 10)
    assert p10["picked"] == ["dvfs:CAM:L5", "lossy"] and p10["achieved"] and p10["iq_cost"]
    p5 = plan_for(menu, 1000.0, 3)
    assert p5["picked"] == ["dvfs:CAM:L5"] and p5["achieved"] and not p5["iq_cost"]
    p20 = plan_for(menu, 1000.0, 20)
    assert not p20["achieved"] and p20["saving_mw"] == -175.0 and "dvfs:CAM:L6" not in p20["picked"]
