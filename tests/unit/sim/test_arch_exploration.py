"""Architecture exploration, change attribution and review report."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.reporting.arch_report import build_snapshot, html_sha256, render_html  # noqa: E402
from scenario_db.sim import arch_exploration as ax  # noqa: E402
from scenario_db.sim.models import DVFSTable  # noqa: E402
from scenario_db.sim.power_attribution import attribute  # noqa: E402

DVFS_PATH = FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml"
UHD30 = "cam-rec-r1-uhd30-vdis"


@pytest.fixture(scope="module")
def graph_factory():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    return lambda variant: graph_from_fixture(raw, variant, catalog)


@pytest.fixture(scope="module")
def dvfs():
    doc = yaml.safe_load(DVFS_PATH.read_text(encoding="utf-8"))
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


# The case-space / compression-math tests use every buffer with DMA traffic (pre-2026-10 behaviour):
# the default now explores only DMA whose endpoints declare compression (see test_declared_compression_only).
ALL_BUFFERS = ax.ArchExplorationSpec.model_validate({"axes": {"compression": {"require_declared": False}}})


@pytest.fixture(scope="module")
def uhd30(graph_factory, dvfs):
    return ax.explore_variant(graph_factory(UHD30), ALL_BUFFERS, dvfs_tables=dvfs)


def test_declared_compression_only(graph_factory):
    """Default axis: only buffers whose endpoints declare SBWC are explored (2600: MLSC -> MTNR L0/L1)."""
    from scenario_db.sim.models import SimulationRunConfig
    rows = {r["buffer"]: r for r in ax.compression_candidates(graph_factory(UHD30), ax.CompressionAxis(), SimulationRunConfig())}
    assert {b for b, r in rows.items() if r["selectable"]} == {"PYRAMID_L0", "PYRAMID_L1"}
    assert "not declared" in rows["MCSC_VIDEO"]["skip_reason"]           # gdc_o declares nothing
    assert "DMA port without" in rows["PYRAMID_L2"]["skip_reason"]       # L2 ports are COMP_OFF only
    relaxed = {r["buffer"]: r for r in ax.compression_candidates(graph_factory(UHD30), ax.CompressionAxis(require_declared=False),
                                                                 SimulationRunConfig())}
    assert relaxed["MCSC_VIDEO"]["selectable"]


def test_ip_mode_table(uhd30):
    modes = {m["node"]: m for m in uhd30["ip_modes"]}
    mtnr = modes["mtnr"]
    assert mtnr["mode"] == "Normal" and mtnr["unit_power_mw_mp"] == 1.0
    assert [(a["mode"], a["explorable"]) for a in mtnr["alternatives"]] == [("LowPower", True)]
    assert all(not a["explorable"] for a in modes["rgbp"]["alternatives"])  # tDMSC is not a substitute


def test_case_space_and_distribution(uhd30):
    c = uhd30["counts"]
    # 2 statistics x 3 growth scales, 5 buffers (port-level SBWC limits drop pyramid L2+ / TNR prev),
    # CAM/INT/INTCAM x {base, +1}
    assert (c["sw_slices"], c["compression_sets"], c["dvfs_sets"]) == (6, 32, 8)
    assert c["cases"] == 6 * 32 * 8
    d = uhd30["distribution"]["total_mw"]
    assert d["min"] <= d["p25"] <= d["median"] <= d["p75"] <= d["max"]
    # every case = CPU + HW + BW
    for case in [uhd30["recommended"], uhd30["baseline"], *uhd30["alternatives"]]:
        assert case["total_mw"] == pytest.approx(case["cpu_mw"] + case["hw_mw"] + case["bw_mw"], abs=0.02)


def test_recommended_is_min_power_and_verified_by_resimulation(uhd30):
    rec, base = uhd30["recommended"], uhd30["baseline"]
    assert rec["statistic"] == "max" and rec["runtime_scale"] == 1.0  # objective slice
    assert rec["total_mw"] < base["total_mw"]
    assert rec["dvfs_raise"] == 0  # faster levels never lower power
    assert all(a["total_mw"] >= rec["total_mw"] - 1e-6 for a in uhd30["alternatives"])
    v = rec["verified"]
    assert v["ok"] and abs(v["delta_pct"]) < 0.05  # analytic == re-simulated


def test_compression_deltas_are_linear_in_ratio(uhd30):
    rows = {b["buffer"]: b for b in uhd30["buffers"]}
    b = rows["MCSC_VIDEO"]
    assert b["mode"] == "COMP_YUV_LOSSY" and b["comp_ratio"] == 0.5
    # half of the uncompressed traffic of the buffer's ports disappears
    assert -b["delta_mbs"] == pytest.approx(0.5 * b["raw_mbs"], abs=0.01)
    assert not rows["RGBP_HIST"]["selectable"]  # no DMA traffic -> nothing to save
    explored = [r for r in uhd30["buffers"] if r["explored"]]
    assert len(explored) == 5 and all(r["selectable"] for r in explored)


def test_dvfs_headroom_raises_voltage_and_power(uhd30):
    cam = next(d for d in uhd30["domains"] if d["domain"] == "CAM")
    base, up = cam["options"]
    # RT clock follows the sensor read-out (241.5 MHz) -> CAM L6 266 MHz; headroom = next level up
    assert base["level"] == 6 and up["level"] == 5 and up["speed_mhz"] > base["speed_mhz"]
    # VDD_CAM is already held above L5 by the CSIS clock (MIPI ingress) -> raising CAM alone costs nothing
    assert up["voltage_mv"] > base["voltage_mv"] and up["delta_mw"] == 0
    intcam = next(d for d in uhd30["domains"] if d["domain"] == "INTCAM")
    assert intcam["options"][1]["voltage_mv"] > intcam["options"][0]["voltage_mv"] and intcam["options"][1]["delta_mw"] > 0
    spread = uhd30["axis_spread"]
    assert spread["dvfs_headroom"]["range"] == pytest.approx(sum(d["options"][-1]["delta_mw"] for d in uhd30["domains"]), abs=0.02)


def test_axis_constraints(graph_factory, dvfs):
    g = graph_factory(UHD30)
    no_lossy = ax.explore_variant(g, ax.ArchExplorationSpec(constraints={"allow_lossy": False}), dvfs_tables=dvfs)
    assert no_lossy["recommended"]["compression"] == []
    budget = ax.explore_variant(g, ax.ArchExplorationSpec(constraints={"power_budget_mw": 300}), dvfs_tables=dvfs)
    assert budget["recommended"] is None and not budget["spec_ok"]
    with pytest.raises(ValueError, match="exceeds"):
        ax.explore_variant(g, ax.ArchExplorationSpec(max_cases_per_variant=100), dvfs_tables=dvfs)


def test_high_fps_is_spec_fail_with_reason(graph_factory, dvfs):
    r = ax.explore_variant(graph_factory("cam-rec-r1-fhd240"), ax.ArchExplorationSpec(), dvfs_tables=dvfs)
    assert not r["spec_ok"] and r["recommended"] is None
    assert any("HW budget" in x for x in r["spec_reasons"])
    m = r["sw_margin"]
    assert m["worst"]["margin_pct"] < 0 and any("spec 미달" in x for x in m["recommendations"])


def test_sw_margin_definition(uhd30):
    m = uhd30["sw_margin"]
    nrt = next(s for s in m["stages"] if s["stage"] == "nrt")
    p = uhd30["period_ms"]
    assert nrt["slack_ms"] == pytest.approx(p - nrt["sw_ms"] - nrt["hw_ms"], abs=1e-3)
    assert nrt["bottleneck"] == "post_irta"
    assert m["growth_tolerance"] == 1.2


def test_find_case_and_payload(uhd30):
    case, rule = ax.find_case(uhd30, None)
    assert rule == "auto:min-power" and case["key"] == uhd30["recommended"]["key"]
    alt = uhd30["alternatives"][0]
    case, rule = ax.find_case(uhd30, alt["key"])
    assert rule == "user:rank-2"
    p = ax.prediction_payload(uhd30["objective_slice"], uhd30["recommended"], uhd30["buffers"])
    assert p["power"]["total_mw"] == pytest.approx(uhd30["recommended"]["total_mw"], abs=0.01)
    assert sum(ip["power_mw"] for ip in p["ips"]) == pytest.approx(p["power"]["hw_mw"], abs=0.05)


def _payload(summary, case):
    return ax.prediction_payload(summary["objective_slice"], case, summary["buffers"])


def test_attribution_is_exact(graph_factory, dvfs, uhd30):
    uhd60 = ax.explore_variant(graph_factory("cam-rec-r1-uhd60-sdr"), ALL_BUFFERS, dvfs_tables=dvfs)
    a = _payload(uhd30, uhd30["recommended"])
    b = _payload(uhd60, uhd60["recommended"])
    r = attribute(a, b)
    assert r["delta_mw"] == pytest.approx(b["power"]["total_mw"] - a["power"]["total_mw"], abs=1e-3)
    assert abs(r["residual_mw"]) < 0.01
    assert any(c["item"] == "fps" for c in r["context_changes"])
    # baseline -> recommended: only compression moves
    r2 = attribute(_payload(uhd30, uhd30["baseline"]), a)
    assert set(r2["by_category"]) == {"Compression"}
    assert r2["by_category"]["Compression"] == pytest.approx(r2["delta_mw"], abs=0.02)


def test_attribution_dvfs_voltage_factor(uhd30):
    raised = next(c for c in [*uhd30["alternatives"]] if c["dvfs_raise"]) if any(
        c["dvfs_raise"] for c in uhd30["alternatives"]) else None
    base = uhd30["recommended"]
    cam = next(d for d in uhd30["domains"] if d["domain"] == "INTCAM")   # CAM's rail is pinned by CSIS (no V change)
    case = dict(base) | {"dvfs": {**base["dvfs"], "INTCAM": cam["options"][1]["level"]}, "dvfs_raise": 1}
    case["hw_mw"] = base["hw_mw"] + cam["options"][1]["delta_mw"]
    case["total_mw"] = base["total_mw"] + cam["options"][1]["delta_mw"]
    r = attribute(_payload(uhd30, base), _payload(uhd30, case))
    assert set(r["by_category"]) == {"IP DVFS 전압"}
    assert r["delta_mw"] == pytest.approx(cam["options"][1]["delta_mw"], abs=0.01)
    assert abs(r["residual_mw"]) < 0.01
    assert raised is None or raised["dvfs_raise"] > 0


def test_report_snapshot_and_html(uhd30):
    run = {"id": "EXP-1", "title": "t", "scenario_type": "Camera Recording", "soc_ref": "soc-exynos2600",
           "project_ref": "proj", "dvfs_table_ref": "dvfs-exynos2600-sample-v0", "engine_rev": ax.ENGINE_REV,
           "spec": ax.ArchExplorationSpec().model_dump(mode="json"), "variants": [uhd30], "errors": [],
           "summary": {"variants": 1}}
    pred = {"id": "PRED-1", "selection_rule": "auto:min-power",
            "metrics": _payload(uhd30, uhd30["recommended"])}
    snap = build_snapshot(run, {(uhd30["scenario_id"], UHD30): pred}, {})
    assert snap["spec_summary"]["spec_ok"] == 1 and snap["overview"]["sample_dvfs"]
    assert snap["scenarios"][0]["power"]["total_mw"] == pytest.approx(uhd30["recommended"]["total_mw"], abs=0.01)
    assert snap["sw_margin_top5"][0]["variant_id"] == UHD30
    assert any(c["buffer"] == "MCSC_VIDEO" and c["selected"] == 1 for c in snap["compression"])
    html = render_html("Report", snap)
    assert html.count("<section") == 15 and "<svg" in html and "SAMPLE" in html
    assert snap["opinions"][0]["category"] == "fps30" and "분류별 검토 의견" in html
    assert html.index("결론") < html.index("개요") and "실측 대조" in html
    assert snap["conclusion"]["confidence"]["grade"] == "C"  # SAMPLE DVFS, no measurement
    assert snap["calibration"] == [] and snap["overview"]["model_limits"]
    row = snap["scenarios"][0]
    assert row["latency"]["video_ms"] and row["period_ms"] == pytest.approx(1000 / row["fps"], rel=1e-3)
    assert "Latency · 출력 간격" in html and "압축 단독 BW 절감" in html and "조합 전체 절감" in html
    block = snap["opinions"][0]
    assert len(block["basis"]) == len(block["opinions"]) and block["evidence"]["grade"] == "산출"
    assert "사내 DVFS table" in block["evidence"]["needed"]
    assert len(html_sha256(html)) == 64


def test_bw_split_ip_vs_cpu_dma(uhd30):
    for case in [uhd30["recommended"], uhd30["baseline"], *uhd30["alternatives"]]:
        assert case["bw_ip_mw"] + case["bw_cpu_mw"] == pytest.approx(case["bw_mw"], abs=0.02)
        assert case["bw_ip_mbs"] + case["bw_cpu_mbs"] == pytest.approx(case["bw_mbs"], abs=0.02)
    base = uhd30["baseline"]
    assert base["bw_cpu_mbs"] > 0  # mpeg_writer / storage_write DMA
    # compressing ISP buffers only changes IP BW
    rec = uhd30["recommended"]
    assert rec["bw_cpu_mw"] == pytest.approx(base["bw_cpu_mw"], abs=1e-6)
    assert rec["bw_ip_mw"] < base["bw_ip_mw"]
    for key in ("bw_ip_mw", "bw_cpu_mw", "bw_ip_mbs", "bw_cpu_mbs"):
        assert key in uhd30["distribution"]
    p = ax.prediction_payload(uhd30["objective_slice"], rec, uhd30["buffers"])
    assert p["power"]["bw_ip_mw"] + p["power"]["bw_cpu_mw"] == pytest.approx(p["power"]["bw_mw"], abs=0.01)


def test_attribution_splits_dma_traffic_ip_vs_cpu(graph_factory, dvfs, uhd30):
    uhd60 = ax.explore_variant(graph_factory("cam-rec-r1-uhd60-sdr"), ax.ArchExplorationSpec(), dvfs_tables=dvfs)
    a, b = _payload(uhd30, uhd30["baseline"]), _payload(uhd60, uhd60["baseline"])
    r = attribute(a, b)
    items = {f["item"] for f in r["factors"] if f["category"] == "BW traffic"}
    assert "IP BW" in items and abs(r["residual_mw"]) < 0.01
    # rev-1 payload (no split) -> single combined factor, no fake IP/CPU swap
    legacy = {k: v for k, v in a.items() if not k.startswith(("base_bw_ip", "base_bw_cpu"))}
    r2 = attribute(legacy, b)
    assert {f["item"] for f in r2["factors"] if f["category"] == "BW traffic"} <= {"uncompressed traffic"}


def test_report_keeps_selected_uncompressed_case_and_verification(uhd30):
    run = {"id": "r", "title": "r", "scenario_type": "camera", "variants": [uhd30], "spec": {}}
    pred = {"id": "p", "metrics": _payload(uhd30, uhd30["baseline"])}
    snap = build_snapshot(run, {(uhd30["scenario_id"], UHD30): pred}, {})
    assert snap["scenarios"][0]["compression"] == []
    assert snap["scenarios"][0]["verified"] is None
    assert not snap["scenarios"][0]["lossy"] and not snap["scenarios"][0]["assumed_ratio"]
    assert all(b["selected"] == 0 for b in snap["compression"])


def test_sw_overhead_is_subtracted_once(uhd30):
    from copy import deepcopy
    obj = deepcopy(uhd30["objective_slice"])
    obj["stages"]["nrt"]["overhead_ms"] = 2
    obj["stages"]["nrt"]["sw_ms"] += 2
    result = ax.sw_margin([obj], obj, ax.ExplorationObjective())
    row = next(s for s in result["stages"] if s["stage"] == "nrt")
    assert row["slack_ms"] == pytest.approx(obj["period_ms"] - row["sw_ms"] - row["hw_ms"], abs=0.001)


def test_failed_resimulation_cannot_report_spec_ok(graph_factory, dvfs, monkeypatch):
    monkeypatch.setattr(ax, "_verify", lambda *args: {"ok": False})
    spec = ax.ArchExplorationSpec(axes={"statistics": ["max"], "runtime_scales": [1], "compression": {"enabled": False}})
    result = ax.explore_variant(graph_factory(UHD30), spec, dvfs_tables=dvfs)
    assert not result["spec_ok"] and "verification" in result["spec_reasons"][0]


def test_supported_lossless_mode_survives_no_lossy_constraint(graph_factory, dvfs):
    spec = ax.ArchExplorationSpec(
        axes={"statistics": ["max"], "runtime_scales": [1], "compression": {
            "modes": ["lossy", "lossless"], "ratio_overrides": {"COMP_YUV_LOSSLESS": 0.75, "COMP_BAYER_LOSSLESS": 0.75}}},
        constraints={"allow_lossy": False},
    )
    result = ax.explore_variant(graph_factory(UHD30), spec, dvfs_tables=dvfs)
    assert result["recommended"]["compression"] and not result["recommended"]["lossy"]


def test_input_hash_changes_with_ip_model(graph_factory):
    from copy import deepcopy
    graph = deepcopy(graph_factory(UHD30))
    spec, config = ax.ArchExplorationSpec(), ax.SimulationRunConfig()
    before = ax.input_hash(graph, spec, config, {})
    ip = next(ip for ip in graph.ip_catalog.values() if (ip.capabilities.get("sim") or {}).get("modes"))
    mode = next(iter(ip.capabilities["sim"]["modes"].values()))
    mode["unit_power_mw_mp"] = float(mode.get("unit_power_mw_mp", 0)) + 100
    assert ax.input_hash(graph, spec, config, {}) != before


def test_sw_dma_uses_adapter_resolved_fps(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    transfer = SimpleNamespace(node_id="writer", port="read", port_type=SimpleNamespace(value="RDMA"))
    monkeypatch.setattr(ax, "build_simulation_inputs", lambda *a: SimpleNamespace(
        config=SimpleNamespace(fps=60), workloads=[], port_transfers=[transfer]))
    calc = MagicMock(return_value=SimpleNamespace(bw_mbs=10, bw_power_mw=1))
    monkeypatch.setattr(ax, "calc_port_bw", calc)
    ax._dma(None, ax.SimulationRunConfig())
    assert calc.call_args.kwargs["fps"] == 60


def test_v2_clock_term_is_used_by_the_analytic_dvfs_headroom(graph_factory, dvfs, uhd30):
    from scenario_db.models.capability.power_model import PowerModelParams
    from scenario_db.sim.models import SimulationRunConfig

    params = PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-exynos2600",
        "ip_model": "v2-vf", "ip_clock_power_fraction": 0.3,
    })
    config = SimulationRunConfig(power_model="v2-vf", power_params=params)
    v2 = ax.explore_variant(graph_factory(UHD30), ax.ArchExplorationSpec(), config=config, dvfs_tables=dvfs)
    assert v2["recommended"]["verified"]["ok"]
    cam_v1 = next(d for d in uhd30["domains"] if d["domain"] == "CAM")["options"][1]
    cam_v2 = next(d for d in v2["domains"] if d["domain"] == "CAM")["options"][1]
    assert cam_v2["delta_mw"] > cam_v1["delta_mw"]  # the faster level also costs clock power
    # the clock factor itself: 1 without a fraction/reference, linear in f above the reference
    ip = {"clock_power_fraction": 0.3, "ref_clock_mhz": 400.0}
    assert ax._clock_factor(ip, 400.0) == pytest.approx(1.0)
    assert ax._clock_factor(ip, 533.0) == pytest.approx(0.7 + 0.3 * 533.0 / 400.0)
    assert ax._clock_factor({"clock_power_fraction": 0.0, "ref_clock_mhz": 400.0}, 533.0) == 1.0


# ------------------------------------------------------------------- codex review 7472331 (P1)
def test_verify_reapplies_budget_to_resimulated_numbers(graph_factory, dvfs, uhd30):
    """Analytic 100 mW within budget but re-simulated 100.4 mW: model match, budget fail."""
    rec = dict(uhd30["recommended"])
    sim = rec["verified"]["sim_total_mw"]
    rec["total_mw"] = round(sim / 1.004, 3)  # analytic 0.4 % below the re-simulation (< 0.5 % tolerance)
    spec = ALL_BUFFERS.model_copy(update={"constraints": ax.ExplorationConstraints(
        power_budget_mw=rec["total_mw"], require_complete_power_for_budget=False)})
    v = ax._verify(graph_factory(UHD30), spec, ax.SimulationRunConfig(), dvfs, rec, uhd30["buffers"])
    assert v["power_match"] and v["bw_match"] and v["timing_pass"]
    assert not v["constraints_pass"] and not v["ok"]
    assert any("budget" in r for r in v["reasons"])


def test_verify_checks_bw_consistency(graph_factory, dvfs, uhd30):
    rec = dict(uhd30["recommended"])
    rec["bw_mbs"] = rec["bw_mbs"] * 0.9
    v = ax._verify(graph_factory(UHD30), ALL_BUFFERS, ax.SimulationRunConfig(), dvfs, rec, uhd30["buffers"])
    assert v["power_match"] and not v["bw_match"] and not v["ok"]


def test_zero_estimates_cannot_verify_nonzero_simulation(graph_factory, dvfs, uhd30):
    rec = dict(uhd30["recommended"]) | {"total_mw": 0.0, "bw_mbs": 0.0}
    result = ax._verify(graph_factory(UHD30), ALL_BUFFERS, ax.SimulationRunConfig(), dvfs, rec, uhd30["buffers"])
    assert result["sim_total_mw"] > 0 and result["sim_bw_mbs"] > 0
    assert not result["power_match"] and not result["bw_match"] and not result["ok"]
    assert result["delta_pct"] is None and result["bw_delta_pct"] is None


def test_partial_power_model_cannot_pass_a_power_budget(graph_factory, dvfs):
    g = graph_factory(UHD30)
    base = {"axes": {"statistics": ["max"], "runtime_scales": [1], "compression": {"enabled": False}}}
    free = ax.explore_variant(g, ax.ArchExplorationSpec.model_validate(base), dvfs_tables=dvfs)
    assert free["coverage"]["power_coverage"] == "partial" and free["coverage"]["zero_power_ips"]
    assert free["status"]["power_budget_status"] == "n/a" and free["spec_ok"]
    strict = ax.explore_variant(g, ax.ArchExplorationSpec.model_validate(
        base | {"constraints": {"power_budget_mw": 100_000}}), dvfs_tables=dvfs)
    assert strict["status"]["power_budget_status"] == "unknown" and not strict["spec_ok"]
    assert any("판정 불가" in r for r in strict["spec_reasons"])
    lenient = ax.explore_variant(g, ax.ArchExplorationSpec.model_validate(
        base | {"constraints": {"power_budget_mw": 100_000, "require_complete_power_for_budget": False}}), dvfs_tables=dvfs)
    assert lenient["spec_ok"] and lenient["status"]["power_budget_status"] == "unknown"
    assert lenient["status"]["timing_feasible"] and lenient["status"]["model_consistency_verified"]


def _c(key, mw, bw, lossy=False, comp=("b",), raise_=0, assumed=False):
    return {"key": key, "total_mw": mw, "bw_mbs": bw, "lossy": lossy, "assumed_ratio": assumed,
            "compression": list(comp), "dvfs_raise": raise_}


def test_pareto_keeps_equal_power_with_lower_bw_or_iq_risk():
    cases = [_c("a", 100, 500, lossy=True), _c("b", 100, 400, lossy=True), _c("c", 100.0, 600, comp=()),
             _c("d", 120, 700, comp=()), _c("e", 101, 400, lossy=True, raise_=1)]
    keys = [c["key"] for c in ax._pareto(cases)]
    assert keys == ["b", "c", "e"]  # a: dominated by b; d: dominated by c; e: more DVFS headroom
    # alternatives no longer collapse cases that share a rounded power but differ in BW
    assert len(ax._distinct([_c("x", 100, 500), _c("y", 100, 400)], 5)) == 2


def test_pareto_front_matches_a_brute_force_oracle():
    from random import Random

    random = Random(42)
    cases = [_c(str(i), random.randrange(20), random.randrange(20),
                lossy=bool(random.randrange(2)), comp=() if i % 4 == 0 else ("b",),
                raise_=random.randrange(5), assumed=bool(random.randrange(2))) for i in range(100)]
    def point(case):
        return case["total_mw"], case["bw_mbs"], ax._iq_risk(case), -case["dvfs_raise"]
    points = {point(case) for case in cases}
    expected = {p for p in points if not any(q != p and all(a <= b for a, b in zip(q, p, strict=True)) for q in points)}
    assert {point(case) for case in ax._pareto(cases)} == expected


def test_pareto_avoids_pairwise_work_when_all_candidates_survive(monkeypatch):
    cases = [_c(str(i), i, 1000 - i) for i in range(256)]
    calls = 0
    original = ax._iq_risk
    def counted(case):
        nonlocal calls
        calls += 1
        return original(case)
    monkeypatch.setattr(ax, "_iq_risk", counted)
    assert len(ax._pareto(cases)) == len(cases)
    assert calls <= 10 * len(cases)


def test_pareto_candidate_can_be_selected_for_promotion():
    candidate = _c("front-only", 100, 400)
    case, rule = ax.find_case({"recommended": _c("rec", 90, 500), "alternatives": [], "pareto": [candidate]}, "front-only")
    assert case == candidate and rule == "user:pareto-1"


def test_fixed_dvfs_growth_tolerance_is_not_the_reoptimised_one(uhd30):
    m = uhd30["sw_margin"]
    assert m["growth_tolerance_fixed"] is not None
    assert m["growth_tolerance_fixed"] <= m["growth_tolerance"]
    assert {"growth_tolerance", "growth_tolerance_fixed"} <= set(m["growth_tolerance_basis"])
    assert uhd30["pareto"] and all("iq_risk" in c for c in uhd30["pareto"])


def test_input_manifest_keeps_resolved_inputs_content_addressed(uhd30, graph_factory, dvfs):
    sections, blobs = uhd30["input_sections"], uhd30["_manifest_blobs"]
    assert {"pipeline", "variant_doc", "config"} <= set(sections) and any(k.startswith("dvfs:") for k in sections)
    assert any(k.startswith("ip:") for k in sections)
    assert blobs[sections["simulation_inputs"]] == ax.build_simulation_inputs(
        graph_factory(UHD30), ax.SimulationRunConfig()).model_dump(mode="json")
    assert all(sections[k] in blobs for k in sections)
    again, _ = ax.input_manifest(graph_factory(UHD30), ax.SimulationRunConfig(), dvfs)
    assert again == sections  # deterministic


def test_run_list_view_keeps_what_the_run_table_reads(uhd30):
    import json
    from scenario_db.api.services.arch_exploration import variant_summary
    full = {k: v for k, v in uhd30.items() if not k.startswith("_")} | {"scenario_id": "s", "variant_id": "v"}
    row = variant_summary(full)
    assert row["detail"] is False and row["recommended"] == full["recommended"] and row["distribution"] == full["distribution"]
    assert row["sw_margin"]["worst"] == full["sw_margin"]["worst"]
    assert row["sw_margin"]["growth_tolerance_fixed"] == full["sw_margin"]["growth_tolerance_fixed"]
    assert {"slices", "buffers", "objective_slice", "pareto"}.isdisjoint(row)
    assert len(json.dumps(row)) * 10 < len(json.dumps(full, default=str))  # an order of magnitude smaller
