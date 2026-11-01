"""RPT-11 previous-report comparison and the tiered render (RPT-08..12)."""
from scenario_db.reporting.report_diff import report_diff
from scenario_db.reporting.review_sections import _gx, dumbbell, previous_block


def snap(power, criteria, basis, register, cpu=None):
    return {"scenarios": [{"variant_id": v, "power": {"total_mw": mw}} for v, mw in power.items()],
            "criteria": criteria, "basis": basis, "risk_register": register, "cpu": cpu or [],
            "conclusion": {"confidence": {"grade": "B"}}}


def crit(fps_ok, over):
    return {"fps": {"ok": fps_ok, "total": 3}, "power": {"ok": 1, "similar": 0, "over": over, "missing": [], "tolerance_pct": 3},
            "thermal": {"items": []}}


def test_report_diff_lists_risk_power_criteria_and_basis_changes():
    prev = snap({"a": 100.0, "b": 200.0, "gone": 50.0}, crit(3, 0), {"throughput_model": "stage", "engine_rev": "e1"},
                [{"key": "k1", "label": "R-01", "title": "old", "trend": "new"}],
                cpu=[{"variant_id": "a", "summary": {"tolerance": 1.3}}])
    cur = snap({"a": 100.4, "b": 260.0, "new": 10.0}, crit(2, 1), {"throughput_model": "pipelined", "engine_rev": "e1"},
               [{"key": "k1", "label": "R-01", "title": "old", "trend": "resolve_candidate"},
                {"key": "k2", "label": "R-02", "title": "fresh", "trend": "new"}],
               cpu=[{"variant_id": "a", "summary": {"tolerance": 1.1}}])
    d = report_diff(prev, cur, {"id": "RPT-prev", "generated_at": "2026-10-17T10:00"})
    assert d["risks"]["new"] == ["R-02 fresh"] and d["risks"]["resolved"] == ["R-01 old"]
    # lineage not frozen in these snapshots: whether the model changed is unknown, not "same"
    assert d["power"]["changed"] == [{"variant_id": "b", "prev_mw": 200.0, "cur_mw": 260.0, "delta_mw": 60.0, "delta_pct": 30.0,
                                      "model_changed": None}]
    assert d["power"]["added"] == ["new"] and d["power"]["removed"] == ["gone"]
    assert {c["item"] for c in d["criteria"]} == {"fps_ok", "power_over"}
    assert d["basis"] == [{"item": "판정 기준", "prev": "stage", "cur": "pipelined"}]
    assert d["cpu"] == [{"variant_id": "a", "prev": 1.3, "cur": 1.1}]
    html = previous_block(d)
    assert "신규 risk 1" in html and "해소 후보 1" in html and "+60.0" in html and "pipelined" in html and "×1.1" in html


