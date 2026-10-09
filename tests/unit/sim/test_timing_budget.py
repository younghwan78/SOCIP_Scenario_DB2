"""Stage timing budget (scenario_db.sim.timing_budget)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import timing_budget as tb  # noqa: E402
from scenario_db.sim.models import DVFSTable  # noqa: E402

DVFS_PATH = FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml"


@pytest.fixture(scope="module")
def graph_factory():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(
            id=d["id"],
            schema_version=d["schema_version"],
            category=d["category"],
            hierarchy=d["hierarchy"],
            capabilities=d["capabilities"],
            yaml_sha256="fixture",
        )
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    return lambda variant: graph_from_fixture(raw, variant, catalog)


@pytest.fixture(scope="module")
def dvfs():
    doc = yaml.safe_load(DVFS_PATH.read_text(encoding="utf-8"))
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


def _stage(report, sid):
    return next(s for s in report["stages"] if s["id"] == sid)


def test_stage_classification_and_budgets(graph_factory):
    r = tb.analyze_timing_budget(graph_factory("cam-rec-r1-uhd30-vdis"))
    period = r["period_ms"]
    rt, nrt, post, out = (_stage(r, s) for s in ("rt", "nrt", "post", "output"))
    assert {"csis", "mlsc"} <= set(rt["nodes"])
    assert (
        {"mtnr", "mcsc"} <= set(nrt["nodes"])
        and {"gdc_o"} <= set(post["nodes"])
        and {"mfc_enc", "dpu"} <= set(out["nodes"])
    )
    assert {i["task"] for i in nrt["sw_items"]} == {"post_crta", "pre_me_rta", "post_irta"}
    assert [i["task"] for i in post["sw_items"]] == ["eis"]
    # max statistic: 0.5 + 1.0 latency + 4.0 + 5.6 = 11.1 ms; EIS 6.0 ms
    assert nrt["sw_ms"] == pytest.approx(11.1)
    assert nrt["budget_ms"] == pytest.approx(period - 11.1, abs=1e-3)
    assert post["budget_ms"] == pytest.approx(period - 6.0, abs=1e-3)
    assert rt["budget_ms"] == pytest.approx(0.75 * period, abs=1e-3)
    # NRT HW fits its budget exactly (continuous clock, no DVFS)
    assert nrt["hw_ms"] == pytest.approx(nrt["budget_ms"], abs=0.01)
    assert r["intervals"]["ok"] is True
    assert r["verdict"]["status"] == "clock_up"


def test_rt_keeps_25_percent_rule(graph_factory):
    r = tb.analyze_timing_budget(graph_factory("cam-rec-r1-8k30-sdr"))
    rt = _stage(r, "rt")
    assert rt["hw_ms"] <= rt["budget_ms"] + 1e-6
    assert rt["margin"] == 0.25


def test_mean_statistic_lowers_nrt_clock(graph_factory):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    mx = tb.summarize(g, tb.TimingBudgetOptions(statistic="max"))
    mean = tb.summarize(g, tb.TimingBudgetOptions(statistic="mean"))
    assert mean["stages"]["nrt"]["sw_ms"] < mx["stages"]["nrt"]["sw_ms"]
    assert mean["nrt_clock_mhz"] < mx["nrt_clock_mhz"]


def test_eis_toggle_changes_post_stage_only(graph_factory):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    on = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(eis="on"))
    off = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(eis="off"))
    assert _stage(on, "post")["sw_ms"] == pytest.approx(6.0)
    assert _stage(off, "post")["sw_ms"] == 0.0
    assert _stage(on, "nrt")["sw_ms"] == _stage(off, "nrt")["sw_ms"]
    auto_sdr = tb.analyze_timing_budget(graph_factory("cam-rec-r1-uhd30-sdr"))
    assert auto_sdr["eis"]["on"] is False


def test_growth_raises_clock_monotonically(graph_factory):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    clocks = [
        tb.summarize(g, tb.TimingBudgetOptions(runtime_scale=s))["nrt_clock_mhz"]
        for s in (1.0, 1.2, 1.4)
    ]
    assert clocks[0] < clocks[1] < clocks[2]


def test_ip_overhead_is_added_to_stage_sw(graph_factory):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    base = tb.analyze_timing_budget(g)
    opts = tb.TimingBudgetOptions(
        ip_overhead={"mtnr": {"min_ms": 1.0, "mean_ms": 1.5, "max_ms": 2.0}}
    )
    with_ovh = tb.analyze_timing_budget(g, opts)
    assert _stage(with_ovh, "nrt")["sw_ms"] == pytest.approx(_stage(base, "nrt")["sw_ms"] + 2.0)
    assert _stage(with_ovh, "nrt")["overhead_ms"] == pytest.approx(2.0)


def test_parallel_sw_chains_do_not_add(graph_factory):
    r = tb.analyze_timing_budget(graph_factory("cam-rec-pip-uhd30"))
    nrt = _stage(r, "nrt")
    total = sum(i["runtime_ms"] + i["latency_ms"] for i in nrt["sw_items"])
    assert nrt["sw_ms"] < total  # front/rear chains run in parallel
    assert any(ip["shared_streams"] == 2 for ip in r["ips"])  # streams time-multiplexed on one IP
    assert r["intervals"]["ok"] is True


def test_mfc_dual_core_halves_clock_keeps_time(graph_factory):
    g = graph_factory("cam-rec-r1-uhd30-sdr")
    dual = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(mfc_dual="auto"))
    single = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(mfc_dual="off"))
    d = next(ip for ip in dual["ips"] if ip["node"] == "mfc_enc")
    s = next(ip for ip in single["ips"] if ip["node"] == "mfc_enc")
    assert d["cores"] == 2 and s["cores"] == 1
    assert d["required_clock_mhz"] == pytest.approx(s["required_clock_mhz"] / 2, rel=0.02)
    assert d["hw_ms"] == pytest.approx(s["hw_ms"], rel=0.01)
    assert tb.analyze_timing_budget(graph_factory("cam-rec-r1-fhd30-sdr"))["mfc_dual"] == {}


def test_dvfs_levels_are_reported(graph_factory, dvfs):
    r = tb.analyze_timing_budget(graph_factory("cam-rec-r1-uhd30-vdis"), dvfs_tables=dvfs)
    mtnr = next(ip for ip in r["ips"] if ip["node"] == "mtnr")
    assert mtnr["dvfs_level"] is not None and mtnr["set_clock_mhz"] >= mtnr["required_clock_mhz"]
    assert mtnr["voltage_mv"] > 0
    assert r["dvfs"]["applied"] is True
    # rule clock carries its own level; a group without a table is flagged instead of a level
    assert mtnr["rule_dvfs_level"] is not None and mtnr["dvfs_table"] is True
    for ip in r["ips"]:
        if not ip["dvfs_table"]:
            assert ip["dvfs_level"] is None


def test_power_and_bw_split(graph_factory):
    r = tb.analyze_timing_budget(graph_factory("cam-rec-r1-uhd30-vdis"))
    p, bw = r["power"], r["bw"]
    assert p["total_mw"] == pytest.approx(p["cpu_mw"] + p["hw_mw"] + p["bw_mw"], abs=0.05)
    assert sum(p["share_pct"].values()) == pytest.approx(100, abs=0.3)
    assert p["cpu_mw"] > 0 and p["hw_by_ip"]["byrp"] > 0
    assert bw["total_mbs"] == pytest.approx(bw["hw_mbs"] + bw["sw_mbs"], abs=0.2)
    assert bw["sw_mbs"] > 0  # writer / storage bitstream traffic


def test_high_fps_without_budget_fails_with_reason(graph_factory):
    r = tb.analyze_timing_budget(graph_factory("cam-rec-r1-fhd240"))
    assert r["verdict"]["status"] == "fail"
    assert any("NRT" in reason for reason in r["verdict"]["reasons"])


def test_whatif_grid_and_fleet_row(graph_factory):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    r = tb.analyze_timing_budget(
        g, tb.TimingBudgetOptions(include_whatif=True, whatif_scales=[1.0, 1.2])
    )
    assert len(r["whatif"]) == 2 * 2 * 2
    row = tb.fleet_row(r)
    assert row["clocks"]["nrt"]["set_mhz"] and row["intervals"]["ok"] in (True, False)


def test_analysis_is_read_only(graph_factory):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    before = (dict(g.variant.design_conditions or {}), repr(g.variant.node_configs))
    tb.analyze_timing_budget(g, tb.TimingBudgetOptions(runtime_scale=1.3, eis="off"))
    assert (dict(g.variant.design_conditions or {}), repr(g.variant.node_configs)) == before


def test_invalid_options_rejected(graph_factory):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    with pytest.raises(ValueError, match="unknown timeline task"):
        tb.analyze_timing_budget(
            g,
            tb.TimingBudgetOptions(ip_overhead={"nope": {"min_ms": 1, "mean_ms": 1, "max_ms": 1}}),
        )
    with pytest.raises(ValueError, match="not a SW task"):
        tb.analyze_timing_budget(g, tb.TimingBudgetOptions(task_adjustments={"mtnr": {"scale": 2}}))
    with pytest.raises(ValueError):
        tb.TimingStat(min_ms=3, mean_ms=1, max_ms=4)


def test_sample_dvfs_fixture_is_valid_and_labelled():
    from scenario_db.models.capability.hw import SocDvfsTable

    doc = yaml.safe_load(DVFS_PATH.read_text(encoding="utf-8"))
    table = SocDvfsTable.model_validate(doc)
    assert "SYNTHETIC" in table.source.note
    assert all(level.speed_mhz > 0 for dom in table.domains.values() for level in dom.levels)


def test_pipelined_throughput_only_adds_latency(graph_factory):
    g = graph_factory("cam-rec-r1-fhd120")
    stage = tb.analyze_timing_budget(g)
    pipe = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(throughput_model="pipelined"))
    nrt = _stage(pipe, "nrt")
    assert nrt["throughput"] == "pipelined"
    assert nrt["longest_sw_ms"] <= nrt["chain_ms"] + 1e-9
    # pipelined never needs a faster clock / more power than the conservative stage model
    assert pipe["power"]["total_mw"] <= stage["power"]["total_mw"] + 0.05
    if stage["verdict"]["status"] == "fail" and pipe["verdict"]["status"] != "fail":
        assert any("latency" in n for n in pipe["verdict"].get("notes", []))
    # 30 fps scenario without the long chain is unchanged
    g30 = graph_factory("cam-rec-r1-uhd30-vdis")
    a = tb.analyze_timing_budget(g30)
    b = tb.analyze_timing_budget(g30, tb.TimingBudgetOptions(throughput_model="pipelined"))
    assert a["intervals"]["ok"] == b["intervals"]["ok"]


def test_dvfs_level_whatif_rows(graph_factory, dvfs):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    out = tb.dvfs_level_whatif(g, tb.TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=dvfs, shifts=(-1, 1))
    assert out["throughput_model"] == "pipelined" and out["domains"]
    base = out["base"]
    assert set(base["slack_ms"]) == {"rt", "nrt", "post", "output"}
    for row in out["rows"]:
        if row.get("error"):
            continue
        assert row["delta_mw"] == pytest.approx(row["total_mw"] - base["total_mw"], abs=0.05)
        dom = next(d for d in out["domains"] if d["domain"] == row["domain"])
        assert (row["mhz"] > dom["mhz"]) == (row["shift"] > 0)
    up = [r for r in out["rows"] if r["shift"] > 0 and not r.get("error")]
    assert up and all(r["delta_mw"] >= -0.05 for r in up)  # a faster level never lowers power
    # domain filter
    only = tb.dvfs_level_whatif(g, tb.TimingBudgetOptions(), dvfs_tables=dvfs, shifts=(1,), domains=[out["domains"][0]["domain"]])
    assert {r["domain"] for r in only["rows"]} <= {out["domains"][0]["domain"]}


def test_pipelined_sw_on_one_cpu_resource_must_fit_the_period_together(graph_factory):
    """AC-05: two SW tasks on the same core cannot pass as independent threads (sum > period fails)."""
    g = graph_factory("cam-rec-r1-fhd120")
    free = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(throughput_model="pipelined"))
    shared = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(throughput_model="pipelined", shared_cpu=True))
    nrt_free, nrt_shared = _stage(free, "nrt"), _stage(shared, "nrt")
    period = shared["period_ms"]
    assert nrt_free["longest_sw_ms"] <= period and nrt_free["cpu_groups"] == []
    group = nrt_shared["cpu_groups"][0]
    assert group["load_ms"] == pytest.approx(sum(i["runtime_ms"] for i in nrt_shared["sw_items"] if i["kind"] == "sw"), abs=0.01)
    if group["load_ms"] > period:
        assert not nrt_shared["feasible"] and shared["verdict"]["status"] == "fail"
        assert any("같은 thread/core" in r for r in shared["verdict"]["reasons"])


def test_pipelined_single_ip_slower_than_the_period_still_fails(graph_factory, dvfs):
    """AC-04: buffering does not rescue a stage whose service time per frame exceeds the period."""
    g = graph_factory("cam-rec-r1-uhd60-sdr")
    out = tb.dvfs_level_whatif(g, tb.TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=dvfs, shifts=(-1,))
    slow = [r for r in out["rows"] if not r.get("error") and r["stage_hw_ms"]["nrt"] > out["period_ms"] * 1.001]
    assert slow
    for r in slow:
        assert r["verdict"] == "fail" and any("interval" in x for x in r["reasons"])


def test_dvfs_combos_boundaries_and_peak_bw(graph_factory, dvfs):
    """TIM-05: several domains together + boundary rows; TIM-08: faster clock keeps average BW, raises peak."""
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    out = tb.dvfs_level_whatif(g, tb.TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=dvfs,
                               shifts=(-9, 1), combos=[{"CAM": 1, "INTCAM": 1}, {"CAM": -9}])
    edge = [r for r in out["rows"] if r["shift"] == -9]
    assert edge and all(r.get("boundary") == "최저 OPP" and r["level"] is None for r in edge)
    combo, outside = out["combos"]
    assert outside.get("error") and outside["boundary"] == "경계"
    singles = {r["domain"]: r for r in out["rows"] if r["shift"] == 1 and not r.get("error")}
    if "CAM" in singles and "INTCAM" in singles and not combo.get("error"):
        # both faster: power at least each single step, average BW unchanged, peak not lower
        assert combo["delta_mw"] >= max(singles["CAM"]["delta_mw"], singles["INTCAM"]["delta_mw"]) - 0.05
        assert combo["delta_mbs"] == pytest.approx(0, abs=0.5)
        assert combo["delta_peak_mbs"] >= -0.5
    peak = out["base"]["peak_stage_mbs"]
    assert peak is not None and peak >= 0


def test_dvfs_combo_star_moves_every_domain(graph_factory, dvfs):
    """'*' preset = every DVFS domain of the variant shifted together."""
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    out = tb.dvfs_level_whatif(g, tb.TimingBudgetOptions(throughput_model="pipelined"), dvfs_tables=dvfs,
                               shifts=(1,), combos=[{"*": 1}])
    (row,) = out["combos"]
    assert set(row["combo"]) == {d["domain"] for d in out["domains"]}
    assert all(k == 1 for k in row["combo"].values())


def test_interval_stats_jitter_drops_warmup():
    """TIM-09: report-only statistics; a 2-period gap = one dropped frame; leading off-cadence gaps = warm-up."""
    st = tb._interval_stats([40.0, 33.3, 66.6, 33.3, 33.3], 33.3, 1e-3, 0)
    assert st["drops"] == 1 and st["warmup_observed"] == 1 and st["warmup_excluded"] == 0
    assert st["jitter_ms"] > 0 and st["p95_dev_ms"] == pytest.approx(33.3, abs=0.01)
    st2 = tb._interval_stats([40.0, 33.3, 33.3], 33.3, 1e-3, 1)
    assert st2["drops"] == 0 and st2["jitter_ms"] == pytest.approx(0) and st2["warmup_excluded"] == 1


def test_warmup_frames_only_relaxes_leading_intervals(graph_factory, dvfs):
    g = graph_factory("cam-rec-r1-uhd30-vdis")
    a = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(), dvfs_tables=dvfs)
    b = tb.analyze_timing_budget(g, tb.TimingBudgetOptions(warmup_frames=2), dvfs_tables=dvfs)
    assert a["intervals"]["video"]["values"] == b["intervals"]["video"]["values"]
    assert b["intervals"]["video"]["warmup_excluded"] == 2
    assert not (a["intervals"]["ok"] and not b["intervals"]["ok"])  # excluding intervals never turns ok into fail
