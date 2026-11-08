"""Power by component (IP groups) and the sustained AP + mem current rule of the review report."""
from copy import deepcopy

from scenario_db.reporting.arch_report import render_html
from scenario_db.reporting.power_groups import OTHER, component_table, components, group_of, heatmap_block, ranking_block
from scenario_db.reporting.review_snapshot import sustained_view
from scenario_db.reporting.risk_rules import _sustained_risks
from scenario_db.reporting.sustained_section import sustained_block

from tests.unit.reporting.test_review_report import snapshot


def test_group_rules_prefixes_and_policy_overrides():
    assert [group_of(n) for n in ("byrp", "front_mcsc", "mfc_enc", "apv_enc", "dpu", "gpu", "npu", "csis", "abox")] == [
        "ISP", "ISP", "Codec", "Codec", "DPU", "GPU", "NPU", "ISP", OTHER]
    assert group_of("abox", {"abox": "기타 IP", "vpu*": "Codec"}) == OTHER
    assert group_of("vpu_core", {"vpu*": "Codec"}) == "Codec"
    assert group_of("dpu", {"dpu": "ISP"}) == "ISP"  # a project mapping wins over the built-in rule


def row(vid, total, cpu, bw, ips, assumed=None, ok=True):
    return {"scenario_id": "uc", "variant_id": vid, "spec_ok": ok,
            "power": {"total_mw": total, "cpu_mw": cpu, "bw_mw": bw, "hw_mw": sum(ips.values()) + sum((assumed or {}).values())},
            "ip_mw": ips, "assumed_mw": assumed or {}}


def power_snap():
    return {"review_context": {"policy": {"ip_groups": {"abox": "기타 IP"}}},
            "scenarios": [row("cam-rec-a", 1000, 300, 400, {"byrp": 200, "mfc_enc": 50, "dpu": 10}, {"gpu": 40}),
                          row("cam-rec-b", 800, 100, 500, {"byrp": 150, "apv_enc": 40, "abox": 10}),
                          row("cam-rec-c", 600, 50, 300, {"mcsc": 240, "dpu": 10}),
                          row("cam-rec-fail", 2000, 900, 900, {"byrp": 200}, ok=False)]}


def test_components_split_ip_power_and_leave_missing_groups_none():
    c = components(power_snap()["scenarios"][0])
    assert c == {"CPU": 300, "BW": 400, "ISP": 200.0, "Codec": 50.0, "DPU": 10.0, "GPU": 40.0, "NPU": None, OTHER: None}
    ct = component_table(power_snap())
    assert [t["variant_id"] for t in ct["rows"]] == ["cam-rec-a", "cam-rec-b", "cam-rec-c"]  # spec-ok rows only
    assert ct["present"]["NPU"] is False and ct["present"]["GPU"] is True
    assert ct["rank"]["BW"][("uc", "cam-rec-b")] == 1 and ct["rank"]["ISP"][("uc", "cam-rec-c")] == 1
    assert ct["other_nodes"] == ["abox"]
    assert ct["rows"][0]["assumed"] == ["GPU"]


def test_ranking_and_heatmap_render_without_mutating_the_snapshot():
    snap = power_snap()
    before = deepcopy(snap)
    html = ranking_block(snap) + heatmap_block(snap)
    assert snap == before
    assert "요소별 순위" in html and "미입력: NPU" in html and "0 mW가 아님" in html
    assert "기타 IP로 분류된 node" in html and "abox" in html
    assert "가정 부하 포함" in html and "cam-rec-fail" not in html and ">fail<" not in html
    legacy = {"scenarios": [{k: v for k, v in r.items() if k not in ("ip_mw", "assumed_mw")} for r in snap["scenarios"]]}
    assert "재생성하면" in ranking_block(legacy) and heatmap_block(legacy) == ""


def ctx(limit=1200, base=0.0, rows=((2877.0, "cam-rec-apv"), (3700.0, "cam-rec-watch"), (4500.0, "cam-rec-hot"))):
    return {"policy": {"sustained_current": {"limit_ma": limit, "watch_ratio": 0.85, "base_mw": base}},
            "battery": {"vbat": 4.0, "pmic_efficiency": 0.85},
            "rows": [{"scenario_id": "uc", "variant_id": v, "total_mw": mw} for mw, v in rows]}


def test_sustained_view_converts_to_battery_current_and_classifies():
    plan = {"ask_pct": 9.3, "need_mw": -420, "saving_mw": -300, "achieved": False, "picked": ["lossy"]}
    items = [{"scenario_id": "uc", "variant_id": "cam-rec-hot", "source": "sustained", "current_mw": 4500, "plans": [plan],
              "approved_plans": [plan | {"saving_mw": -100}]},
             {"scenario_id": "uc", "variant_id": "cam-rec-apv", "source": "watch", "plans": [{"ask_pct": 10}]}]
    sv = sustained_view(ctx(), items)
    assert sv["limit_mw"] == 4080.0 and sv["watch_ma"] == 1020.0
    assert [(r["variant_id"], r["status"]) for r in sv["rows"]] == [
        ("cam-rec-hot", "over"), ("cam-rec-watch", "watch"), ("cam-rec-apv", "ok")]
    hot = sv["rows"][0]
    assert hot["ma"] == 1323.5 and hot["need_mw"] == 420.0 and hot["plan"] == plan
    assert sv["rows"][2]["plan"] is None  # a watch-list plan is not a sustained-current plan
    # base_mw (AP power outside the scenario model) is added before converting
    assert sustained_view(ctx(base=500), [])["rows"][1]["status"] == "over"
    assert sustained_view({"policy": {}}, []) is None


def test_sustained_risks_section_and_scorecard():
    snap = snapshot()
    sv = sustained_view(ctx(), [])
    snap["sustained"] = sv
    snap["criteria"]["sustained"] = {"limit_ma": 1200, "total": 3, "over": ["cam-rec-hot"], "watch": ["cam-rec-watch"]}
    risks = _sustained_risks(snap)
    assert [(r["key"], r["severity"]) for r in risks] == [("sustained_over", "high"), ("sustained_watch", "medium")]
    assert "1200 mA 초과 1건" in risks[0]["title"] and "1324 mA" in risks[0]["detail"]
    block = sustained_block(snap)
    assert "AP + mem" in block and "초과 — 절감 검토" in block and "절감 조합 미계산" in block
    html = render_html("Review", snap)
    assert "③ 지속 전류 ≤ 1200 mA" in html and "2 / 3" in html and "③ 발열 대응 여지" not in html
    none = snapshot()
    assert "sustained_current 미설정" in render_html("Review", none) and "③ 발열 대응 여지" in render_html("Review", none)
