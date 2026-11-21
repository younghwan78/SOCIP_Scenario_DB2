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


def test_every_capture_variant_has_exactly_one_shot(jobs):
    for vid, (v, rows) in jobs.items():
        assert len(rows) == 1, vid
        full = (v.get("design_conditions") or {}).get("capture_readout") == "full_remosaic"
        assert rows[0]["id"] == ("still_shot_200m" if full else "still_shot"), vid
        assert rows[0]["milestones"]["thumbnail"] < rows[0]["milestones"]["saved"], vid


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

    assert thumb("cam-cap-r1-sf") < thumb("cam-cap-r1-mf") < thumb("cam-cap-r1-night")
    assert thumb("cam-cap-r1-remosaic-sf") < thumb("cam-cap-r1-remosaic-mf")
    assert {s["id"] for s in jobs["cam-cap-r1-ai-remosaic"][1][0]["stages"]} >= {"readout", "ai"}


def test_a_shot_leaves_the_steady_preview_unchanged(tables):
    graph = _exynos2600_generated_graph(UC, "cam-cap-r1-sf")
    with_job = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)
    graph.scenario.pipeline = {k: v for k, v in graph.scenario.pipeline.items() if k != "jobs"}
    plain = analyze_timing_budget(graph, TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=tables)
    assert {k: v for k, v in with_job.items() if k != "jobs"} == plain
