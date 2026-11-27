"""R-7 job measured slots: jobs.measured.yaml -> node_configs.<node>.sim.jobs.<job>.<stage> at compile."""

from copy import deepcopy
from pathlib import Path

import pytest

from scenario_db.authoring.errors import AuthoringError
from scenario_db.authoring.scenario import apply_job_measurements
from scenario_db.authoring.tree import compile_project

JOBS = [{"id": "shot", "when": {"mode": ["a", "b"]}, "stages": [
    {"id": "readout", "kind": "sensor", "nodes": ["sensor"]},
    {"id": "merge", "nodes": ["mtnr", "msnr"], "when": {"mf": True}},
    {"id": "post", "nodes": ["yuvp"]},
]}]


def _variants():
    return [{"id": "v1", "design_conditions": {"mode": "a", "mf": True}},
            {"id": "v2", "design_conditions": {"mode": "b"}},
            {"id": "v3", "design_conditions": {"mode": "c"}}]


def _entry(stage, field, value, **kw):
    return {"target": {"job": "shot", "stage": stage, "field": field}, "value": value, **kw}


def test_a_filled_slot_lands_under_the_first_stage_node_of_active_variants():
    variants = _variants()
    stats = apply_job_measurements(variants, {"entries": [
        _entry("merge", "service_ms", 60.0, evidence_ref="EV-1"),
        _entry("post", "clock_mhz", 600, when={"mode": "b"}),
        _entry("post", "service_ms", None),
    ]}, JOBS)
    assert variants[0]["node_configs"] == {"mtnr": {"sim": {"jobs": {"shot": {"merge": {
        "service_ms": 60.0, "value_source": "measured", "evidence_ref": "EV-1"}}}}}}
    assert variants[1]["node_configs"]["yuvp"]["sim"]["jobs"]["shot"]["post"]["clock_mhz"] == 600
    assert "node_configs" not in variants[2]                      # job not active (mode c)
    # merge: v1 applied, v2 skipped (stage when), v3 skipped (job when); post clock: v2 only
    assert stats == {"applied": 2, "pending": 1, "skipped": 2, "slots": 3}


def test_later_entries_win_and_variants_limit_the_scope():
    variants = _variants()
    apply_job_measurements(variants, {"entries": [_entry("post", "service_ms", 10), _entry("post", "service_ms", 12,
                                                                                         variants=["v1"])]}, JOBS)
    assert variants[0]["node_configs"]["yuvp"]["sim"]["jobs"]["shot"]["post"]["service_ms"] == 12
    assert variants[1]["node_configs"]["yuvp"]["sim"]["jobs"]["shot"]["post"]["service_ms"] == 10


@pytest.mark.parametrize("entry, match", [
    ({"target": {"job": "nope", "stage": "post", "field": "mb"}, "value": 1}, "job 'nope'"),
    (_entry("nope", "mb", 1), "no stage 'nope'"),
    (_entry("post", "power_mw", 1), "field must be one of"),
    (_entry("readout", "clock_mhz", 1), "takes only service_ms"),
    (_entry("post", "service_ms", 1, unit="us"), "in ms, not us"),
    (_entry("post", "service_ms", 1, statistic="p42"), "statistic"),
    (_entry("post", "service_ms", 0), "positive number"),
])
def test_a_slot_must_name_a_real_field(entry, match):
    with pytest.raises(AuthoringError, match=match):
        apply_job_measurements(_variants(), {"entries": [entry]}, JOBS)
    with pytest.raises(AuthoringError, match="kind"):
        apply_job_measurements(_variants(), {"kind": "authoring.sw_timing_measured", "entries": []}, JOBS)


def test_the_e2600_capture_slots_are_all_pending():
    report = compile_project(Path("authoring"), "sm-s947b")
    cov = report["job_measurements"]["uc-cam-capture-e2600"]
    assert cov["slots"] == cov["pending"] == 7 and cov["applied"] == 0


def test_a_filled_slot_reaches_the_job_evaluator(tmp_path):
    from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
    from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

    graph = _exynos2600_generated_graph("uc-cam-capture-e2600", "cam-cap-r1-mf")
    base = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"))
    doc = {"id": "cam-cap-r1-mf", "design_conditions": dict(graph.variant.design_conditions),
           "node_configs": deepcopy(graph.variant.node_configs or {})}
    jobs = graph.scenario.pipeline["jobs"]
    apply_job_measurements([doc], {"entries": [{"target": {"job": "still_shot", "stage": "merge",
                                                           "field": "service_ms"}, "value": 400.0}]}, jobs)
    graph.variant.node_configs = doc["node_configs"]
    measured = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"))
    job = next(j for j in measured["jobs"] if j["id"] == "still_shot")
    merge = next(s for s in job["stages"] if s["id"] == "merge")
    assert merge["value_source"] == "measured"
    before = next(j for j in base["jobs"] if j["id"] == "still_shot")["milestones"]["thumbnail"]
    assert job["milestones"]["thumbnail"] > before
