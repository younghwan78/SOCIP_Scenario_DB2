"""R-3b event job evaluator (job-v1) on a real E2600 capture graph with an injected still-shot job."""

from copy import deepcopy
import math

import pytest

from scenario_db.sim.jobs import JobError, evaluate_jobs
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

VARIANT = "cam-cap-r1-mf"          # 12M session (C-2): sensor_out 4000x3000 -> one YUV420 10-bit frame = 22.5 MB
FRAME_MB = 4000 * 3000 * 1.5 * 10 / 8 / 1e6
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
    graph = _plain(variant)
    graph.scenario.pipeline = {**graph.scenario.pipeline, "jobs": [job or deepcopy(JOB)]}
    graph.scenario.power_options = {"params": {**PARAMS, **(params or {})}}
    return graph


def _plain(variant=VARIANT):
    """The capture graph without its declared jobs (the scenario declares its own shot since R-3c) and without
    the session lifetime of the ZSL ring (its resident footprint is a capture-data fact, tested there)."""
    graph = _exynos2600_generated_graph("uc-cam-capture-e2600", variant)
    pipeline = {k: v for k, v in graph.scenario.pipeline.items() if k != "jobs"}
    pipeline["buffers"] = {name: {k: v for k, v in spec.items() if k != "lifetime"}
                           for name, spec in (pipeline.get("buffers") or {}).items()}
    graph.scenario.pipeline = pipeline
    return graph


def _report(graph):
    report = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"))
    if "jobs_error" in report:        # the steady report survives; the job error is reported beside it
        raise JobError(report["jobs_error"])
    return report


def _job(**params):
    return _report(_graph(params=params))["jobs"][0]


def test_jobs_are_opt_in_and_leave_the_steady_report_unchanged():
    plain = _report(_plain())
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
    assert stage["chunks"] == PARAMS["zsl_frames"] * 4           # 4000 px wide, 1000 px line buffer
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
    assert evaluate_jobs(_plain(), {}, None, {}, None) == []


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


def test_the_condition_hash_follows_the_job_params_from_design_conditions():
    from scenario_db.api.services.timing_budget import _condition_hash
    from tests.unit.sim.test_service_hash import _request

    graph, opts, shim = _graph(), TimingBudgetOptions(throughput_model="pipelined"), _request()
    before = _condition_hash(graph, opts, shim, {})
    graph.variant.design_conditions = {**(graph.variant.design_conditions or {}), "enc_ms": 100}
    assert _condition_hash(graph, opts, shim, {}) != before
    assert _report(graph)["jobs"][0]["stages"][-1]["service_ms"] == pytest.approx(100.0)


def test_a_hw_stage_mode_selects_the_catalog_sim_mode():
    graph = _graph()
    node = next(n for n in graph.scenario.pipeline["nodes"] if n["id"] == "byrp")
    ip = graph.ip_catalog[node["ip_ref"]]
    ip.capabilities = deepcopy(ip.capabilities)
    normal = ip.capabilities["sim"]["modes"]["Normal"]
    ip.capabilities["sim"]["modes"]["JobFast"] = {**normal, "ppc": normal["ppc"] * 2}
    stage = {"id": "a", "phase": "p", "nodes": ["byrp"], "mode": "Normal"}
    graph.scenario.pipeline["jobs"] = [{"id": "j", "background": "none", "stages": [stage]}]
    base = _report(graph)["jobs"][0]["stages"][0]["service_ms"]
    stage["mode"] = "JobFast"
    assert _report(graph)["jobs"][0]["stages"][0]["service_ms"] == pytest.approx(base / 2, rel=1e-3)
    stage["mode"] = "Ghost"
    with pytest.raises(JobError, match="no catalog mode 'Ghost'"):
        _report(graph)


def test_the_trigger_start_is_a_parameter_expression():
    job = deepcopy(JOB)
    job["trigger"]["at_ms"] = "sw_ms * 20"                 # = 100, the literal of JOB
    assert _report(_graph(job=job))["jobs"][0] == _job()
    job["trigger"]["at_ms"] = "sw_ms * 3"
    assert _report(_graph(job=job))["jobs"][0] != _job()


