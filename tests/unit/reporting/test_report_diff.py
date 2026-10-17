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
    assert d["power"]["changed"] == [{"variant_id": "b", "prev_mw": 200.0, "cur_mw": 260.0, "delta_mw": 60.0, "delta_pct": 30.0}]
    assert d["power"]["added"] == ["new"] and d["power"]["removed"] == ["gone"]
    assert {c["item"] for c in d["criteria"]} == {"fps_ok", "power_over"}
    assert d["basis"] == [{"item": "판정 기준", "prev": "stage", "cur": "pipelined"}]
    assert d["cpu"] == [{"variant_id": "a", "prev": 1.3, "cur": 1.1}]
    html = previous_block(d)
    assert "신규 risk 1" in html and "해소 후보 1" in html and "+60.0" in html and "pipelined" in html and "×1.1" in html


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
