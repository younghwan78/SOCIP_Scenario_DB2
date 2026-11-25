"""R-5 / M-6: sim.workload (WorkloadSpec) and frame-pacing-v1."""

import math

import pytest
from pydantic import ValidationError

from scenario_db.sim.frame_pacing import gpu_sampler, simulate
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from scenario_db.sim.workload_spec import FrameTime, WorkloadSpec, workload_spec
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

GAME = "uc-game-play-e2600"
OPTS = TimingBudgetOptions(throughput_model="pipelined")
CPU = [(2.0, 4.0, 8.0)]


def _sim(**kw):
    base = dict(period_ms=1000 / 120, vsync_ms=1000 / 120, cpu_ranges=CPU, gpu_median_ms=6.61,
                frame_time=FrameTime(p99_x=1.45, p95_x=1.25), depth=3, present_mode="fifo")
    return simulate(**{**base, **kw})


@pytest.mark.parametrize("raw", [{"frame_time": {"p99_x": 0.9}}, {"frame_time": {"p50_ms": 9, "p99_ms": 8}},
                                 {"frame_time": {"histogram": []}}, {"frame_time": {"histogram": [[0, 1]]}},
                                 {"present_mode": "immediate"}, {"unknown": 1}])
def test_a_workload_is_checked(raw):
    with pytest.raises(ValidationError):
        WorkloadSpec.model_validate(raw)


def test_a_label_string_is_not_a_workload():
    assert workload_spec({"workload": "composition"}) is None and workload_spec({}) is None
    assert workload_spec({"workload": {"frame_time": {"p99_x": 1.2}}}).frame_time.p99_x == 1.2


def test_the_p99_ratio_sets_the_sigma_and_reports_the_p95_gap():
    _, basis = gpu_sampler(6.61, FrameTime(p99_x=1.45, p95_x=1.25))
    assert basis["sigma"] == pytest.approx(math.log(1.45) / 2.326, abs=1e-5)
    assert basis["p95_x_implied"] == pytest.approx(math.exp(1.645 * math.log(1.45) / 2.326), abs=1e-4)
    assert basis["p95_x_gap"] == pytest.approx(basis["p95_x_implied"] - 1.25, abs=1e-4)


def test_measured_values_win_over_the_ratio():
    assert gpu_sampler(6.61, FrameTime(histogram=[[7, 1], [9, 1]], p99_x=1.4))[1]["distribution"] == "histogram"
    _, basis = gpu_sampler(6.61, FrameTime(p50_ms=7.0, p99_ms=10.0, p99_x=1.1))
    assert basis["from"] == "measured percentiles" and basis["median_ms"] == 7.0
    assert gpu_sampler(6.61, None)[1]["distribution"] == "fixed"


def test_the_run_is_reproducible():
    assert _sim() == _sim()
    assert _sim(seed=8) != _sim()


def test_a_fast_chain_keeps_the_target_with_no_jank():
    out = _sim(gpu_median_ms=3.0, frame_time=None, cpu_ranges=[(2.0, 2.0, 2.0)])
    assert out["achieved_fps"] == pytest.approx(120.0, abs=0.01) and out["jank_pct"] == 0 and out["drops"] == 0


def test_45_fps_on_120_hz_is_the_normal_3_3_2_pattern():
    out = _sim(period_ms=1000 / 45, gpu_median_ms=5.0, frame_time=None, cpu_ranges=[(2.0, 2.0, 2.0)])
    assert out["jank_pct"] == 0 and out["achieved_fps"] == pytest.approx(45.0, rel=0.01)
    assert out["expected_interval_ms"] == pytest.approx(3 * 1000 / 120, abs=1e-3)


def test_a_slow_gpu_misses_the_target():
    out = _sim(gpu_median_ms=12.0, frame_time=None)
    assert out["achieved_fps"] < 100 and out["jank_pct"] > 30      # 12 ms GPU: every other present waits a vsync


def test_a_deeper_queue_absorbs_tails_and_adds_latency():
    tail = FrameTime(p99_x=1.8)
    two, three = _sim(depth=2, frame_time=tail, gpu_median_ms=7.0), _sim(depth=3, frame_time=tail, gpu_median_ms=7.0)
    assert three["jank_pct"] <= two["jank_pct"]
    assert three["latency_ms"]["p50"] >= two["latency_ms"]["p50"]


def test_mailbox_drops_instead_of_queueing():
    fifo = _sim(period_ms=4.0, gpu_median_ms=3.0, frame_time=None, cpu_ranges=[(1.0, 1.0, 1.0)])
    box = _sim(period_ms=4.0, gpu_median_ms=3.0, frame_time=None, cpu_ranges=[(1.0, 1.0, 1.0)], present_mode="mailbox")
    assert box["drops"] > 0 and fifo["drops"] == 0
    assert box["latency_ms"]["p50"] < fifo["latency_ms"]["p50"]