def test_the_job_background_is_the_final_steady_power():
    from scenario_db.sim.models import CpuProfile, CpuTaskProfile, SimulationRunConfig
    from tests.unit.sim.test_cpu_topology_profile import synthetic_topology

    opts = TimingBudgetOptions(throughput_model="pipelined", cpu_model="profile",
                               cpu_profile=CpuProfile(tasks=[CpuTaskProfile(task="test", cluster="C", cycles=1e7,
                                                                            bus_bytes=100e6)]))
    report = analyze_timing_budget(_graph(), opts,
                                   config=SimulationRunConfig(power_params=synthetic_topology([("C", "C", 4)])))
    assert report["jobs"][0]["background"]["power_mw"] == pytest.approx(report["power"]["total_mw"], abs=0.1)


def test_resolved_expressions_get_the_literal_ranges():
    for params, message in (({"zsl_frames": 2.5}, "frames 2.5 must be an integer >= 1"),
                            ({"pool": 0}, "count 0.0 must be an integer >= 1"),
                            ({"enc_ms": -1}, "runtime_ms -1.0 must be >= 0")):
        with pytest.raises(JobError, match=message):
            _job(**params)


def _stage(sid, **kw):
    return {"id": sid, "phase": "p", **kw}


def _one(stages, buffers=None, background="steady", params=None, **job):
    spec = {"id": "j", "background": background, "stages": stages, **job}
    if buffers:
        spec["buffers"] = buffers
    return _report(_graph(job=spec, params=params))["jobs"][0]


def test_an_otf_group_and_a_sensor_hold_cannot_deadlock():
    out = _one([
        _stage("otf", nodes=["byrp", "rgbp"], frames=4, chunk={"by": "frame"}),
        _stage("readout", kind="sensor", nodes=["sensor_rear"], holds=["rgbp", "byrp"], mode={"param": "cap_mode"},
               frames=1),
    ])
    assert {s["id"] for s in out["stages"]} == {"otf", "readout"}


def test_a_shared_buffer_is_freed_after_its_last_reader():
    out = _one([
        _stage("prod", nodes=["byrp"], frames=2, writes=["x"], chunk={"by": "frame"}),
        _stage("fast", kind="fixed", nodes=["post_proc"], work={"duration_ms": 1}, after=["prod"]),
        _stage("slow", kind="fixed", nodes=["mtnr"], work={"duration_ms": 50}, after=["prod"]),
    ], buffers={"x": {"mb": 10, "count": 2}})
    slow = {s["id"]: s for s in out["stages"]}["slow"]
    assert out["peak"]["footprint_mb"] == pytest.approx(20.0, abs=1e-3)
    # both frames stay allocated until `slow` (the last reader) ends
    held = [v for t, v in zip(range(len(out["series"]["footprint_mb"])), out["series"]["footprint_mb"])
            if t < slow["end_ms"] - 1]
    assert held and min(held[int(slow["start_ms"]) + 1:]) >= 20.0 - 1e-6


def test_the_peak_window_is_exact_over_the_run_intervals():
    out = _one([_stage("burst", kind="fixed", nodes=["post_proc"], work={"duration_ms": 1, "power_mw": 1000})],
               background="none")
    bg = out["background"]["power_mw"]
    assert out["peak"]["power_instant_mw"] == pytest.approx(bg + 1000, abs=0.1)
    assert out["peak"]["power_mw"] == pytest.approx(bg + 100, abs=0.1)       # 1 mJ over the 10 ms window


def test_repeating_triggers_are_rejected():
    for kind in ("burst", "periodic"):
        with pytest.raises(JobError, match=f"trigger kind '{kind}' is not supported"):
            _one([_stage("a", nodes=["byrp"])], trigger={"kind": kind, "count": 3, "interval_ms": 10})


def test_a_to_consumer_reads_and_frees_the_buffer():
    out = _one([
        _stage("prod", nodes=["byrp"], writes=["x"]),
        _stage("mid", kind="fixed", nodes=["post_proc"], work={"duration_ms": 1}, after=["prod"]),
        _stage("use", kind="fixed", nodes=["mtnr"], work={"duration_ms": 1}, after=["mid"]),
    ], buffers={"x": {"mb": 10, "to": ["use"]}})
    stages = {s["id"]: s for s in out["stages"]}
    assert stages["use"]["mb"] == pytest.approx(10.0) and stages["mid"]["mb"] == 0.0
    assert out["series"]["footprint_mb"][-1] == pytest.approx(0.0)


