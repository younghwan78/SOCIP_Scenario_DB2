from scenario_db.comparison.calibration import measured_split
from scenario_db.comparison.rail_attribution import (
    clock_compare,
    ip_power_by_vdd,
    latency_compare,
    node_vdd_map,
    rail_attribution,
    sw_task_compare,
)

VDD = {
    "B5_6S1_VDD_CAM_L": {"power_mw": 100.0},
    "B4S4_VDD_INT_L": {"power_mw": 90.0},
    "B5S4_VDDMIF_AP_L": {"power_mw": 30.0},
    "SRB1S4_VDD2H_MEM_AP_L": {"power_mw": 40.0},
    "B2S2_VDD_CPUCL1_MID_LF0_L": {"power_mw": 70.0},
    "B5_6S3_VDD_CPUCL0_DSU_L": {"power_mw": 30.0},
    "B6S2_VDD_SRAM_L": {"power_mw": 20.0},
}
IPS = [
    {"node": "byrp", "dvfs_group": "CAM", "power_mw": 60.0, "set_clock_mhz": 133.0, "dvfs_level": 7},
    {"node": "csis", "dvfs_group": "CSIS", "power_mw": 2.0, "set_clock_mhz": 342.0},
    {"node": "mtnr", "dvfs_group": "INTCAM", "power_mw": 10.0, "set_clock_mhz": 133.0},
    {"node": "gdc", "dvfs_group": "INT", "power_mw": 5.0, "set_clock_mhz": 100.0},
]
DVFS = [{"node_id": "byrp", "dvfs_group": "CAM", "vdd": "VDD_CAM"}, {"node_id": "csis", "dvfs_group": "CSIS", "vdd": "VDD_CAM"},
        {"node_id": "mtnr", "dvfs_group": "INTCAM", "vdd": "VDD_INTCAM"}, {"node_id": "gdc", "dvfs_group": "INT", "vdd": "VDD_INT"}]


def test_rail_attribution_groups_ip_by_vdd_and_sorts_by_error():
    nodes, groups = node_vdd_map(DVFS)
    by_vdd = ip_power_by_vdd(IPS, nodes, groups)
    assert by_vdd["VDD_CAM"]["mw"] == 62.0 and by_vdd["VDD_INTCAM"]["mw"] == 10.0
    rails = measured_split(VDD)["rails"]
    out = rail_attribution(rails, {"cpu": 110.0, "ip": 77.0, "bw": 150.0}, by_vdd, {"t1": 110.0})
    g = {x["key"]: x for x in out["groups"]}
    # INTCAM has no measured rail → joins the VDD_INT group
    assert g["ip:VDD_INT"]["pred_mw"] == 15.0 and g["ip:VDD_INT"]["meas_mw"] == 90.0
    assert any("VDD_INTCAM" in n for n in out["notes"])
    assert g["bw"]["meas_mw"] == 70.0 and g["bw"]["delta_mw"] == 80.0
    assert g["other"]["pred_mw"] == 0.0
    assert [x["key"] for x in out["groups"]][:2] == ["bw", "ip:VDD_INT"]
    assert round(sum(x["share_pct"] for x in out["groups"]), 0) == 100
    assert {c["cluster"] for c in out["cpu_clusters"]} == {"CPUCL1_MID_LF0", "CPUCL0_DSU"}


def test_rail_attribution_without_node_split_keeps_ip_total():
    out = rail_attribution(measured_split(VDD)["rails"], {"cpu": 1.0, "ip": 50.0, "bw": 1.0}, None, None)
    assert any(g["key"] == "ip:(전체)" and g["pred_mw"] == 50.0 for g in out["groups"])


def test_sw_task_compare_uses_statistic_and_p95():
    meas = [{"task": "a", "mean_ms": 3.0, "p95_ms": 4.5}, {"task": "b", "mean_ms": 1.0, "p95_ms": 1.2}, {"task": "c", "p95_ms": 30.0}]
    assumed = {"a": {"min_ms": 2, "mean_ms": 3, "max_ms": 4}, "b": {"mean_ms": 1, "max_ms": 2}, "c": {"max_ms": 20}, "d": {"max_ms": 1}}
    out = sw_task_compare(meas, assumed, statistic="max", budget_ms=25.0)
    rows = {r["task"]: r for r in out["rows"]}
    assert rows["a"]["assumed_ms"] == 4 and rows["a"]["delta_ms"] == 0.5 and rows["a"]["status"] == "under_assumed"
    assert rows["b"]["status"] == "within"
    assert rows["c"]["status"] == "over_budget"
    assert rows["d"]["status"] == "assumed_only"
    assert out["optimistic"] == 2 and out["worst"]["task"] == "c"


def test_latency_and_clock_compare():
    assert latency_compare({"video_ms": 44.0}, {"p95": 40.0, "mean": 31.0})["delta_pct"] == 10.0
    assert latency_compare(None, None) is None
    view = {"domains": [{"domain": "CAM", "class_label": "CAM", "active": None, "wall": {"mean_mhz": 140.0, "p50_mhz": 133.0}}]}
    rows = {r["group"]: r for r in clock_compare(IPS, view)}
    assert rows["CAM"]["meas_mhz"] == 140.0 and rows["CAM"]["delta_pct"] == -5.0
    assert rows["INT"]["meas_mhz"] is None
