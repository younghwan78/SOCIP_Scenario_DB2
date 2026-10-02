from __future__ import annotations

from scenario_db.comparison.calibration import compare_split
from scenario_db.reporting.arch_conclusion import build_conclusion, calibration_row, model_limits
from scenario_db.reporting.arch_report import render_html


def _detail(pred_split, meas, total_meas, pred_total, synthetic=False, pid="PRED-1"):
    rows = compare_split(pred_split, meas)
    return {"id": "MEAS-1", "measured_at": "2026-06-14T00:00:00", "synthetic": synthetic, "total": {"mean": total_meas},
            "predictions": [{"kind": "current", "id": pid, "total_mw": pred_total,
                             "delta_pct": round(100 * (pred_total - total_meas) / total_meas, 2), "rows": rows}]}


MEAS = {"cpu": 168.5, "ip": 190.9, "bw": 103.6, "other": 57.2}
PRED = {"cpu": 174.1, "ip": 123.8, "bw": 222.0}  # total 519.9 vs 520.2: matches by compensation


def _snap(**over):
    snap = {
        "overview": {"sample_dvfs": False, "dvfs_table_ref": "dvfs-inhouse-v1"},
        "spec_summary": {"explored": 3, "spec_ok": 2, "spec_fail": 1, "power_range_mw": [500.0, 900.0],
                         "failed": [{"variant_id": "cam-rec-r1-fhd120", "reasons": ["NRT: SW 11.10 ms leaves no HW budget"]}]},
        "sw_margin_top5": [{"variant_id": "cam-rec-r1-uhd60", "margin_pct": 5.7, "stage": "nrt", "bottleneck": "post_irta"}],
        "power_options": [{"variant_id": "cam-rec-r1-fhd60", "best": {"labels": ["MTNR L0 skip"], "delta_mw": -80.0, "delta_pct": -6.5}}],
        "calibration": [],
    }
    snap.update(over)
    return snap


def test_model_limits_follow_the_run_lineage():
    builtin = model_limits({"power_model": "v1-vfps", "bw_power_model": "builtin", "bw_coefficient": 80.0})
    assert any("MIF DVFS level 미반영" in x for x in builtin)
    v2 = model_limits({"power_model": "v2-vf", "bw_power_model": "mif-linear", "power_params_ref": "pmp-x", "clock_basis": "measured"})
    assert not any("MIF DVFS level 미반영" in x for x in v2)
    assert any("mif-linear" in x for x in v2) and any("pmp-x" in x for x in v2)
    assert "lineage 기록이 없음" in model_limits(None)[0]


def test_calibration_row_flags_offsetting_categories():
    row = calibration_row("cam-rec-r1-uhd30-vdis", "uc", _detail(PRED, MEAS, 520.2, 519.9), "PRED-1")
    assert row["fit"]["offsetting"] is True and row["fit"]["worst_category"] == "bw"
    assert row["unmodeled_mw"] == 57.2
    assert calibration_row("v", "uc", _detail(PRED, MEAS, 520.2, 519.9), "OTHER") is None


def test_conclusion_risks_actions_and_confidence():
    c = build_conclusion(_snap())
    assert c["headline"].startswith("탐색 3개 중 2개 spec 만족")
    assert [r["title"].split(" ")[0] for r in c["risks"]][:2] == ["spec", "SW"]
    assert c["actions"][0]["delta_mw"] == -80.0 and c["actions"][0]["check"] == "IQ 평가"
    assert any("post_irta" in a["action"] for a in c["actions"])
    assert c["confidence"]["grade"] == "C"  # no real measurement

    real = calibration_row("cam-rec-r1-uhd30-vdis", "uc", _detail(PRED, MEAS, 520.2, 519.9), "PRED-1")
    c2 = build_conclusion(_snap(calibration=[real]))
    assert c2["confidence"]["grade"] == "B" and any("상쇄" in r["title"] for r in c2["risks"])
    good = calibration_row("v", "uc", _detail({"cpu": 170, "ip": 185, "bw": 100}, MEAS, 520.2, 455.0), "PRED-1")
    assert build_conclusion(_snap(calibration=[good]))["confidence"]["grade"] == "A"
    assert build_conclusion(_snap(calibration=[good], overview={"sample_dvfs": True, "dvfs_table_ref": "x-sample"}))["confidence"]["grade"] == "C"


def test_render_handles_snapshot_without_conclusion():
    from scenario_db.reporting.arch_report import _calibration, _conclusion

    assert "이전 형식" in _conclusion(None)
    assert "검증되지 않았습니다" in _calibration([])
    real = calibration_row("cam-rec-r1-uhd30-vdis", "uc", _detail(PRED, MEAS, 520.2, 519.9), "PRED-1")
    assert "상쇄" in _calibration([real])
    assert callable(render_html)
