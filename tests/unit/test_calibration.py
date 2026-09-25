from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import calibration as router
from scenario_db.comparison.calibration import compare_split, measured_split, rail_category

RAILS = {
    "B4S4_VDD_INT_L": {"power_mw": 99.083, "std_mw": 1.043},
    "B5_6S1_VDD_CAM_L": {"power_mw": 103.565, "std_mw": 1.09},
    "B5S4_VDDMIF_AP_L": {"domain": "MIF", "power_mw": 42.74, "std_mw": 0.45},
    "SRB1S4_VDD2H_MEM_AP_L": {"power_mw": 58.248},
    "B6S4_VDDQ_DRAM_MEM_0P5_T": {"domain": "MEM", "power_mw": 7.592},
    "B2S2_VDD_CPUCL1_MID_LF0_L": {"domain": "CPU", "power_mw": 113.28},
    "B5_6S3_VDD_CPUCL0_DSU_L": {"power_mw": 77.301},
    "B1_2_3E1_VDD_G3D1_0P725_L": {"power_mw": 1.851},
    "B6S2_VDD_SRAM_L": {"power_mw": 35.212},
    "L1S3_VDD_ICPU_L": {"power_mw": 18.781},
}


@pytest.mark.parametrize("rail,cat", [
    ("B4S4_VDD_INT_L", "ip"), ("B5_6S1_VDD_CAM_L", "ip"), ("B5S4_VDDMIF_AP_L", "bw"),
    ("SRB1S5_VDD2L_MEM_AP_L", "bw"), ("L5M_VDD1_MEM_L", "bw"), ("B3_4_5S2_VDD_CPUCL3_BIG_L", "cpu"),
    ("B5_6S3_VDD_CPUCL0_DSU_L", "cpu"), ("B1_2_3E1_VDD_G3D1_0P725_L", "other"), ("L1S3_VDD_ICPU_L", "other"),
    ("B6S2_VDD_SRAM_L", "other"), ("XYZ_UNKNOWN", "other"),
])
def test_rail_rules(rail, cat):
    assert rail_category(rail) == cat


def test_profile_map_and_domain_hint_win():
    assert rail_category("B4S4_VDD_INT_L", {"B4S4_VDD_INT_L": "MIF"}) == "bw"
    assert rail_category("ODD_RAIL", None, "CPU") == "cpu"
    assert rail_category("B1_VDD_GPU", None, "GPU") == "other"
    assert rail_category("ODD_RAIL", {"ODD_RAIL": "NPU"}) == "other"


def test_measured_split_sums_and_orders():
    s = measured_split(RAILS)
    c = s["categories"]
    assert c["ip"] == pytest.approx(99.083 + 103.565)
    assert c["bw"] == pytest.approx(42.74 + 58.248 + 7.592)
    assert c["cpu"] == pytest.approx(113.28 + 77.301)
    assert c["other"] == pytest.approx(1.851 + 35.212 + 18.781)
    assert s["rail_total_mw"] == pytest.approx(sum(r["power_mw"] for r in RAILS.values()), abs=1e-3)
    assert [r["category"] for r in s["rails"]][:2] == ["cpu", "cpu"]
    assert s["category_std"]["ip"] == pytest.approx((1.043**2 + 1.09**2) ** 0.5, abs=1e-3)


def test_compare_split_other_is_unmodeled():
    rows = {r["category"]: r for r in compare_split({"cpu": 310.0, "ip": 127.0, "bw": 237.0}, {"cpu": 190.0, "ip": 200.0, "bw": 110.0, "other": 55.0})}
    assert rows["cpu"]["delta_pct"] == pytest.approx(63.16, abs=0.01)
    assert rows["other"]["prediction_mw"] is None and rows["other"]["delta_pct"] is None
    assert compare_split(None, {"cpu": 1.0, "ip": 1.0, "bw": 1.0, "other": 0.0})[0]["prediction_mw"] is None


def _client(monkeypatch, **fakes):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: (yield MagicMock())
    for mod_name, fake in fakes.items():
        mod, name = mod_name.split(".")
        monkeypatch.setattr(getattr(router, mod), name, fake)
    return TestClient(app, raise_server_exceptions=False)


def test_routes(monkeypatch):
    c = _client(monkeypatch,
                **{"cal.list_measurements": lambda db, scenario_id=None: [{"id": "m", "scenario_id": scenario_id}],
                   "cal.measurement_detail": lambda db, mid: {"id": mid},
                   "lib.sw_timing": lambda db, scenario_id=None: {"tasks": [], "measured": [], "s": scenario_id}})
    assert c.get("/api/v1/calibration/measurements", params={"scenario_id": "s"}).json()[0]["scenario_id"] == "s"
    assert c.get("/api/v1/calibration/measurements/abc").json() == {"id": "abc"}
    assert c.get("/api/v1/library/sw-timing", params={"scenario_id": "x"}).json()["s"] == "x"


def test_compare_split_zero_prediction_is_unmodeled():
    rows = {r["category"]: r for r in compare_split({"cpu": 0.0, "ip": 130.0, "bw": 429.0}, {"cpu": 265.0, "ip": 203.0, "bw": 150.0})}
    assert rows["cpu"]["prediction_mw"] is None and rows["cpu"]["delta_pct"] is None
    assert rows["ip"]["delta_pct"] is not None