def test_one_buffer_is_refused():
    with pytest.raises(ValueError, match="depth >= 2"):
        _sim(depth=1)


def test_the_game_reports_its_pacing():
    r = analyze_timing_budget(_exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr"), OPTS)
    p = r["pacing"]
    assert p["model"] == "frame-pacing-v1" and p["node"] == "gpu" and p["depth"] == 3 and p["refresh_hz"] == 120
    assert p["gpu_ms"]["median_computed"] == pytest.approx(4.0 / 605 * 1000, abs=1e-3)   # 4 Mcycle / 605 MHz
    assert p["cpu_tasks"] == ["cpu"] and p["status"] == "ok" and r["verdict"]["status"] == "ok"
    assert not any("frame_pacing" in n for n in r["verdict"]["notes"])       # now evaluated


def test_a_sustained_shortfall_fails_the_verdict():
    graph = _exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr")
    gpu = graph.variant.node_configs["gpu"]
    gpu["sim"]["workload"] = {**gpu["sim"]["workload"], "frame_time": {"p99_x": 3.0}}
    r = analyze_timing_budget(graph, OPTS)
    assert r["pacing"]["status"] == "fail" and r["verdict"]["status"] == "fail"
    assert any(x.startswith("frame pacing:") for x in r["verdict"]["reasons"])


def test_scenarios_without_a_workload_have_no_pacing():
    for uc, v in (("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr"), ("uc-game-streaming-e2600", "game-stream-fhd60-hevc")):
        assert "pacing" not in analyze_timing_budget(_exynos2600_generated_graph(uc, v), OPTS)


def _graph(variant="game-fhd-120fps-sdr"):
    return _exynos2600_generated_graph(GAME, variant)


def test_the_depth_follows_the_active_gpu_output():
    graph = _graph("game-fhd-60fps-npu-ai")          # gpu -> npu is active, gpu -> dpu is switched off
    pipe = dict(graph.scenario.pipeline)
    pipe["buffers"] = {**pipe["buffers"], "GPU_NPU_BUF": {**pipe["buffers"]["GPU_NPU_BUF"], "count": 2}}
    graph.scenario.pipeline = pipe
    assert analyze_timing_budget(graph, OPTS)["pacing"]["depth"] == 2


def test_the_cpu_upstream_comes_from_the_plan_edges():
    from scenario_db.sim.frame_pacing import _ancestors

    edges = [{"from": "cpu", "to": "dpu"}, {"from": "gpu", "to": "dpu"}]
    assert _ancestors(edges, "gpu", {"cpu", "gpu", "dpu"}) == []
    assert _ancestors([{"from": "cpu", "to": "gpu"}], "gpu", {"cpu", "gpu"}) == ["cpu"]


def test_only_a_gpu_with_frame_time_opts_in():
    graph = _graph()
    gpu = graph.variant.node_configs["gpu"]
    gpu["sim"]["workload"] = {"title_class": "x", "legacy_key": 1}        # no frame_time: not parsed, no pacing
    assert "pacing" not in analyze_timing_budget(graph, OPTS)
    graph = _graph("game-fhd-60fps-npu-ai")
    graph.variant.node_configs["gpu"]["sim"]["workload"] = "render"
    graph.variant.node_configs["npu"]["sim"]["workload"] = {"frame_time": {"p99_x": 1.2}}
    assert "pacing" not in analyze_timing_budget(graph, OPTS)            # an NPU is not the GPU


def test_a_measured_p50_alone_is_the_gpu_time():
    sample, basis = gpu_sampler(6.61, FrameTime(p50_ms=12.0))
    assert basis["from"] == "measured p50" and sample(None) == 12.0
    out = _sim(frame_time=FrameTime(p50_ms=12.0))
    assert out["gpu_ms"]["p50"] == 12.0 and out["achieved_fps"] < 100


def test_zero_gpu_work_is_reported_not_raised():
    graph = _graph()
    pipe = dict(graph.scenario.pipeline)
    pipe["nodes"] = [{**n, "domain_load": {**n["domain_load"], "mcycles_per_frame": 0}} if n["id"] == "gpu" else n
                     for n in pipe["nodes"]]
    graph.scenario.pipeline = pipe
    r = analyze_timing_budget(graph, OPTS)
    assert r["pacing"]["status"] == "no_gpu_time" and any("positive GPU work" in n for n in r["verdict"]["notes"])


def test_very_slow_frames_are_a_shortfall_not_a_deadlock():
    out = _sim(frame_time=FrameTime(histogram=[[30000.0, 1.0]]), frames=40, warmup=5)
    assert out["achieved_fps"] < 1 and out["jank_pct"] == 100
