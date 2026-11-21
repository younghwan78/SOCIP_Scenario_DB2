"""R-3b event job evaluator (job-v1) on a real E2600 capture graph with an injected still-shot job."""

from copy import deepcopy

import pytest

from scenario_db.sim.jobs import JobError, evaluate_jobs
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

VARIANT = "cam-cap-r1-mf"          # sensor_out 8000x6000 -> one YUV420 10-bit frame = 90 MB
FRAME_MB = 8000 * 6000 * 1.5 * 10 / 8 / 1e6
JOB = {
    "id": "still_shot", "trigger": {"kind": "event", "at_ms": 100},
    "phases": ["acquire", "process", "encode"],
    "buffers": {"cap_yuv": {"format": "YUV420", "bitdepth": 10, "count": "pool"}, "jpeg": {"mb": "file_mb"}},
    "stages": [
        {"id": "readout", "phase": "acquire", "kind": "sensor", "nodes": ["sensor_rear"], "holds": ["csispdp"],
         "mode": {"param": "cap_mode"}, "frames": 1, "work": {"switch_in_ms": "sw_ms", "switch_out_ms": "sw_ms"}},
        {"id": "reproc", "phase": "process", "nodes": ["byrp", "rgbp"], "frames": "zsl_frames",
         "reads": ["ZSL_RING_BUF"], "writes": ["cap_yuv"], "chunk": {"by": "frame"}, "after": ["readout"]},
        {"id": "merge", "phase": "process", "nodes": ["mtnr"], "frames": "zsl_frames",
         "after": [{"stage": "reproc", "per": "frame"}]},
        {"id": "enc", "phase": "encode", "kind": "sw", "nodes": ["post_proc"], "writes": ["jpeg"],
         "work": {"runtime_ms": "enc_ms", "power_mw": 400}, "after": ["merge"]},
    ],
    "milestones": {"saved": "enc"},
}
PARAMS = {"cap_mode": "binning_2x2", "sw_ms": 5, "zsl_frames": 4, "pool": 2, "enc_ms": 35, "file_mb": 4}


def _graph(job=None, params=None, variant=VARIANT):
    graph = _exynos2600_generated_graph("uc-cam-capture-e2600", variant)
    graph.scenario.pipeline = {**graph.scenario.pipeline, "jobs": [job or deepcopy(JOB)]}
    graph.scenario.power_options = {"params": {**PARAMS, **(params or {})}}
    return graph


def _report(graph):
    return analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"))


def _job(**params):
    return _report(_graph(params=params))["jobs"][0]


def test_jobs_are_opt_in_and_leave_the_steady_report_unchanged():
    plain = _report(_exynos2600_generated_graph("uc-cam-capture-e2600", VARIANT))
    with_job = _report(_graph())
    assert "jobs" not in plain
    assert {k: v for k, v in with_job.items() if k != "jobs"} == plain


def test_milestones_follow_the_stage_dag():
    job = _job()
    stages = {s["id"]: s for s in job["stages"]}
    assert job["model"] == "job-v1"
    assert stages["reproc"]["start_ms"] >= stages["readout"]["end_ms"] - PARAMS["sw_ms"] - 1e-6  # data at readout end
    assert stages["enc"]["start_ms"] == pytest.approx(stages["merge"]["end_ms"])
    assert job["milestones"]["saved"] == pytest.approx(stages["enc"]["end_ms"]) == pytest.approx(job["makespan_ms"])
    assert stages["enc"]["service_ms"] == pytest.approx(PARAMS["enc_ms"])
    assert stages["reproc"]["chunks"] == stages["merge"]["chunks"] == PARAMS["zsl_frames"]
    assert job["energy_mj"]["by_kind"]["sw"] == pytest.approx(400 * PARAMS["enc_ms"] / 1000.0)
    assert [p["id"] for p in job["phases"]] == ["acquire", "process", "encode"]


def test_the_buffer_pool_bounds_the_footprint():
    small, large = _job(pool=1), _job(pool=4)
    # one capture frame in flight; the last one is freed before the JPEG is written
    assert small["peak"]["footprint_mb"] == pytest.approx(FRAME_MB, abs=1e-3)
    assert large["peak"]["footprint_mb"] > small["peak"]["footprint_mb"]
    assert small["makespan_ms"] >= large["makespan_ms"] - 1e-6   # a smaller pool can only stall the producer


def test_the_sensor_reservation_drops_preview_frames_and_chunks_delay_rt_work():
    job = _job()
    assert job["background"]["dropped_frames"] >= 1
    assert job["background"]["rt_wait_max_ms"] > 0
    graph = _graph()
    graph.scenario.pipeline["jobs"][0]["background"] = "none"
    quiet = _report(graph)["jobs"][0]
    assert quiet["background"]["dropped_frames"] == 0 and quiet["background"]["rt_wait_max_ms"] == 0
    assert quiet["makespan_ms"] <= job["makespan_ms"] + 1e-6