def test_a_multi_frame_sensor_readout_produces_every_frame():
    out = _one([
        _stage("readout", kind="sensor", nodes=["sensor_rear"], mode={"param": "cap_mode"}, frames=3,
               writes=["raw"], chunk={"by": "frame"}),
        _stage("proc", nodes=["byrp"], frames=3, chunk={"by": "frame"}, after=[{"stage": "readout", "per": "frame"}]),
    ], buffers={"raw": {"format": "BAYER", "bitdepth": 10, "count": 3}})
    stages = {s["id"]: s for s in out["stages"]}
    frame_mb = 8000 * 6000 * 10 / 8 / 1e6          # binning_2x2 readout size, BAYER 10-bit
    assert stages["readout"]["mb"] == pytest.approx(3 * frame_mb, rel=1e-6)
    assert stages["proc"]["start_ms"] < stages["readout"]["end_ms"]      # frame 0 is processed during readout
    assert "readout" in out["energy_mj"]["unattributed"]


def test_a_transfer_without_buffers_counts_its_declared_bytes():
    out = _one([_stage("store", kind="transfer", nodes=["post_proc"], work={"mb": 12, "mb_per_s": 1200})],
               background="none")
    st = out["stages"][0]
    assert st["service_ms"] == pytest.approx(10.0) and st["mb"] == pytest.approx(12.0)
    assert out["peak"]["bw_instant_mbs"] == pytest.approx(out["background"]["bw_mbs"] + 1200, abs=0.1)


def test_stripe_overlap_is_processed_not_stored():
    def write_mb(chunk):
        out = _one([_stage("a", nodes=["byrp"], writes=["y"], chunk=chunk)],
                   buffers={"y": {"format": "YUV420", "bitdepth": 10}}, background="none")
        return out["stages"][0]["mb"], out["stages"][0]["service_ms"]

    (mb_f, t_f), (mb_s, t_s) = write_mb({"by": "frame"}), write_mb({"by": "stripe", "max_line_px": 1000,
                                                                     "overlap_px": 64})
    assert mb_s == pytest.approx(mb_f) and t_s > t_f


def test_resolved_stripe_widths_and_the_chunk_count_are_checked():
    with pytest.raises(JobError, match="max_line_px 64.0 must exceed overlap_px 64"):
        _one([_stage("a", nodes=["byrp"], chunk={"by": "stripe", "max_line_px": "sw_ms * 12.8", "overlap_px": 64})])
    with pytest.raises(JobError, match=r"chunks \(through stage a\) exceed"):
        _one([_stage("a", nodes=["byrp"], frames=30000)])


def test_the_condition_hash_covers_job_only_catalog_modes():
    from scenario_db.api.services.timing_budget import _condition_hash
    from tests.unit.sim.test_service_hash import _request

    graph, opts, shim = _graph(), TimingBudgetOptions(throughput_model="pipelined"), _request()
    before = _condition_hash(graph, opts, shim, {})
    ip = graph.ip_catalog[next(n for n in graph.scenario.pipeline["nodes"] if n["id"] == "mtnr")["ip_ref"]]
    ip.capabilities = deepcopy(ip.capabilities)
    ip.capabilities["sim"]["modes"]["JobOnly"] = {"ppc": 8.0, "unit_power_mw_mp": 1.0}
    assert _condition_hash(graph, opts, shim, {}) != before


def test_steady_only_callers_skip_the_jobs():
    graph = _graph()
    assert "jobs" not in analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), jobs=False)


def test_a_slot_must_be_a_mapping_and_keeps_the_stage_provenance():
    graph = _with_slot("mtnr", {"merge": 60})
    with pytest.raises(JobError, match="sim.jobs.still_shot.merge must be a mapping"):
        _report(graph)
    job = deepcopy(JOB)
    job["stages"][2].update(evidence_ref="doc-1", basis="vendor sheet")
    merge = {s["id"]: s for s in _report(_graph(job=job))["jobs"][0]["stages"]}["merge"]
    assert merge["evidence_ref"] == "doc-1" and merge["basis"] == "vendor sheet"
    out = _report(_with_slot("mtnr", {"merge": {"service_ms": 60.0, "basis": "trace t1"}}, job=job))["jobs"][0]
    merge = {s["id"]: s for s in out["stages"]}["merge"]
    assert merge["evidence_ref"] == "doc-1" and merge["basis"] == "trace t1"



