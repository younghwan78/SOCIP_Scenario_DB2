"""R-6 KPI targets and the M-10 KPI registry (sim/kpis.py)."""

from copy import deepcopy
from types import SimpleNamespace
from typing import get_args

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.models.definition.job import JobSpec
from scenario_db.models.definition.usecase import (
    MODELED_KPIS, TARGET_PEAK_WINDOW_MS, JudgementContract, JudgementKpi, KpiTarget, Pipeline,
    target_reference_errors,
)
from scenario_db.sim.jobs import PEAK_WINDOW_MS
from scenario_db.sim.judgement import rate_issues, select_targets
from scenario_db.sim.kpis import KPI_MODELS, evaluate_kpis, summary
from scenario_db.sim.models import DVFSTable
from scenario_db.sim.timing_budget import TimingBudgetOptions, _judge_kpis, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

ROOT = "db_Exynos2600_SM-S947B"


# ---------------------------------------------------------------- vocabulary

def test_registry_ids_are_vocabulary_and_modeled_kpis():
    vocab = set(get_args(JudgementKpi))
    assert set(KPI_MODELS) <= vocab
    assert set(MODELED_KPIS) == {"interval", "latency", *KPI_MODELS}
    assert TARGET_PEAK_WINDOW_MS == PEAK_WINDOW_MS


@pytest.mark.parametrize("bad, match", [
    ({"kpi": "interval", "max": 1}, "takes no target"),
    ({"kpi": "underrun", "max": 1}, "bounded by min"),
    ({"kpi": "peak_bw", "min": 1}, "bounded by max"),
    ({"kpi": "frame_pacing", "metric": "fps", "max": 1}, "not one of"),
    ({"kpi": "peak_bw", "metric": "p99", "max": 1}, "takes no metric"),
    ({"kpi": "peak_bw", "max": 1, "min": 0}, "exactly one"),
    ({"kpi": "peak_bw"}, "exactly one"),
    ({"kpi": "event_latency", "max": 1}, "needs a milestone"),
    ({"kpi": "peak_bw", "milestone": "x", "max": 1}, "event_latency only"),
    ({"kpi": "underrun", "job": "j", "min": 1}, "event job KPIs only"),
    ({"kpi": "peak_bw", "window_ms": 5, "max": 1}, "must be 10"),
    ({"kpi": "event_energy", "window_ms": 10, "max": 1}, "peak KPIs"),
])
def test_target_shape_errors(bad, match):
    with pytest.raises(ValidationError, match=match):
        KpiTarget(id="t", **bad)


def test_target_key_defaults_the_pacing_metric():
    assert KpiTarget(id="t", kpi="frame_pacing", max=1).key() == ("frame_pacing", "jank_pct", None, None)
    assert KpiTarget(id="t", kpi="frame_pacing", metric="achieved_fps", min=59).key()[1] == "achieved_fps"


def _job(**kw):
    base = {"id": "shot", "stages": [{"id": "s", "phase": "p", "kind": "transfer", "nodes": ["n"], "work": {"mb": 1, "mb_per_s": 1}}],
            "milestones": {"thumbnail": "s"}, "kpis": ["event_latency", "peak_bw"]}
    return JobSpec.model_validate({**base, **kw})


def test_target_references():
    jobs = [_job(), _job(id="other", kpis=["peak_bw"], milestones={})]
    c = JudgementContract.model_validate({"kpis": ["underrun"], "targets": [
        {"id": "a", "kpi": "underrun", "min": 0},
        {"id": "a", "kpi": "frame_pacing", "max": 1},                          # duplicate id, undeclared kpi
        {"id": "b", "kpi": "event_latency", "job": "nope", "milestone": "thumbnail", "max": 1},
        {"id": "c", "kpi": "event_energy", "max": 1},                          # no job declares it
        {"id": "d", "kpi": "event_latency", "job": "shot", "milestone": "saved", "max": 1},
        {"id": "e", "kpi": "peak_bw", "max": 1},                               # every job declares it: ok
        {"id": "f", "kpi": "event_latency", "milestone": "thumbnail", "max": 1},  # only shot declares it: ok
    ]})
    errors = target_reference_errors(c, jobs)
    assert any("duplicate" in e and "'a'" in e for e in errors)
    assert any("frame_pacing is not declared" in e for e in errors)
    assert any("job 'nope' not found" in e for e in errors)
    assert any("declares kpi event_energy" in e for e in errors)
    assert any("milestone 'saved'" in e for e in errors)
    assert not any(".e:" in e or ".f:" in e for e in errors)