def test_stripe_chunks_shorten_the_rt_wait():
    frames = deepcopy(JOB)
    frames["stages"][2]["after"] = ["reproc"]            # stripe chunks only allow a stage-level consumer
    stripes = deepcopy(frames)
    for i in (1, 2):
        stripes["stages"][i]["chunk"] = {"by": "stripe", "max_line_px": 1000}
    by_frame = _report(_graph(job=frames, params={"pool": 4}))["jobs"][0]
    by_stripe = _report(_graph(job=stripes, params={"pool": 4}))["jobs"][0]
    stage = next(s for s in by_stripe["stages"] if s["id"] == "reproc")
    assert stage["chunks"] == PARAMS["zsl_frames"] * 8
    # a full-frame MTNR chunk blocks the RT frame; stripes interleave with it, at the cost of a longer shot
    assert by_stripe["background"]["rt_wait_max_ms"] < by_frame["background"]["rt_wait_max_ms"] / 2
    assert by_stripe["makespan_ms"] >= by_frame["makespan_ms"]


def test_a_stage_level_consumer_needs_a_pool_for_every_frame():
    job = deepcopy(JOB)
    job["stages"][2]["after"] = ["reproc"]
    graph = _graph(job=job)
    with pytest.raises(JobError, match="pool 2 < 4 frames"):
        _report(graph)


def test_an_unmatched_selector_yields_no_job():
    job = deepcopy(JOB)
    job["when"] = {"subscenario": "NOT_THIS_ONE"}
    assert _report(_graph(job=job))["jobs"] == []


def test_disabled_nodes_skip_their_stage():
    job = deepcopy(JOB)
    job["stages"].append({"id": "ai", "phase": "process", "kind": "fixed", "nodes": ["npu"],
                          "work": {"duration_ms": 10}, "after": ["readout"]})
    out = _report(_graph(job=job))["jobs"][0]
    assert "ai" not in {s["id"] for s in out["stages"]}
    assert any("stage ai skipped" in n for n in out["notes"])


def test_evaluate_jobs_without_declaration_is_empty():
    graph = _exynos2600_generated_graph("uc-cam-capture-e2600", VARIANT)
    assert evaluate_jobs(graph, {}, None, {}, None) == []


def _with_slot(node, values, job=None):
    graph = _graph(job=job)
    cfgs = dict(graph.variant.node_configs or {})
    cfg = dict(cfgs.get(node) or {})
    cfg["sim"] = {**(cfg.get("sim") or {}), "jobs": {"still_shot": values}}
    cfgs[node] = cfg
    graph.variant.node_configs = cfgs
    return graph


def test_measured_stage_values_replace_the_computed_ones():
    base = {s["id"]: s for s in _job()["stages"]}
    graph = _with_slot("mtnr", {"merge": {"service_ms": 60.0, "mb": 100.0, "evidence_ref": "meas-x"}})
    out = _report(graph)["jobs"][0]
    merge = {s["id"]: s for s in out["stages"]}["merge"]
    assert merge["service_ms"] == pytest.approx(60.0)
    assert merge["mb"] == pytest.approx(100.0)
    assert merge["value_source"] == "measured" and merge["evidence_ref"] == "meas-x"
    assert merge["energy_mj"] == pytest.approx(base["merge"]["energy_mj"])   # HW keeps its per-pixel energy
    assert {s["id"]: s for s in out["stages"]}["reproc"]["value_source"] == base["reproc"]["value_source"]


def test_measured_sw_time_keeps_the_declared_power():
    out = _report(_with_slot("post_proc", {"enc": {"service_ms": 70.0}}))["jobs"][0]
    enc = {s["id"]: s for s in out["stages"]}["enc"]
    assert enc["service_ms"] == pytest.approx(70.0) and enc["energy_mj"] == pytest.approx(400 * 70 / 1000.0)


def test_a_measured_clock_sets_the_hw_chunk_time():
    base = {s["id"]: s for s in _job()["stages"]}["merge"]
    out = _report(_with_slot("mtnr", {"merge": {"clock_mhz": base["clock_mhz"]["mtnr"] * 2}}))["jobs"][0]
    merge = {s["id"]: s for s in out["stages"]}["merge"]
    assert merge["service_ms"] == pytest.approx(base["service_ms"] / 2, rel=1e-3)


@pytest.mark.parametrize("node,values,message", [
    ("mtnr", {"ghost": {"service_ms": 1}}, "unknown stage 'ghost'"),
    ("mtnr", {"merge": {"latency_ms": 1}}, r"values \['latency_ms'\]"),
    ("byrp", {"merge": {"service_ms": 1}}, "belong under one of its nodes"),
    ("mtnr", {"merge": {"service_ms": 0}}, "must be a positive number"),
    ("sensor_rear", {"readout": {"mb": 1}}, "takes only service_ms"),
])
def test_measured_slot_errors(node, values, message):
    with pytest.raises(JobError, match=message):
        _report(_with_slot(node, values))


def test_ip_params_are_parameter_expressions():
    base = {s["id"]: s for s in _job()["stages"]}["merge"]
    job = deepcopy(JOB)
    job["stages"][2]["ip_params"] = {"ppc": "pool * 4"}     # pool = 2 -> ppc 8 (catalog MTNR: 4)
    merge = {s["id"]: s for s in _report(_graph(job=job))["jobs"][0]["stages"]}["merge"]
    assert merge["service_ms"] == pytest.approx(base["service_ms"] / 2, rel=1e-3)
