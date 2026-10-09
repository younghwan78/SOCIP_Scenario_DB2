"""S5: coefficient fit math, data scaling of a params document, and the engine's opt-in IP power scale."""

import pytest

from scenario_db.api.services import power_fit as pf
from scenario_db.sim.power_model import V1VfpsModel, V2VfClockModel


def test_fit_through_origin_and_quality():
    f = pf._fit([(100.0, 50.0), (200.0, 100.0), (400.0, 200.0)])
    assert f["k"] == pytest.approx(0.5) and f["n"] == 3 and f["rmse_after_mw"] == pytest.approx(0.0)
    assert f["mape_before_pct"] == pytest.approx(100.0) and f["r2_after"] == pytest.approx(1.0)
    assert pf._fit([(0.0, 10.0), (5.0, None)]) == {"k": None, "n": 0}
    clamped = pf._fit([(1.0, 100.0)])
    assert clamped["clamped"] and clamped["k"] == pf.K_RANGE[1]


def test_scale_cpu_and_bw_documents():
    cpu = {"clusters": [{"opps": [{"mhz": 1000, "mv": 700, "mw_per_core": 100.0}], "leakage": {"mw_per_core_at_ref": 10.0}},
                        {"coeff_uw_per_mhz_v2": 2.0}],
           "dsu": {"opps": [{"mhz": 800, "mw_per_core": 40.0}]}}
    pf._scale_cpu(cpu, 0.5)
    assert cpu["clusters"][0]["opps"][0]["mw_per_core"] == 50.0 and cpu["clusters"][0]["leakage"]["mw_per_core_at_ref"] == 5.0
    assert cpu["clusters"][1]["coeff_uw_per_mhz_v2"] == 1.0 and cpu["dsu"]["opps"][0]["mw_per_core"] == 20.0
    bw = {"e_read_mw_per_gbps": 50.0, "e_write_mw_per_gbps": 80.0, "mif_opps": [{"mhz": 421, "base_mw": 25.0}]}
    assert pf._scale_bw(bw, 2.0) and bw["e_read_mw_per_gbps"] == 100.0 and bw["mif_opps"][0]["base_mw"] == 50.0
    assert not pf._scale_bw({}, 2.0)


def test_ip_power_scale_is_opt_in_and_keyed():
    class P:
        ref_voltage_mv = None
        ref_fps = None
        ip_clock_power_fraction = None
        calibration = type("C", (), {"ip_power_scale": {"*": 1.2, "mfc": 0.9}})()

    m = V2VfClockModel().with_params(P())
    assert m.ip_scale_for("node_x", "isp") == 1.2 and m.ip_scale_for("mfc_enc", "mfc") == 0.9
    assert V1VfpsModel().ip_scale_for("anything") == 1.0       # no params -> unchanged physics