def test_a_job_kpi_declared_scenario_wide_covers_every_job():
    jobs = [_job(kpis=None)]
    c = JudgementContract.model_validate({"kpis": ["peak_bw"], "targets": [{"id": "bw", "kpi": "peak_bw", "max": 1}]})
    assert target_reference_errors(c, jobs) == []
    assert target_reference_errors(c.model_copy(update={"kpis": ["interval"]}), jobs)   # nobody declares it


def test_the_pipeline_model_refuses_dangling_targets():
    raw = {"nodes": [{"id": "n", "ip_ref": "ip-x"}], "judgement": {"kpis": ["interval"], "targets": [
        {"id": "a", "kpi": "underrun", "min": 0}]}}
    with pytest.raises(ValidationError, match="underrun is not declared"):
        Pipeline.model_validate(raw)


# ---------------------------------------------------------------- selection

def _variant(**design):
    return SimpleNamespace(design_conditions=design, routing_switch={"disabled_nodes": ["npu"]})


def test_the_most_specific_target_wins_and_ties_are_refused():
    targets = [KpiTarget(id="all", kpi="peak_bw", max=50),
               KpiTarget(id="hi", kpi="peak_bw", max=80, when={"readout": ["full", "binning"]}),
               KpiTarget(id="npu", kpi="peak_footprint", max=1, when_node_enabled="npu")]
    assert [t.id for t in select_targets(targets, _variant(readout="full"))] == ["hi"]
    assert [t.id for t in select_targets(targets, _variant(readout="none"))] == ["all"]   # npu disabled
    tie = [*targets, KpiTarget(id="hi2", kpi="peak_bw", max=90, when={"mode": "mf"})]
    with pytest.raises(ValueError, match="equally specifically"):
        select_targets(tie, _variant(readout="full", mode="mf"))


def test_rate_issues_reports_a_target_tie_per_variant():
    pipeline = {"judgement": {"kpis": ["underrun"], "targets": [
        {"id": "a", "kpi": "underrun", "min": 0, "when": {"x": 1}},
        {"id": "b", "kpi": "underrun", "min": 1, "when": {"y": 1}}]}}
    variants = [{"id": "v1", "design_conditions": {"x": 1, "y": 1}}, {"id": "v2", "design_conditions": {"x": 1}}]
    errors, _ = rate_issues("uc", pipeline, variants)
    assert len(errors) == 1 and errors[0].startswith("uc/v1:") and "equally" in errors[0]
    from scenario_db.write.service import _rate_write_issues

    issues = _rate_write_issues("uc", pipeline, variants, "payload.variant")
    assert [i.code for i in issues] == ["judgement_target_invalid"]


# ---------------------------------------------------------------- registry on synthetic reports

def _graph(pipeline, **design):
    return SimpleNamespace(scenario=SimpleNamespace(pipeline=pipeline), variant=_variant(**design))


def _shot_report(**over):
    job = {"id": "shot", "milestones": {"thumbnail": 120.0, "saved": None},
           "energy_mj": {"event": 30.0}, "peak": {"power_mw": 900.0, "bw_mbs": 21000.0, "footprint_mb": 2100.0},
           "stages": [{"value_source": "assumed"}, {"value_source": "measured"}]}
    return {"intervals": {"preview": {"ok": True}, "video": {"ok": None}}, "jobs": [{**job, **over}],
            "verdict": {"status": "ok", "reasons": [], "notes": []}}


