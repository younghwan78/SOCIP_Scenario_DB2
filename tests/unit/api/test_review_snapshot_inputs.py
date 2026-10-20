"""Complete review snapshots freeze scope, provenance and human IQ decisions."""

from copy import deepcopy

import pytest

from scenario_db.reporting.arch_report import build_snapshot
from scenario_db.reporting.review_snapshot import ProjectEvidence, ReviewEvidence


def run(*keys):
    return {
        "id": "run", "title": "review", "scenario_type": "camera", "spec": {}, "summary": {},
        "variants": [
            {"scenario_id": sid, "variant_id": vid, "fps": 30, "eis_on": False, "spec_ok": True,
             "spec_reasons": [], "distribution": {}, "recommended": {"total_mw": 500},
             "design_conditions": {"sw_timing_source": "assumed"}}
            for sid, vid in keys
        ],
    }


def project(**kwargs):
    return ProjectEvidence(
        project_ref="project",
        model={"coverage": {"origin": {"physical_capture": 1}}, "offsetting": 0,
               "flat_cpu": None, "confidence": {"grade": "A"}, "bias": {}},
        **kwargs,
    )


def evidence(**kwargs):
    return ReviewEvidence(
        scope={"kind": "project", "project_ref": "project"},
        context={"policy": {"sw_growth_budget": 1.2}, "rows": [], "battery": {"vbat": 4}},
        references={"references": {"base": {"mw": 500}}, "tolerance_pct": None},
        **kwargs,
    )


def test_complete_snapshot_counts_product_variants_and_keeps_physical_capture_precedence():
    facts = evidence(project=project(
        scenarios=[("a", {"name": "Camera"}), ("b", {})],
        variants=[("a", "base", None), ("a", "derived", "base"), ("b", "unexplored", None)],
        measurements=[("a", "base", "physical_capture"), ("a", "base", "synthetic"), ("b", "unexplored", "unknown")],
    ))
    snap = build_snapshot(run(("a", "base")), {("a", "base"): {"id": "pred", "metrics": {}}}, {}, review=facts)
    cov = snap["coverage"]
    assert cov["total"] == {"variants": 2, "derived": 1, "explored": 1, "registered": 1, "measured": 2,
                            "measured_physical": 1, "measured_no_prediction": 1, "reference": 1}
    assert cov["rows"][1]["explored"] == 0 and cov["rows"][0]["name"] == "Camera"


def test_complete_snapshot_freezes_reference_identity_and_distinguishes_verdict_from_prediction():
    facts = evidence(project=project(
        metadata={"soc_ref": "soc-exynos2600", "board_name": "EVT"}, globals={"default_sw_profile_ref": "sw"},
    ))
    facts.references = {
        "references": {"v": {"mw": 600, "source": "measurement", "id": "previous-capture", "project_ref": "previous",
                             "conditions": {"fps": 30}}},
        "tolerance_pct": 3, "source_priority": ["measurement", "prediction"],
    }
    facts.calibration = [{"scenario_id": "s", "variant_id": "v", "measured_mw": 650, "origin": "physical_capture",
                          "synthetic": False, "fit": {"offsetting": False, "worst_delta_pct": 20}}]
    facts.thermal = {"items": [
        {"scenario_id": "s", "variant_id": "v", "current_mw": 500, "prediction_id": "pred",
         "plans": [{"ask_pct": 10, "need_mw": -50, "saving_mw": -60, "achieved": True,
                    "picked": ["pending"], "iq_pending": True}],
         "approved_plans": [{"ask_pct": 10, "need_mw": -50, "saving_mw": -20, "achieved": False, "picked": []}]},
    ]}
    facts.clock_residency = [{"measurement_id": "clock", "domains": []}]
    source = run(("s", "v"))
    before = deepcopy(source)
    snapshot = build_snapshot(source, {("s", "v"): {"id": "pred", "metrics": {"power": {"total_mw": 500}}}}, {}, review=facts)
    assert source == before
    assert snapshot["references"]["v"]["id"] == "previous-capture"
    assert snapshot["criteria"]["power"]["over"] == 1 and snapshot["criteria"]["power"]["flip"] == ["v"]
    assert snapshot["thermal"]["items"][0]["approved_plans"][0]["achieved"] is False
    assert snapshot["project_conditions"]["soc_name"] == "Exynos2600"
    assert snapshot["project_conditions"]["sw_growth_budget"] == 1.2
    assert snapshot["clock_residency"][0]["measurement_id"] == "clock"
    # A saved result owns nested evidence too, not just the outer references map.
    facts.references["references"]["v"]["conditions"]["fps"] = 120
    facts.thermal["items"][0]["plans"][0]["picked"].append("later")
    facts.calibration[0]["measured_mw"] = 1
    source["variants"][0]["recommended"]["total_mw"] = 1
    assert snapshot["references"]["v"]["conditions"]["fps"] == 30
    assert snapshot["thermal"]["items"][0]["plans"][0]["picked"] == ["pending"]
    assert snapshot["calibration"][0]["measured_mw"] == 650
    assert snapshot["scenarios"][0]["power"]["total_mw"] == 500


