"""S-04 memory limits: opt-in serialisation, LLC per owner, case peak / footprint, judgement."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import arch_exploration as ax  # noqa: E402
from scenario_db.sim.models import DVFSTable  # noqa: E402

UHD30 = "cam-rec-r1-uhd30-vdis"


@pytest.fixture(scope="module")
def setup():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    tables = {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    return (lambda: graph_from_fixture(raw, UHD30, catalog)), tables


def spec(**constraints):
    return ax.ArchExplorationSpec.model_validate({"constraints": constraints, "axes": {"power_options": {"enabled": False}}})


def test_unset_limits_are_not_serialised():
    keys = set(ax.ArchExplorationSpec().model_dump()["constraints"])
    assert not keys & set(ax.MEMORY_LIMITS)
    assert set(ax.ArchExplorationSpec().model_dump(mode="json")["constraints"]) == keys
    assert ax.ExplorationConstraints(llc_capacity_mb=8).model_dump()["llc_capacity_mb"] == 8
    assert "peak_bw_limit_mbs" not in ax.ExplorationConstraints(llc_capacity_mb=8).model_dump()
    assert not ax.ExplorationConstraints().memory_on and ax.ExplorationConstraints(peak_bw_limit_mbs=1).memory_on


def test_llc_counts_each_owner_partition_once(setup):
    make, _ = setup
    graph = make()
    # PYRAMID_L0 / L1 (+ TNR history) share the 4 MB MTNR partition
    assert ax.llc_allocation_mb(graph) == 4.0


def slice_(**over):
    s = {
        "period_ms": 33.333,
        "ips": [{"node": "a", "stage": "rt", "dvfs_group": "CAM", "set_clock_mhz": 400.0, "hw_ms": 10.0},
                {"node": "b", "stage": "nrt", "dvfs_group": "CAM", "set_clock_mhz": 400.0, "hw_ms": 12.0},
                {"node": "c", "stage": "nrt", "dvfs_group": "MFC", "set_clock_mhz": 300.0, "hw_ms": 8.0}],
        "memory_basis": {"avg_by_ip": {"a": 500.0, "b": 300.0, "c": 300.0}, "peak_by_ip": {"a": 1000.0, "b": 600.0, "c": 600.0},
                         "write_mb_frame": 10.0, "llc_mb": 4.0},
        "domains": [{"domain": "CAM", "options": [{"level": 3, "speed_mhz": 400.0, "raise": False},
                                                  {"level": 2, "speed_mhz": 600.0, "raise": True}]}],
        "stages": {"rt": {"sw_ms": 0.0, "hw_ms": 10.0}, "nrt": {"sw_ms": 30.0, "hw_ms": 20.0}},
    }
    return s | over


BUFFERS = [{"buffer": "B1", "modes": [{"mode": "COMP_YUV_LOSSY", "delta_by_node": {"b": -100.0}, "delta_write_mbs": -60.0}]}]


def case(*comp):
    return {"compression": list(comp), "compression_modes": {c: "COMP_YUV_LOSSY" for c in comp}}


def test_case_peak_follows_the_buffers_own_dma_and_dvfs_raise():
    s = slice_()
    base = ax._case_memory(s, case(), {"levels": {"CAM": 3}}, BUFFERS)
    assert base["peak_stage_mbs"] == 1200.0 and base["peak_stage"] == "nrt"
    # 50 ms chain over a 33.3 ms period -> two frames in flight
    assert base["frames_held"] == 2 and base["dram_footprint_mb"] == 20.0 and base["llc_mb"] == 4.0
    # B1 compression removes 100 MB/s from b only (peak factor 2) and 60 MB/s of writes (2 MB per frame)
    comp = ax._case_memory(s, case("B1"), {"levels": {"CAM": 3}}, BUFFERS)
    assert comp["peak_stage_mbs"] == 1000.0 and comp["dram_footprint_mb"] == pytest.approx(16.0, abs=1e-3)
    # CAM one level up (400 -> 600 MHz): CAM IPs 1.5x faster -> peak x1.5, NRT HW 20 -> (8 + 8) ms -> 1 frame
    raised = ax._case_memory(s, case(), {"levels": {"CAM": 2}}, BUFFERS)
    assert raised["peak_stage_mbs"] == 1500.0 and raised["peak_stage"] == "rt"
    assert raised["frames_held"] == 2  # 30 + 16 = 46 ms is still more than one period
    short = slice_(stages={"nrt": {"sw_ms": 15.0, "hw_ms": 20.0}})
    # 15 + 20 = 35 ms -> 2 frames at the resolved level; 15 + (8 + 8) = 31 ms -> 1 frame with CAM raised
    assert ax._case_memory(short, case(), {"levels": {"CAM": 3}}, BUFFERS)["frames_held"] == 2
    assert ax._case_memory(short, case(), {"levels": {"CAM": 2}}, BUFFERS)["frames_held"] == 1
    # candidates priced without the per-DMA split cannot be judged
    assert ax._case_memory(s, case("B1"), {"levels": {}}, [{"buffer": "B1", "modes": [{"mode": "COMP_YUV_LOSSY"}]}]) is None
    assert ax._case_memory({**s, "memory_basis": None}, case(), {"levels": {}}, BUFFERS) is None


def test_case_reasons_name_the_limit():
    c = ax.ExplorationConstraints(peak_bw_limit_mbs=1000, dram_footprint_limit_mb=10, llc_capacity_mb=2)
    case = {"lossy": False, "total_mw": 1, "bw_mbs": 1,  # noqa: F811 - local case dict
            "memory": {"peak_stage_mbs": 1200.0, "peak_stage": "nrt", "dram_footprint_mb": 20.0, "frames_held": 2, "llc_mb": 4.0}}
    reasons = ax._case_reasons(case, c)
    assert [r.split(":")[0] for r in reasons] == ["BW 포화", "DRAM footprint 초과", "LLC 할당 초과"]
    assert ax._case_reasons(case, ax.ExplorationConstraints()) == []
    # a set limit without memory data never passes
    missing = ax._case_reasons({"lossy": False, "total_mw": 1, "bw_mbs": 1}, c)
    assert missing[0].startswith("메모리 한도 판정 불가")


def test_exploration_with_limits(setup):
    make, tables = setup
    plain = ax.explore_variant(make(), spec(), dvfs_tables=tables)
    loose = ax.explore_variant(make(), spec(peak_bw_limit_mbs=1e6, dram_footprint_limit_mb=1e6, llc_capacity_mb=64), dvfs_tables=tables)
    assert "memory" not in plain["recommended"] and loose["recommended"]["memory"]["llc_mb"] == 4.0
    # limits that every case meets do not change the choice
    assert loose["recommended"]["key"] == plain["recommended"]["key"] and loose["counts"] == plain["counts"]
    assert loose["objective_slice"]["memory_basis"]["llc_mb"] == 4.0 and "memory_basis" not in plain["objective_slice"]
    assert all("memory_basis" not in sl for sl in loose["slices"])
    tight = ax.explore_variant(make(), spec(llc_capacity_mb=2), dvfs_tables=tables)
    assert not tight["spec_ok"] and tight["spec_reasons"] == ["LLC 할당 초과: 4 MB > 2 MB"]
    peak = loose["recommended"]["memory"]["peak_stage_mbs"]
    capped = ax.explore_variant(make(), spec(peak_bw_limit_mbs=peak * 0.999), dvfs_tables=tables)
    assert capped["counts"]["eligible"] < plain["counts"]["eligible"]
    if capped["recommended"]:
        assert capped["recommended"]["memory"]["peak_stage_mbs"] <= peak * 0.999
    else:
        assert capped["spec_reasons"][0].startswith("BW 포화")


def test_analytic_peak_matches_the_resimulated_case(setup):
    make, tables = setup
    loose = ax.explore_variant(make(), spec(peak_bw_limit_mbs=1e6), dvfs_tables=tables)
    rec = loose["recommended"]
    assert rec["compression"]  # the recommended case compresses buffers: the per-DMA delta matters
    # just below the analytic peak of the recommended case: it must drop out, and the re-simulation agrees
    capped = ax.explore_variant(make(), spec(peak_bw_limit_mbs=rec["memory"]["peak_stage_mbs"] - 1), dvfs_tables=tables)
    assert capped["recommended"] is None or capped["recommended"]["key"] != rec["key"]
    if capped["recommended"]:
        assert capped["recommended"]["verified"]["constraints_pass"]


def test_rebuilt_and_verified_cases_carry_memory(setup):
    make, tables = setup
    v = ax.explore_variant(make(), spec(llc_capacity_mb=2), dvfs_tables=tables)
    rebuilt = ax.case_from_key(v, v["baseline"]["key"])
    assert rebuilt["memory"]["llc_mb"] == 4.0 and not rebuilt["eligible"]
    # a stored run without the basis (limits added later) cannot pass a memory limit
    old = {**v, "objective_slice": {k: x for k, x in v["objective_slice"].items() if k != "memory_basis"}}
    assert not ax.case_from_key(old, v["baseline"]["key"])["eligible"]
    ok = ax.explore_variant(make(), spec(llc_capacity_mb=8, peak_bw_limit_mbs=1e6, dram_footprint_limit_mb=1e6), dvfs_tables=tables)
    assert ok["recommended"]["verified"]["constraints_pass"]


def test_raised_dvfs_can_meet_a_footprint_limit_by_shortening_the_chain(setup):
    make, tables = setup
    s = ax.ArchExplorationSpec.model_validate({
        "constraints": {"dram_footprint_limit_mb": 100}, "objective": {"runtime_scale": 1.4},
        "axes": {"runtime_scales": [1.4], "compression": {"enabled": False}, "dvfs_headroom_levels": 2,
                 "power_options": {"enabled": False}},
        "timing": {"throughput_model": "pipelined"}})
    v = ax.explore_variant(make(), s, dvfs_tables=tables)
    if v["recommended"]:
        assert v["recommended"]["memory"]["dram_footprint_mb"] <= 100
        assert v["recommended"]["memory"]["frames_held"] == 1