def test_a_job_error_leaves_the_steady_report_intact():
    graph = _graph(job={"id": "j", "trigger": {"kind": "burst", "count": 3}, "stages": [_stage("a", nodes=["byrp"])]})
    report = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"))
    assert report["jobs"] == [] and "not supported" in report["jobs_error"]
    plain = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), jobs=False)
    assert {k: v for k, v in report.items() if k not in ("jobs", "jobs_error")} == plain


def test_a_per_frame_reader_of_fewer_frames_does_not_stall_the_pool():
    out = _one([
        _stage("prod", nodes=["byrp"], frames=3, writes=["x"], chunk={"by": "frame"}),
        _stage("use", nodes=["rgbp"], frames=1, chunk={"by": "frame"}, after=[{"stage": "prod", "per": "frame"}]),
    ], buffers={"x": {"mb": 10, "count": 1}}, background="none")
    assert {s["id"] for s in out["stages"]} == {"prod", "use"}


def test_a_waiting_group_does_not_hold_a_resource_it_is_not_running_on():
    out = _one([
        _stage("long", kind="fixed", nodes=["rgbp"], work={"duration_ms": 50}),
        _stage("grp", nodes=["byrp", "rgbp"]),
        _stage("solo", kind="fixed", nodes=["byrp"], work={"duration_ms": 1}),
    ], background="none")
    stages = {s["id"]: s for s in out["stages"]}
    assert stages["solo"]["end_ms"] < 5.0                  # not blocked behind the group waiting for rgbp
    assert stages["grp"]["start_ms"] >= stages["long"]["end_ms"] - 1e-6


def test_the_condition_hash_covers_job_size_anchors():
    from scenario_db.api.services.timing_budget import _condition_hash
    from tests.unit.sim.test_service_hash import _request

    graph, opts, shim = _graph(), TimingBudgetOptions(throughput_model="pipelined"), _request()
    graph.variant.size_overrides = {**(graph.variant.size_overrides or {}), "job_only": "1000x1000"}
    before = _condition_hash(graph, opts, shim, {})
    graph.variant.size_overrides = {**graph.variant.size_overrides, "job_only": "2000x2000"}
    assert _condition_hash(graph, opts, shim, {}) != before


def test_a_sensor_stage_cannot_wait_per_frame():
    with pytest.raises(JobError, match="sensor stage readout cannot read job buffers or wait per frame"):
        _one([
            _stage("prep", nodes=["byrp"], chunk={"by": "frame"}),
            _stage("readout", kind="sensor", nodes=["sensor_rear"], mode={"param": "cap_mode"},
                   after=[{"stage": "prep", "per": "frame"}], chunk={"by": "frame"}),
        ])


def test_a_stage_level_reader_reads_every_producer_frame():
    out = _one([
        _stage("prod", nodes=["byrp"], frames=3, writes=["x"], chunk={"by": "frame"}),
        _stage("merge", kind="fixed", nodes=["mtnr"], work={"duration_ms": 1}, after=["prod"]),
    ], buffers={"x": {"mb": 10, "count": 3}}, background="none")
    assert {s["id"]: s for s in out["stages"]}["merge"]["mb"] == pytest.approx(30.0)


def test_sensor_writes_only_while_a_frame_is_read_out():
    out = _one([_stage("readout", kind="sensor", nodes=["sensor_rear"], mode={"param": "cap_mode"}, writes=["raw"],
                       work={"switch_in_ms": 50, "switch_out_ms": 50})],
               buffers={"raw": {"mb": 90}}, background="none")
    frame_ms = 1000.0 / 30.0                               # binning_2x2 at 30 fps
    assert out["peak"]["bw_instant_mbs"] == pytest.approx(out["background"]["bw_mbs"] + 90 / frame_ms * 1000, rel=1e-3)