def test_job_rows_targets_and_no_input():
    pipeline = {"jobs": [{"id": "shot", "kpis": ["event_latency", "event_energy", "peak_bw", "peak_footprint",
                                               "event_rate"]}]}
    contract = JudgementContract.model_validate({"kpis": ["interval"], "targets": [
        {"id": "thumb", "kpi": "event_latency", "milestone": "thumbnail", "max": 300},
        {"id": "bw-all", "kpi": "peak_bw", "max": 10000},
        {"id": "bw-shot", "kpi": "peak_bw", "job": "shot", "max": 50000, "value_source": "spec"},
        {"id": "heap", "kpi": "peak_footprint", "max": 2048, "basis": "camera heap"}]})
    rows = evaluate_kpis(_graph(pipeline), _shot_report(), contract, jobs_evaluated=True)
    by = {(r["kpi"], r["milestone"]): r for r in rows}
    assert by[("event_latency", "thumbnail")]["status"] == "pass" and by[("event_latency", "thumbnail")]["id"] == "thumb"
    assert by[("event_latency", "saved")]["status"] == "no_input"         # milestone not reached: never a pass
    assert by[("event_energy", None)]["status"] == "no_target" and by[("event_energy", None)]["value"] == 30.0
    bw = by[("peak_bw", None)]
    assert bw["id"] == "bw-shot" and bw["status"] == "pass" and bw["value_source"] == "spec"   # the job's own wins
    heap = by[("peak_footprint", None)]
    assert heap["status"] == "fail" and heap["unit"] == "MB" and heap["bound"] == "max"
    assert heap["sources"] == ["assumed", "measured"]
    assert by[("event_rate", None)]["status"] == "unmodeled"
    assert summary(rows) == {"status": "fail", "fail": 1, "no_input": 1, "unmodeled": 1, "no_target": 1, "pass": 2}
    # steady-only runs skip the job KPIs; nothing declared beyond interval -> no section
    assert evaluate_kpis(_graph(pipeline), _shot_report(), contract, jobs_evaluated=False) is None


def test_scenario_rows():
    contract = JudgementContract.model_validate({"kpis": ["interval", "latency", "underrun", "frame_pacing"],
                                                 "targets": [{"id": "fps", "kpi": "frame_pacing",
                                                              "metric": "achieved_fps", "min": 119.9},
                                                             {"id": "slack", "kpi": "underrun", "min": 0.5}]})
    report = {"intervals": {"preview": {"ok": None}, "video": {"ok": None}},
              "pacing": {"status": "ok", "jank_pct": 0.18, "achieved_fps": 119.79, "frame_ms": {"p99": 15.6},
                         "value_source": "assumed"},
              "subsystems": {"abox": {"value_source": "assumed", "deadline_slack": [{"slack_ms": 4.7}, {"slack_ms": 0.3}],
                                      "route": {"id": "spk", "latency_ms": 53.4, "latency_target_ms": 60.0}}}}
    rows = evaluate_kpis(_graph({}), report, contract, jobs_evaluated=False)
    by = {(r["kpi"], r["metric"]): r for r in rows}
    assert by[("latency", None)]["status"] == "pass" and by[("latency", None)]["target"] == 60.0
    assert "latency_target_ms" in by[("latency", None)]["basis"]
    assert by[("underrun", None)]["value"] == 0.3 and by[("underrun", None)]["status"] == "fail"
    assert by[("frame_pacing", "jank_pct")]["status"] == "no_target"
    assert by[("frame_pacing", "achieved_fps")]["status"] == "fail"
    # without declared targets the route's own latency target is not applied (opt-in): value only
    bare = contract.model_copy(update={"targets": None})
    latency = next(r for r in evaluate_kpis(_graph({}), report, bare, jobs_evaluated=False) if r["kpi"] == "latency")
    assert latency["status"] == "no_target" and latency["target"] is None and latency["value"] == 53.4
    # a frame output judged by the interval path keeps latency there
    report["intervals"]["preview"]["ok"] = True
    assert "latency" not in {r["kpi"] for r in evaluate_kpis(_graph({}), report, contract, jobs_evaluated=False)}