def test_complete_snapshot_keeps_same_named_option_decisions_in_their_scenario():
    source = run(("a", "shared"), ("b", "shared"))
    for variant in source["variants"]:
        variant["power_options"] = {
            "status": "ok", "dimensions": [{"items": [{"key": "one", "kind": "iq"}]}],
            "results": [{"key": "one", "items": ["one"], "labels": ["One"], "spec_ok": True,
                         "delta_mw": -10, "delta_pct": -2, "attribution": {"by_category": {}}}],
        }
    facts = evidence(option_states={("a", "shared", "one"): "adopted", ("b", "shared", "one"): "rejected"})
    snap = build_snapshot(source, {}, {}, review=facts)
    assert [r["best"]["review_status"] for r in snap["power_options"]] == ["adopted", "rejected"]
    assert [r["singles"][0]["review_status"] for r in snap["power_options"]] == ["adopted", "rejected"]
    assert "risk_register" not in snap  # the persistence caller chooses run snapshot vs project register


def test_review_evidence_owns_calibration_and_keeps_unscoped_thermal_reason():
    facts = evidence()
    facts.scope = {"kind": "run", "project_ref": None}
    snapshot = build_snapshot(run(), {}, {}, review=facts)
    assert snapshot["scope"]["kind"] == "run"
    assert snapshot["thermal"] == {"items": [], "reason": "과제 범위 없음"}
    assert "project_conditions" not in snapshot and "coverage" not in snapshot
    assert "clock_residency" not in snapshot and "cpu" not in snapshot
    assert "conclusion" in snapshot and "risks" in snapshot
    with pytest.raises(ValueError, match="already owns"):
        build_snapshot(run(), {}, {}, [], review=facts)


def test_final_conclusion_and_risks_include_the_collected_cpu_decision():
    cpu = {
        "id": "cpu-snapshot", "scenario_id": "s", "variant_id": "v", "profile_ref": "measurement",
        "power_params_ref": None, "base_power_params_ref": None, "note": "reviewed", "created_by": "reviewer",
        "created_at": "2026-10-20T00:00:00Z",
        "summary": {"tolerance": 1.1, "binding": "timing", "points": [],
                    "best_at_start": {"delta_mw": -25, "moved": ["task"]}},
    }
    facts = evidence(project=project(cpu=[cpu]))
    snapshot = build_snapshot(run(("s", "v")), {}, {}, review=facts)
    action = next(a for a in snapshot["conclusion"]["actions"] if a["basis"] == "CPU what-if 최적 배치")
    assert action["delta_mw"] == -25 and action["targets"] == ["v"] and action["tier"] == 3
    assert any(r["key"] == "cpu_growth_tolerance" for r in snapshot["risks"])
    cpu["summary"]["best_at_start"]["delta_mw"] = -100
    assert snapshot["cpu"][0]["summary"]["best_at_start"]["delta_mw"] == -25