def test_diff_names_a_model_only_change():
    """A re-registration with another power model moves power with no design change: the diff says so."""
    v1 = {"power_model": "v1-vfps", "bw_power_model": "builtin", "bw_coefficient": 80.0}
    v2 = {"power_model": "v2-vf", "power_model_version": "1.2", "bw_power_model": "mif-linear", "power_params_ref": "pmp-x@2",
          "power_params_hash": "abc", "clock_basis": "calculated"}
    prev, cur = snap({}, crit(2, 0), {"model_lineages": ["v1"]}, []), snap({}, crit(2, 0), {"model_lineages": ["v2"]}, [])
    prev["scenarios"] = [{"scenario_id": "s", "variant_id": "a", "power": {"total_mw": 200}, "model_lineage": v1},
                         {"scenario_id": "s", "variant_id": "b", "power": {"total_mw": 100}, "model_lineage": v2}]
    cur["scenarios"] = [{"scenario_id": "s", "variant_id": "a", "power": {"total_mw": 120}, "model_lineage": v2},
                        {"scenario_id": "s", "variant_id": "b", "power": {"total_mw": 110}, "model_lineage": dict(v2)}]
    d = report_diff(prev, cur, {})
    flags = {r["variant_id"]: r["model_changed"] for r in d["power"]["changed"]}
    assert flags == {"a": True, "b": False} and d["power"]["model_changed"] == 1
    assert {"item": "계산 모델", "prev": ["v1"], "cur": ["v2"]} in d["basis"]
    html = previous_block(d)
    assert "계산 모델 · engine 변경" in html and "설계 변화로 읽지 말 것" in html and "['v1']" not in html
    # same lineage, CPU power switched from the flat term to a measured profile: still a model change
    prev["scenarios"][1]["cpu_basis"], cur["scenarios"][1]["cpu_basis"] = "flat", "profile"
    assert {r["variant_id"]: r["model_changed"] for r in report_diff(prev, cur, {})["power"]["changed"]}["b"] is True
    # same model, another engine revision: the numbers moved without a design change too
    cur["scenarios"][1]["cpu_basis"] = "flat"
    prev["scenarios"][1]["engine_rev"], cur["scenarios"][1]["engine_rev"] = "arch-exploration/14", "arch-exploration/15"
    assert {r["variant_id"]: r["model_changed"] for r in report_diff(prev, cur, {})["power"]["changed"]}["b"] is True
    cur["scenarios"][1]["engine_rev"] = "arch-exploration/14"
    assert {r["variant_id"]: r["model_changed"] for r in report_diff(prev, cur, {})["power"]["changed"]}["b"] is False


def test_dumbbell_shows_reference_source_and_ma():
    ctx = {"battery": {"vbat": 4.0, "pmic_efficiency": 0.85},
           "rows": [{"variant_id": "cam-rec-a", "total_mw": 340.0, "ma": 100.0,
                     "reference": {"reference_mw": 300.0, "delta_pct": 13.3, "status": "over", "source": "measurement"}},
                    {"variant_id": "cam-rec-b", "total_mw": 100.0, "reference": None}]}
    h = dumbbell(ctx, 5)
    assert "a <tspan" in h and "[실측]" in h and "100 mA" in h and "+13.3%" in h and "허용 +5%" in h
    assert "cam-rec-b" not in h and dumbbell({"rows": []}) == ""


def test_growth_label():
    assert _gx(1.3) == "×1.3" and _gx(1.337) == "×1.34" and _gx(None) == "—"


def test_diff_keeps_scenario_identity_when_a_duplicate_variant_is_added():
    prev = snap({}, crit(1, 0), {}, [])
    cur = snap({}, crit(2, 0), {}, [])
    prev['scenarios'] = [{'scenario_id': 'a', 'variant_id': 'shared', 'power': {'total_mw': 100}}]
    cur['scenarios'] = [
        {'scenario_id': 'a', 'variant_id': 'shared', 'power': {'total_mw': 120}},
        {'scenario_id': 'b', 'variant_id': 'shared', 'power': {'total_mw': 300}}]
    prev['cpu'] = [{'scenario_id': 'a', 'variant_id': 'shared', 'summary': {'tolerance': 1.5}}]
    cur['cpu'] = [
        {'scenario_id': 'a', 'variant_id': 'shared', 'summary': {'tolerance': 0}},
        {'scenario_id': 'b', 'variant_id': 'shared', 'summary': {'tolerance': 1.1}}]
    diff = report_diff(prev, cur, {})
    assert diff['power']['changed'][0]['variant_id'] == 'a/shared'
    assert diff['power']['changed'][0]['delta_mw'] == 20
    assert diff['power']['added'] == ['b/shared'] and diff['power']['removed'] == []
    assert diff['cpu'] == [{'variant_id': 'a/shared', 'prev': 1.5, 'cur': 0},
                           {'variant_id': 'b/shared', 'prev': None, 'cur': 1.1}]
    assert '×0.0' in previous_block(diff)