def test_dropped_preview_frames_are_counted_once_per_frame():
    out = _one([_stage("readout", kind="sensor", nodes=["sensor_rear"], holds=["csispdp", "byrp", "rgbp"],
                       mode={"param": "cap_mode"}, work={"switch_in_ms": 50, "switch_out_ms": 50})])
    reservation = next(s for s in out["stages"] if s["id"] == "readout")["elapsed_ms"]
    period = analyze_timing_budget(_graph(), TimingBudgetOptions(throughput_model="pipelined"))["period_ms"]
    assert 0 < out["background"]["dropped_frames"] <= math.ceil(reservation / period) + 1


def test_a_stripe_that_fits_the_line_is_one_chunk():
    graph = _graph(job={"id": "j", "background": "none", "stages": [
        _stage("a", nodes=["byrp"], size_ref="tst", chunk={"by": "stripe", "max_line_px": 1000, "overlap_px": 64})]})
    graph.variant.size_overrides = {**(graph.variant.size_overrides or {}), "tst": "1000x100"}
    assert _report(graph)["jobs"][0]["stages"][0]["chunks"] == 1
    graph.variant.size_overrides["tst"] = "1001x100"
    assert _report(graph)["jobs"][0]["stages"][0]["chunks"] == 2


def test_session_reads_use_the_variant_buffer_overrides():
    base = {s["id"]: s for s in _job()["stages"]}["reproc"]["mb"]
    graph = _graph()
    graph.variant.buffer_overrides = {**(graph.variant.buffer_overrides or {}), "ZSL_RING_BUF": {"mb": 1000}}
    reproc = {s["id"]: s for s in _report(graph)["jobs"][0]["stages"]}["reproc"]
    assert reproc["mb"] > base and reproc["mb"] >= 1000 * PARAMS["zsl_frames"]


def test_a_measured_time_keeps_the_declared_power_from_zero():
    job = deepcopy(JOB)
    job["stages"][3]["work"]["runtime_ms"] = 0
    out = _report(_with_slot("post_proc", {"enc": {"service_ms": 35.0}}, job=job))["jobs"][0]
    enc = {s["id"]: s for s in out["stages"]}["enc"]
    assert enc["energy_mj"] == pytest.approx(400 * 35 / 1000.0)


def test_a_slot_cannot_claim_another_node():
    with pytest.raises(JobError, match="must not set 'node'"):
        _report(_with_slot("byrp", {"merge": {"node": "mtnr", "service_ms": 1.0}}))


def test_job_slots_do_not_change_the_steady_replay_fingerprint():
    from scenario_db.sim.measured_timing import baseline_fingerprint

    before = baseline_fingerprint(_graph())
    assert baseline_fingerprint(_with_slot("mtnr", {"merge": {"service_ms": 60.0}})) == before



def test_a_too_short_frame_period_is_a_job_error_not_a_hang():
    graph = _graph()
    report = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"))
    from scenario_db.sim.jobs import MIN_PERIOD_MS, _Evaluation, _Params
    from scenario_db.models.definition.job import JobSpec

    inputs = __import__("scenario_db.sim.adapter", fromlist=["build_simulation_inputs"]).build_simulation_inputs(
        graph, None)
    ev = _Evaluation(graph, {**report, "period_ms": 0.0, "fps": 1e9}, inputs, JobSpec.model_validate(JOB),
                     _Params(PARAMS, "job still_shot"), None)
    assert ev.period < MIN_PERIOD_MS
    with pytest.raises(JobError, match="frame period"):
        ev.run()


def test_an_unread_output_frame_frees_its_slot():
    out = _one([_stage("prod", nodes=["byrp"], frames=2, writes=["x"], chunk={"by": "frame"})],
               buffers={"x": {"mb": 10, "count": 1}}, background="none")
    assert out["stages"][0]["chunks"] == 2


def test_an_arithmetic_error_in_a_job_expression_is_a_job_error():
    job = deepcopy(JOB)
    job["stages"][3]["work"]["runtime_ms"] = "35 / (sw_ms - 5)"          # sw_ms = 5 -> divides by zero
    with pytest.raises(JobError, match="enc.work.runtime_ms"):
        _report(_graph(job=job))


