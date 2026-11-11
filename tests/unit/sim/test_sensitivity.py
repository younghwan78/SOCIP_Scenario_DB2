"""S-03 assumed-input sensitivity: linear tornado rows, break-even, timing headroom, report ranking."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.reporting.review_summary import assumption_ranking  # noqa: E402
from scenario_db.sim.arch_exploration import ArchExplorationSpec, explore_variant  # noqa: E402
from scenario_db.sim.models import DVFSTable  # noqa: E402
from scenario_db.sim.sensitivity import assumed_sensitivity, top_inputs, variant_sensitivity  # noqa: E402


def payload(**over):
    base = {
        "power": {"total_mw": 1000.0, "cpu_mw": 300.0, "hw_mw": 400.0, "bw_mw": 300.0},
        "bw_mbs": 3000.0, "runtime_scale": 1.0,
        "ips": [{"node": "isp", "power_mw": 250.0, "dvfs_group": "CAM", "voltage_mv": 700.0, "set_clock_mhz": 400.0},
                {"node": "mfc", "power_mw": 150.0, "dvfs_group": "MFC", "voltage_mv": 700.0, "set_clock_mhz": 300.0},
                {"node": "idle", "power_mw": 0.0, "dvfs_group": "CAM", "voltage_mv": 700.0, "set_clock_mhz": 400.0}],
        "buffers": [{"buffer": "B1", "raw_mbs": 1000.0, "compressed": True, "mode": "COMP_YUV_LOSSY", "comp_ratio": 0.5},
                    {"buffer": "B2", "raw_mbs": 500.0, "compressed": False, "comp_ratio": 1.0}],
        "assumed_by_ip": {"gpu": 80.0},
        "stages": {"nrt": {"sw_items": [{"kind": "sw", "source": "assumed"}, {"kind": "sw", "source": "measured"},
                                        {"kind": "ip_overhead", "source": "ip_overhead"}]}},
    }
    return base | over


def rows_by_key(res):
    return {r["key"]: r for r in res["rows"]}


def test_linear_rows_for_every_assumed_input():
    ratio = [{"buffer": "B1", "mode": "COMP_YUV_LOSSY", "ratio": 0.5, "source": "assumed", "slope_mw": 100.0}]
    res = assumed_sensitivity(payload(), sample_dvfs=True, ratio_rows=ratio)
    rows = rows_by_key(res)
    assert rows["ip:isp"]["delta_high_mw"] == 50.0 and rows["ip:isp"]["delta_low_mw"] == -50.0
    assert "ip:idle" not in rows  # 0 mW IPs have nothing to move
    assert rows["bw:coeff"]["swing_mw"] == 120.0
    # B1: 0.5 x 100 mW per unit ratio = 50 mW on its own ports; ±20 % -> ±10 mW; B2 is not compressed
    assert rows["ratio:B1"]["delta_high_mw"] == 10.0 and rows["ratio:B1"]["source"] == "ratio assumed"
    assert "ratio:B2" not in rows
    assert rows["load:gpu"]["delta_high_mw"] == 16.0
    assert rows["sw:runtime"]["label"] == "SW timing (가정 1/2 task)" and rows["sw:runtime"]["delta_high_mw"] == 60.0
    # SAMPLE voltage ±5 %: power x (1.05² - 1) / (0.95² - 1)
    assert rows["vdd:CAM"]["delta_high_mw"] == pytest.approx(250 * 0.1025, abs=1e-3)
    assert rows["vdd:CAM"]["delta_low_mw"] == pytest.approx(-250 * 0.0975, abs=1e-3)
    assert [r["swing_mw"] for r in res["rows"]] == sorted((r["swing_mw"] for r in res["rows"]), reverse=True)
    assert "vdd:CAM" not in rows_by_key(assumed_sensitivity(payload()))


def test_break_even_and_limit_crossing():
    res = assumed_sensitivity(payload(), limits={"power budget": 1040.0})
    rows = rows_by_key(res)
    # 40 mW of room: BW (300 mW) crosses within ±20 %, ISP (±50 mW) crosses too, MFC (±30 mW) does not
    assert rows["bw:coeff"]["crosses"] == ["power budget"] and rows["bw:coeff"]["break_even_pct"]["power budget"] == pytest.approx(13.3, abs=0.1)
    assert rows["ip:isp"]["crosses"] == ["power budget"]
    assert rows["ip:mfc"]["crosses"] == [] and rows["ip:mfc"]["break_even_pct"]["power budget"] == pytest.approx(26.7, abs=0.1)
    # already over the limit: an input crosses back when its low end drops below
    over = rows_by_key(assumed_sensitivity(payload(), limits={"power budget": 980.0}))
    assert over["ip:mfc"]["crosses"] == ["power budget"] and over["ip:mfc"]["break_even_pct"]["power budget"] < 0


def test_sw_timing_headroom():
    rows = rows_by_key(assumed_sensitivity(payload(), sw_growth_tolerance=1.1, sw_growth_tested_max=1.5))
    assert rows["sw:runtime"]["timing"] == {"growth_tolerance": 1.1, "break_even_pct": 10.0, "at_least": False, "fails_at_high": True}
    rows = rows_by_key(assumed_sensitivity(payload(), sw_growth_tolerance=1.2, sw_growth_tested_max=1.2))
    assert rows["sw:runtime"]["timing"]["at_least"] and not rows["sw:runtime"]["timing"]["fails_at_high"]


def test_top_inputs_keep_the_worst_case_per_input():
    a = assumed_sensitivity(payload())
    b = assumed_sensitivity(payload(power={"total_mw": 2000.0, "cpu_mw": 900.0, "hw_mw": 400.0, "bw_mw": 700.0}),
                            limits={"power budget": 2100.0})
    tops = top_inputs([a, b], 3)
    assert [t["key"] for t in tops] == ["sw:runtime", "bw:coeff", "ip:isp"]
    assert tops[0]["swing_mw"] == 360.0 and tops[0]["count"] == 2 and tops[0]["crosses_any"]


@pytest.fixture(scope="module")
def explored():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    tables = {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    spec = ArchExplorationSpec.model_validate({"axes": {"power_options": {"enabled": False}}})
    summary = explore_variant(graph_from_fixture(raw, "cam-rec-r1-uhd30-vdis", catalog), spec, dvfs_tables=tables)
    return json.loads(json.dumps(summary, default=str))  # as stored in the run JSONB


def test_stored_variant_sensitivity(explored):
    res = variant_sensitivity(explored, sample_dvfs=True)
    rows = rows_by_key(res)
    assert res["total_mw"] == pytest.approx(explored["recommended"]["total_mw"], abs=1e-3)
    assert {"sw:runtime", "bw:coeff"} <= set(rows) and any(k.startswith("vdd:") for k in rows)
    assert rows["sw:runtime"]["timing"]["growth_tolerance"] == explored["sw_margin"]["growth_tolerance"]
    # the IP rows add up to the case's IP core power
    ip = sum(r["component_mw"] for k, r in rows.items() if k.startswith("ip:"))
    assert ip == pytest.approx(sum(i["power_mw"] for i in explored["objective_slice"]["ips"] if i["power_mw"]), rel=1e-6)
    assert variant_sensitivity({"objective_slice": {}}) is None


def test_report_ranks_the_top_assumptions(explored):
    sens = variant_sensitivity(explored, sample_dvfs=True)
    html = assumption_ranking({"scenarios": [{"sensitivity": sens}, {"sensitivity": None}]})
    assert "결론에 영향이 큰 가정 상위 5" in html and html.count("<li>") == 5
    assert "SW timing" in html and "±20%" in html
    assert assumption_ranking({"scenarios": [{}]}) == ""


def test_unit_power_moves_only_the_dynamic_part_and_voltage_follows_the_engine_law():
    from scenario_db.sim.arch_exploration import _ip_power_at

    ip = {"node": "nr", "power_mw": 50.0, "leakage_power_mw": 40.0, "dvfs_group": "CAM", "voltage_mv": 700.0,
          "set_clock_mhz": 400.0}
    rows = rows_by_key(assumed_sensitivity(payload(ips=[ip]), sample_dvfs=True))
    assert rows["ip:nr"]["delta_high_mw"] == 2.0 and rows["ip:nr"]["component_mw"] == 10.0
    assert rows["vdd:CAM"]["delta_high_mw"] == pytest.approx(_ip_power_at(ip, 735.0, 400.0) - 50.0, abs=1e-3)
    assert rows["vdd:CAM"]["delta_high_mw"] > 50 * 0.1025  # leakage grows faster than V²


def test_profile_cpu_reads_the_growth_slices():
    slices = {1.0: 300.0, 1.2: 420.0}
    rows = rows_by_key(assumed_sensitivity(payload(), sw_profile_slices=slices))
    assert rows["sw:runtime"]["delta_high_mw"] == 120.0 and rows["sw:runtime"]["delta_low_mw"] == 0.0
    assert "증가 방향만" in rows["sw:runtime"]["note"]
    res = assumed_sensitivity(payload(), sw_profile_slices={1.0: 300.0, 1.1: 330.0})
    assert "sw:runtime" not in rows_by_key(res) and "growth slice 없음" in res["notes"][0]


def test_ratio_rows_use_each_buffers_own_ports():
    from scenario_db.sim.sensitivity import _ratio_rows

    buffers = [
        {"buffer": "A", "base_compression": None, "modes": [{"mode": "COMP_YUV_LOSSY", "comp_ratio": 0.5, "delta_mw": -20.0,
                                                             "ratio_source": "assumed"}]},
        # ships lossless (0.7) and the case keeps it: OFF would cost 6 mW more
        {"buffer": "B", "base_compression": "COMP_YUV_LOSSLESS", "base_comp_ratio": 0.7,
         "current_saving": {"saving_mw": 6.0, "comp_ratio": 0.7}, "modes": []},
        # ships lossless (0.7), the case moves it to lossy (0.5): -4 mW for -0.2 ratio
        {"buffer": "C", "base_compression": "COMP_YUV_LOSSLESS", "base_comp_ratio": 0.7,
         "modes": [{"mode": "COMP_YUV_LOSSY", "comp_ratio": 0.5, "delta_mw": -4.0, "ratio_source": "typical"}]},
        {"buffer": "D", "base_compression": None, "modes": []},
    ]
    rows = {r["buffer"]: r for r in _ratio_rows(buffers, {"A": "COMP_YUV_LOSSY", "C": "COMP_YUV_LOSSY"})}
    assert set(rows) == {"A", "B", "C"}
    assert rows["A"]["slope_mw"] == 40.0 and rows["B"]["slope_mw"] == pytest.approx(20.0)
    assert rows["C"]["slope_mw"] == pytest.approx(20.0) and rows["C"]["source"] == "typical"


def test_fixed_dvfs_tolerance_only_for_the_recommended_case(explored):
    rows = rows_by_key(variant_sensitivity(explored))
    assert rows["sw:runtime"]["timing"]["growth_tolerance"] == explored["sw_margin"]["growth_tolerance_fixed"]
    other = dict(explored["baseline"])
    from scenario_db.sim.arch_exploration import prediction_payload

    chosen = prediction_payload(explored["objective_slice"], other, explored["buffers"])
    if sorted(other["compression"]) != sorted(explored["recommended"]["compression"]) or other["dvfs"] != explored["recommended"]["dvfs"]:
        assert "timing" not in rows_by_key(variant_sensitivity(explored, chosen))["sw:runtime"]


def test_already_compressed_buffers_are_in_the_baseline(explored):
    without_rec = {**explored, "recommended": None}
    rows = rows_by_key(variant_sensitivity(without_rec))
    shipped = [b["buffer"] for b in explored["buffers"] if b.get("base_compression")]
    assert shipped and all(f"ratio:{b}" in rows for b in shipped)
    # the fixture's lossless SBWC is priced at ratio 1.0: only the lower ratio moves (never above raw)
    r = rows[f"ratio:{shipped[0]}"]
    assert r["delta_high_mw"] == 0.0 and r["delta_low_mw"] < 0 and r["source"] == "ratio scenario (현재 압축)"


def test_report_rows_use_their_own_runs_dvfs_table(explored):
    from scenario_db.sim.sensitivity import is_sample_dvfs

    assert is_sample_dvfs("dvfs-exynos2600-sample-v0") and not is_sample_dvfs("dvfs-exynos2600-silicon") and not is_sample_dvfs(None)
    measured = rows_by_key(variant_sensitivity(explored, sample_dvfs=False))
    assert not any(k.startswith("vdd:") for k in measured)