def test_a_latency_target_on_a_frame_judged_scenario_is_noted_not_applied():
    contract = JudgementContract.model_validate({"kpis": ["interval", "latency"], "targets": [
        {"id": "lat", "kpi": "latency", "max": 100}]})
    report = _shot_report()
    _judge_kpis(_graph({}), report, contract, jobs_evaluated=False)
    assert "KPI 목표 미적용(frame interval 판정이 latency 판정): lat" in report["verdict"]["notes"]
    assert report["verdict"]["status"] == "ok"


def test_a_job_error_leaves_the_declared_job_kpis_no_input():
    pipeline = {"jobs": [{"id": "shot", "milestones": {"thumbnail": "s"}, "kpis": ["event_latency", "peak_footprint"]}]}
    contract = JudgementContract.model_validate({"kpis": ["interval"], "targets": [
        {"id": "heap", "kpi": "peak_footprint", "max": 2048}]})
    report = {**_shot_report(), "jobs": [], "jobs_error": "stage s: no clock"}
    _judge_kpis(_graph(pipeline), report, contract, jobs_evaluated=True)
    assert {(r["kpi"], r["milestone"], r["status"]) for r in report["kpis"]} == {
        ("event_latency", "thumbnail", "no_input"), ("peak_footprint", None, "no_input")}
    assert report["verdict"]["kpis"]["status"] == "no_input" and report["verdict"]["status"] == "ok"
    assert "job 평가 오류로 job KPI 판정 불가: stage s: no clock" in report["verdict"]["notes"]


def test_a_fail_fails_the_verdict_and_a_pass_does_not_lift_not_applicable():
    pipeline = {"jobs": [{"id": "shot", "kpis": ["peak_footprint", "event_energy"]}]}
    contract = JudgementContract.model_validate({"kpis": ["interval"], "targets": [
        {"id": "heap", "kpi": "peak_footprint", "max": 2048}]})
    report = _shot_report()
    _judge_kpis(_graph(pipeline), report, contract, jobs_evaluated=True)
    assert report["verdict"]["status"] == "fail"
    assert report["verdict"]["reasons"] == ["KPI heap: 2100 MB > 2048 MB (가정 목표)"]
    report = _shot_report(peak={"footprint_mb": 100.0})
    report["verdict"]["status"] = "not_applicable"
    _judge_kpis(_graph(pipeline), report, contract, jobs_evaluated=True)
    assert report["verdict"]["status"] == "not_applicable" and report["verdict"]["kpis"]["pass"] == 1


def test_nothing_declared_leaves_the_report_alone():
    report = _shot_report()
    before = deepcopy(report)
    _judge_kpis(_graph({}), report, None, jobs_evaluated=True)
    assert report == before


# ---------------------------------------------------------------- E2600 capture with a declared target

@pytest.fixture(scope="module")
def tables():
    with open(f"{ROOT}/00_hw/dvfs-exynos2600-sample-v0.yaml", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


def test_e2600_200m_mf_footprint_against_a_heap_target(tables):
    graph = _exynos2600_generated_graph("uc-cam-capture-e2600", "cam-cap-r1-remosaic-mf")
    pipeline = deepcopy(graph.scenario.pipeline)
    pipeline["judgement"] = {**(pipeline.get("judgement") or {}), "targets": [
        {"id": "heap", "kpi": "peak_footprint", "max": 2048},
        {"id": "thumb-200m", "kpi": "event_latency", "job": "still_shot_200m", "milestone": "thumbnail", "max": 2000}]}
    graph.scenario.pipeline = pipeline
    r = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)
    by = {r_["id"]: r_ for r_ in r["kpis"] if r_["id"]}
    assert by["heap"]["status"] == "fail" and by["heap"]["value"] > 2048
    assert by["thumb-200m"]["status"] == "pass"
    assert r["verdict"]["status"] == "fail" and any(x.startswith("KPI heap:") for x in r["verdict"]["reasons"])
