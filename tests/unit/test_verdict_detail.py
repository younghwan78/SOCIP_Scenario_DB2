"""Board 판정 detail: stored reasons or reasons re-derived from frozen stages / intervals."""
from __future__ import annotations

from scenario_db.api.services.arch_exploration import verdict_detail

STAGES = {"rt": {"id": "rt", "name": "RT", "sw_ms": 1.0, "hw_ms": 26.0, "budget_ms": 25.0, "margin": 0.25, "feasible": True, "fill_pct": 80.0},
          "nrt": {"id": "nrt", "name": "NRT", "sw_ms": 9.0, "hw_ms": 20.0, "budget_ms": 8.0, "margin": -0.1, "feasible": False, "fill_pct": 120.0}}


def test_stored_reasons_win():
    d = verdict_detail({"verdict": "clock_up", "verdict_detail": {"status": "clock_up", "reasons": [], "nrt_clock_factor": 1.18},
                        "stages": STAGES, "period_ms": 33.33, "intervals": {"preview": 33.3, "video": 33.4}})
    assert d["derived"] is False and d["nrt_clock_factor"] == 1.18 and d["reasons"] == []
    assert {s["id"] for s in d["stages"]} == {"rt", "nrt"} and d["intervals"] == {"preview": 33.3, "video": 33.4}


def test_reasons_derived_for_older_predictions():
    d = verdict_detail({"verdict": "fail", "stages": STAGES, "period_ms": 33.33, "intervals_ok": False,
                        "intervals": {"preview": 40.0, "video": 33.3}})
    assert d["derived"] is True
    assert any(r.startswith("NRT: SW 9.00") for r in d["reasons"])
    assert any(r.startswith("RT HW 26.00") for r in d["reasons"])
    assert any(r.startswith("preview interval 40.000") for r in d["reasons"])


def test_absent_and_bare_fail():
    assert verdict_detail({}) is None
    d = verdict_detail({"verdict": "fail"})
    assert d["reasons"] == ["timing fail (detail not stored for this prediction)"] and d["stages"] == []


def test_clock_up_derived_reason():
    st = {"nrt": {"id": "nrt", "name": "NRT", "sw_ms": 11.1, "hw_ms": 22.23, "budget_ms": 22.23, "feasible": True, "fill_pct": 100.0}}
    d = verdict_detail({"verdict": "clock_up", "stages": st})
    assert d["derived"] and d["reasons"][0].startswith("NRT HW가 budget을 꽉 채움")
