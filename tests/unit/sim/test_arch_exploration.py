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
    raw = read(FIXTURE / "02_definition" / "uc-camera-recording.yaml")
    return lambda variant: graph_from_fixture(raw, variant, catalog)


@pytest.fixture(scope="module")
def dvfs():
    doc = yaml.safe_load(DVFS_PATH.read_text(encoding="utf-8"))
    return {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


@pytest.fixture(scope="module")
def uhd30(graph_factory, dvfs):
    return ax.explore_variant(graph_factory(UHD30), ax.ArchExplorationSpec(), dvfs_tables=dvfs)


def test_case_space_and_distribution(uhd30):
    c = uhd30["counts"]
    # 2 statistics x 3 growth scales, 8 buffers, CAM/INT/INTCAM x {base, +1}
    assert (c["sw_slices"], c["compression_sets"], c["dvfs_sets"]) == (6, 256, 8)
    assert c["cases"] == 6 * 256 * 8
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
    assert len(explored) == 8 and all(r["selectable"] for r in explored)


def test_dvfs_headroom_raises_voltage_and_power(uhd30):
    cam = next(d for d in uhd30["domains"] if d["domain"] == "CAM")
    base, up = cam["options"]
    assert base["level"] == 4 and up["level"] == 3 and up["speed_mhz"] > base["speed_mhz"]
    assert up["voltage_mv"] > base["voltage_mv"] and up["delta_mw"] > 0
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
    uhd60 = ax.explore_variant(graph_factory("cam-rec-r1-uhd60-sdr"), ax.ArchExplorationSpec(), dvfs_tables=dvfs)
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
    case = dict(base) | {"dvfs": {**base["dvfs"], "CAM": 3}, "dvfs_raise": 1}
    cam = next(d for d in uhd30["domains"] if d["domain"] == "CAM")
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
    snap = build_snapshot(run, {UHD30: pred}, {})
    assert snap["spec_summary"]["spec_ok"] == 1 and snap["overview"]["sample_dvfs"]
    assert snap["scenarios"][0]["power"]["total_mw"] == pytest.approx(uhd30["recommended"]["total_mw"], abs=0.01)
    assert snap["sw_margin_top5"][0]["variant_id"] == UHD30
    assert any(c["buffer"] == "MCSC_VIDEO" and c["selected"] == 1 for c in snap["compression"])
    html = render_html("Report", snap)
    assert html.count("<section") == 10 and "<svg" in html and "SAMPLE" in html
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
