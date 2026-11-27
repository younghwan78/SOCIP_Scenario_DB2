"""R-3c: the E2600 capture scenario declares its shot as event jobs (assumed values, knobs.yaml params).

C-2: the steady session is the 12M preview; a 12M shot reprocesses ZSL frames, and a 200M shot reads the sensor
once in full_remosaic through a seamless mode change (the preview drops frames meanwhile).
"""

import pytest
import yaml

from scenario_db.sim.models import DVFSTable
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

ROOT = "db_Exynos2600_SM-S947B"
UC = "uc-cam-capture-e2600"


@pytest.fixture(scope="module")
def tables():
    with open(f"{ROOT}/00_hw/dvfs-exynos2600-sample-v0.yaml", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


@pytest.fixture(scope="module")
def jobs(tables):
    with open(f"{ROOT}/02_definition/{UC}.yaml", encoding="utf-8") as fh:
        variants = yaml.safe_load(fh)["variants"]
    out = {}
    for v in variants:
        report = analyze_timing_budget(_exynos2600_generated_graph(UC, v["id"]),
                                       TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)
        out[v["id"]] = (v, report["jobs"])
    return out


SHOT = {None: "still_shot", "binning_2x2": "still_shot_50m", "full_remosaic": "still_shot_200m"}


def test_every_capture_variant_has_exactly_one_shot(jobs):
    for vid, (v, rows) in jobs.items():
        dc = v.get("design_conditions") or {}
        assert len(rows) == 1, vid
        assert rows[0]["id"] == SHOT[dc.get("capture_readout")], vid
        if dc.get("output_format") == "RAW_BAYER_16":          # DNG: no ISP thumbnail
            assert rows[0]["milestones"]["thumbnail"] is None and rows[0]["milestones"]["saved"] > 0, vid
        else:
            assert rows[0]["milestones"]["thumbnail"] < rows[0]["milestones"]["saved"], vid


def test_the_post_stage_reads_the_merged_frame(jobs):
    def post(vid):
        return {s["id"]: s for s in jobs[vid][1][0]["stages"]}["post"]["mb"]

    assert post("cam-cap-r1-mf-flash") == pytest.approx(post("cam-cap-r1-sf"))          # 12M: read + write
    assert post("cam-cap-r1-remosaic-mf") == pytest.approx(post("cam-cap-r1-remosaic-sf"))
    assert post("cam-cap-r1-ai-remosaic") == pytest.approx(post("cam-cap-r1-remosaic-sf"))


def test_shot_acquisition_follows_the_capture_type(jobs):
    def thumb(vid):
        return jobs[vid][1][0]["milestones"]["thumbnail"]

    # non-ZSL waits for 4 new frames after the shutter (reprocessing overlaps the wait); the flash MF variant
    # reprocesses ZSL frames at once
    assert thumb("cam-cap-r1-mf") > 4 * 33.3 > thumb("cam-cap-r1-mf-flash")
    high = {s["id"]: s for s in jobs["cam-cap-r1-mf-high-res"][1][0]["stages"]}
    assert high["readout"]["kind"] == "sensor" and high["readout"]["chunks"] == 1
    raw = {s["id"] for s in jobs["cam-cap-r1-high-res-raw"][1][0]["stages"]}
    assert raw == {"raw_proc", "store"}
    assert {s["id"] for s in jobs["cam-cap-r1-remosaic-pro"][1][0]["stages"]} == \
        {s["id"] for s in jobs["cam-cap-r1-remosaic-sf"][1][0]["stages"]}             # pro SF: a single frame


def test_a_200m_shot_is_a_seamless_mode_change_readout(jobs):
    shot = jobs["cam-cap-r1-remosaic-sf"][1][0]
    readout = {s["id"]: s for s in shot["stages"]}["readout"]
    assert readout["kind"] == "sensor"
    # one full_remosaic frame at the catalog 10 fps plus the mode change in / out (33.3 ms each, assumed)
    assert readout["service_ms"] == pytest.approx(100.0 + 2 * 33.3, abs=0.1)
    assert shot["background"]["dropped_frames"] > 0          # the preview pauses while the sensor is reserved
    assert jobs["cam-cap-r1-sf"][1][0]["background"]["dropped_frames"] == 0   # ZSL: no sensor stage


def test_shot_latency_follows_the_frame_count(jobs):
    def thumb(vid):
        return jobs[vid][1][0]["milestones"]["thumbnail"]

    assert thumb("cam-cap-r1-sf") < thumb("cam-cap-r1-mf-flash") < thumb("cam-cap-r1-night")   # 1 / 4 / 8 ZSL
    assert thumb("cam-cap-r1-remosaic-sf") < thumb("cam-cap-r1-remosaic-mf")
    assert {s["id"] for s in jobs["cam-cap-r1-ai-remosaic"][1][0]["stages"]} >= {"readout", "ai"}


def test_a_shot_leaves_the_steady_preview_unchanged(tables):
    graph = _exynos2600_generated_graph(UC, "cam-cap-r1-sf")
    with_job = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)
    graph.scenario.pipeline = {k: v for k, v in graph.scenario.pipeline.items() if k != "jobs"}
    plain = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)
    # the job KPIs (M-10) are judged on the job results only
    assert with_job["verdict"].pop("kpis")["status"] == "no_target" and with_job.pop("kpis")
    assert {k: v for k, v in with_job.items() if k != "jobs"} == plain