def test_resource_capacity_lets_independent_chunks_overlap():
    graph = _graph(job={"id": "j", "background": "none", "stages": [
        _stage("a", kind="fixed", nodes=["post_proc"], work={"duration_ms": 1}),
        _stage("b", kind="fixed", nodes=["post_proc"], work={"duration_ms": 1})]})
    one = _report(graph)["jobs"][0]["makespan_ms"]
    node = next(n for n in graph.scenario.pipeline["nodes"] if n["id"] == "post_proc")
    node["resource_capacity"] = 2
    two = _report(graph)["jobs"][0]["makespan_ms"]
    assert one == pytest.approx(2.0) and two == pytest.approx(1.0)


def test_stripe_chunks_run_their_own_width():
    def service(width, chunk):
        graph = _graph(job={"id": "j", "background": "none", "stages": [
            _stage("a", nodes=["byrp"], size_ref="tst", chunk=chunk)]})
        graph.variant.size_overrides = {**(graph.variant.size_overrides or {}), "tst": f"{width}x1000"}
        st = _report(graph)["jobs"][0]["stages"][0]
        return st["chunks"], st["service_ms"]

    base = service(1000, {"by": "frame"})[1]
    chunks, total = service(1001, {"by": "stripe", "max_line_px": 1000, "overlap_px": 64})
    assert chunks == 2 and total == pytest.approx(base * 1065 / 1000, rel=1e-3)   # 1000 px + (1 + 64) px


def test_job_buffers_use_the_shared_format_factors():
    graph = _graph(job={"id": "j", "background": "none", "stages": [
        _stage("a", nodes=["byrp"], size_ref="tst", writes=["rgb"])], "buffers": {"rgb": {"format": "RGB", "bitdepth": 8}}})
    graph.variant.size_overrides = {**(graph.variant.size_overrides or {}), "tst": "1000x1000"}
    assert _report(graph)["jobs"][0]["stages"][0]["mb"] == pytest.approx(3.0)


def test_a_sensor_session_read_counts_in_the_bandwidth():
    graph = _graph(job={"id": "j", "background": "none", "stages": [
        _stage("readout", kind="sensor", nodes=["sensor_rear"], mode={"param": "cap_mode"}, reads=["ZSL_RING_BUF"])]})
    graph.variant.buffer_overrides = {**(graph.variant.buffer_overrides or {}), "ZSL_RING_BUF": {"mb": 100}}
    out = _report(graph)["jobs"][0]
    assert out["peak"]["bw_instant_mbs"] > out["background"]["bw_mbs"] + 100 / 34 * 1000 * 0.99


def test_a_hw_mode_without_unit_power_is_unattributed():
    graph = _graph()
    ip = graph.ip_catalog[next(n for n in graph.scenario.pipeline["nodes"] if n["id"] == "byrp")["ip_ref"]]
    ip.capabilities = deepcopy(ip.capabilities)
    ip.capabilities["sim"]["modes"]["NoPower"] = {"ppc": 8.0}
    graph.scenario.pipeline["jobs"] = [{"id": "j", "background": "none",
                                        "stages": [_stage("a", nodes=["byrp"], mode="NoPower")]}]
    out = _report(graph)["jobs"][0]
    assert out["energy_mj"]["unattributed"] == ["a"]


def test_a_deep_evaluated_dag_has_no_recursion_limit():
    n = 1100
    stages = [_stage(f"s{i}", kind="fixed", nodes=["post_proc"], work={"duration_ms": 0},
                     **({"after": [f"s{i + 1}"]} if i + 1 < n else {})) for i in range(n)]
    out = _one(stages, background="none")
    assert len(out["stages"]) == n


def test_the_condition_hash_covers_the_session_buffers():
    from scenario_db.api.services.timing_budget import _condition_hash
    from tests.unit.sim.test_service_hash import _request

    graph, opts, shim = _graph(), TimingBudgetOptions(throughput_model="pipelined"), _request()
    before = _condition_hash(graph, opts, shim, {})
    bufs = deepcopy(graph.scenario.pipeline["buffers"])
    bufs["ZSL_RING_BUF"] = {**bufs["ZSL_RING_BUF"], "count": 9}
    graph.scenario.pipeline = {**graph.scenario.pipeline, "buffers": bufs}
    assert _condition_hash(graph, opts, shim, {}) != before


def test_a_new_slot_container_does_not_change_the_fingerprint():
    from scenario_db.sim.measured_timing import baseline_fingerprint

    before = baseline_fingerprint(_graph())
    graph = _with_slot("post_proc", {"enc": {"service_ms": 10.0}})
    assert baseline_fingerprint(graph) == before



