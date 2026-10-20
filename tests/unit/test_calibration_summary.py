"""Model-level calibration helpers: bias verdicts, flat-term detection, correction preview, confidence."""
from __future__ import annotations

from scenario_db.comparison.calibration import bias_stats, correction_preview, flat_term
from scenario_db.reporting.arch_conclusion import calibration_confidence


def test_bias_stats_verdicts():
    common = bias_stats([-61, -58, -63, -40, -65, -55])
    assert common["verdict"] == "model_common" and common["sign"] == -1 and common["same_sign_pct"] == 100.0
    assert common["median"] == -59.5 and common["within25"] == 0
    assert bias_stats([2, -3, 8, 1, -9])["verdict"] == "ok"
    assert bias_stats([12, 15, 18, 20, 30])["verdict"] == "bias"
    spread = bias_stats([-30, 40, -20, 95, -25])
    assert spread["verdict"] == "scenario" and spread["min"] == -30 and spread["max"] == 95
    assert bias_stats([None, 5])["verdict"] == "insufficient"
    assert bias_stats([])["n"] == 0


def test_flat_term_detects_fps_only_prediction():
    pairs = [(63.6, 30), (63.6, 29.97), (127.3, 59.94), (50.9, 23.98), (101.4, 30), (176.5, 30)]
    flat = flat_term(pairs)
    assert flat is not None and flat["count"] == 4 and flat["n"] == 6 and abs(flat["mw_at_base_fps"] - 63.6) < 0.2
    assert flat_term([(63.6, 30), (101.4, 30), (176.5, 30), (88.0, 30)]) is None


def test_correction_preview_shows_compensation():
    # CPU under, BW over: the total looks right; fixing BW alone makes it worse
    rows = [{"meas": {"total": 600, "other": 50}, "pred": {"cpu": 100, "ip": 200, "bw": 280}},
            {"meas": {"total": 500, "other": 50}, "pred": {"cpu": 90, "ip": 170, "bw": 230}}]
    asis = correction_preview(rows, {})
    bw_only = correction_preview(rows, {"bw": 0.5})
    assert asis["n"] == 2 and abs(asis["median"]) < abs(bw_only["median"])
    both = correction_preview(rows, {"bw": 0.5, "cpu": 2.4})
    assert abs(both["median"]) < abs(bw_only["median"])


def test_confidence_shared_rule():
    fit = lambda w, off=False: {"worst_delta_pct": w, "offsetting": off, "worst_category": "bw"}  # noqa: E731
    assert calibration_confidence([{"origin": "synthetic", "synthetic": True, "fit": fit(5)}])["grade"] == "C"
    b = calibration_confidence([{"origin": "physical_capture", "synthetic": False, "fit": fit(81.4, True)}])
    assert b["grade"] == "B" and b["real"] == 1 and any("상쇄" in r for r in b["reasons"])
    a = calibration_confidence([{"origin": "physical_capture", "synthetic": False, "fit": fit(6)}])
    assert a["grade"] == "A" and a["reasons"] == []
    # weak input (SAMPLE DVFS) downgrades a reasoned grade to C, as in the report
    assert calibration_confidence([{"origin": "physical_capture", "synthetic": False, "fit": fit(30)}],
                                  input_reasons=["DVFS SAMPLE"], weak_input=True)["grade"] == "C"


def test_representative_selection_prefers_comparable_physical_captures():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from scenario_db.comparison.measurement_selection import representative_measurement

    physical = SimpleNamespace(id="physical", kpi={'total_power_mw': 100},
                               provenance={'device_id': 'device', 'collection_method': 'capture'},
                               measured_at=datetime(2025, 1, 1))
    synthetic = SimpleNamespace(id="synthetic", kpi={'total_power_mw': {'mean': 100}}, provenance={'device_id': 'SYNTHETIC'},
                                measured_at=datetime(2026, 1, 1, tzinfo=UTC))
    missing = SimpleNamespace(id="missing", kpi={}, provenance=physical.provenance, measured_at=None)
    assert representative_measurement([missing, synthetic, physical]) is physical
    assert representative_measurement([missing, synthetic]) is synthetic
    newer = SimpleNamespace(id="newer", kpi=physical.kpi, provenance=physical.provenance,
                            measured_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert representative_measurement([physical, newer]) is newer