def test_merged_frame_writes_land_in_a_real_interval(jobs):
    for vid in ("cam-cap-r1-mf-flash", "cam-cap-r1-mf-high-res", "cam-cap-r1-remosaic-mf"):
        st = {s["id"]: s for s in jobs[vid][1][0]["stages"]}["merge_out"]
        assert st["kind"] == "transfer" and st["service_ms"] > 0 and st["mb"] > 0, vid


def test_the_zsl_ring_is_in_the_shot_footprint(jobs):
    ring = 8 * 4000 * 3000 * 10 / 8 / 1e6 * 0.5      # 8 x 12M Bayer 10-bit; lossless Bayer ratio (mean) <= 1
    for vid in ("cam-cap-r1-sf", "cam-cap-r1-night"):
        assert jobs[vid][1][0]["peak"]["footprint_mb"] > ring, vid


def test_the_stored_jpeg_and_the_jpeg_buffer_are_one_size(tables):
    graph = _exynos2600_generated_graph(UC, "cam-cap-r1-sf")
    graph.variant.design_conditions = {**graph.variant.design_conditions, "file_mb": 12}
    shot = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)["jobs"][0]
    store = {s["id"]: s for s in shot["stages"]}["store"]
    assert store["mb"] == pytest.approx(12.0) and store["service_ms"] == pytest.approx(12 / 1200 * 1000, rel=1e-3)


def test_the_zsl_ring_fill_is_steady_traffic():
    from copy import deepcopy

    graph = _exynos2600_generated_graph(UC, "cam-cap-r1-sf")
    with_fill = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), jobs=False)
    pipeline = deepcopy(graph.scenario.pipeline)
    pipeline["buffers"]["ZSL_RING_BUF"].pop("dma")
    graph.scenario.pipeline = pipeline
    without = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), jobs=False)
    assert with_fill["bw"]["total_mbs"] > without["bw"]["total_mbs"]


def test_a_raw_shot_stores_the_declared_file_size(tables):
    graph = _exynos2600_generated_graph(UC, "cam-cap-r1-high-res-raw")
    graph.variant.design_conditions = {**graph.variant.design_conditions, "file_mb": 12}
    shot = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)["jobs"][0]
    store = {s["id"]: s for s in shot["stages"]}["store"]
    assert store["mb"] == pytest.approx(12.0) and store["service_ms"] == pytest.approx(10.0, rel=1e-3)