def test_a_huge_tile_count_fails_before_building_chunks():
    with pytest.raises(JobError, match="exceed 20000"):
        _one([_stage("a", nodes=["byrp"], chunk={"by": "tile", "tiles": 10**9})])


def test_a_same_instant_preview_release_goes_first():
    period = analyze_timing_budget(_graph(), TimingBudgetOptions(throughput_model="pipelined"))["period_ms"]
    out = _one([_stage("a", kind="fixed", nodes=["byrp"], work={"duration_ms": 12})],
               trigger={"kind": "event", "at_ms": round(period * 2, 6)})
    assert out["background"]["rt_wait_max_ms"] < 12 - 1e-6


def test_stripe_traffic_follows_the_output_width():
    graph = _graph(job={"id": "j", "background": "none", "stages": [
        _stage("a", nodes=["byrp"], size_ref="tst", writes=["y"],
               chunk={"by": "stripe", "max_line_px": 1000, "overlap_px": 64})],
        "buffers": {"y": {"format": "YUV420", "bitdepth": 8}}})
    graph.variant.size_overrides = {**(graph.variant.size_overrides or {}), "tst": "1000x1000"}
    one = _report(graph)["jobs"][0]["peak"]["bw_instant_mbs"]
    graph.variant.size_overrides["tst"] = "1001x1000"
    two = _report(graph)["jobs"][0]["peak"]["bw_instant_mbs"]
    assert two < one * 1.5                              # the 1 px stripe carries 1 px of output, not half


def test_a_tiled_transfer_keeps_its_declared_bytes():
    out = _one([_stage("store", kind="transfer", nodes=["post_proc"], chunk={"by": "tile", "tiles": 3},
                       work={"mb": 12, "mb_per_s": 1200})], background="none")
    assert out["stages"][0]["mb"] == pytest.approx(12.0)


def test_a_measured_time_with_setup_keeps_the_declared_power():
    job = deepcopy(JOB)
    job["stages"][3]["chunk"] = {"by": "frame", "setup_us": 2000}
    out = _report(_with_slot("post_proc", {"enc": {"service_ms": 10.0}}, job=job))["jobs"][0]
    enc = {s["id"]: s for s in out["stages"]}["enc"]
    assert enc["energy_mj"] == pytest.approx(400 * 10 / 1000.0)


def test_an_unresolved_mode_parameter_is_a_job_error():
    job = {"id": "j", "background": "none", "stages": [_stage("a", nodes=["byrp"], mode={"param": "no_such"})]}
    with pytest.raises(JobError, match="parameter 'no_such' resolves to None"):
        _report(_graph(job=job))


def test_a_job_buffer_takes_its_own_comp_ratio():
    graph = _graph(job={"id": "j", "background": "none", "stages": [
        _stage("a", nodes=["byrp"], size_ref="tst", writes=["y"])],
        "buffers": {"y": {"format": "Y", "bitdepth": 8, "compression": "COMP_BAYER_LOSSY", "comp_ratio": 0.25}}})
    graph.variant.size_overrides = {**(graph.variant.size_overrides or {}), "tst": "1000x1000"}
    assert _report(graph)["jobs"][0]["stages"][0]["mb"] == pytest.approx(0.25)


def test_a_session_ring_cannot_hand_out_more_frames_than_it_holds():
    graph = _graph(params={"zsl_frames": 9})
    bufs = deepcopy(graph.scenario.pipeline["buffers"])
    bufs["ZSL_RING_BUF"] = {**bufs["ZSL_RING_BUF"], "lifetime": "session", "count": 8}
    graph.scenario.pipeline = {**graph.scenario.pipeline, "buffers": bufs}
    with pytest.raises(JobError, match="reads 9 frames of ZSL_RING_BUF, which holds 8"):
        _report(graph)


def test_a_long_chain_is_reduced_without_ancestor_sets():
    n = 3000
    stages = [_stage(f"s{i}", kind="fixed", nodes=["post_proc"], work={"duration_ms": 0},
                     **({"after": [f"s{i - 1}"]} if i else {})) for i in range(n)]
    assert len(_one(stages, background="none")["stages"]) == n
