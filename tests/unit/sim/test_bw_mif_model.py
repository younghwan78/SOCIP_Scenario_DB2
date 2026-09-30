"""mif-linear BW power model (MIF level from QoS lock / governor) and its least-squares fit."""
from __future__ import annotations

import pathlib

import pytest

from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.bw_fit import FitRow, fit_mif_linear, main as fit_main, row_from_evidence, rows_from_csv
from scenario_db.sim.bw_power import BwPowerContext, bw_model_from_config
from scenario_db.sim.models import IPSimParams, IPWorkload, PortTransferSpec, PortType, SimulationInputs, SimulationRunConfig
from scenario_db.sim.runner import run_simulation

ROOT = pathlib.Path(__file__).resolve().parents[3]
BW = {
    "e_read_mw_per_gbps": 50.0, "e_write_mw_per_gbps": 80.0, "governor_util": 0.5, "other_masters_mbs": 1000.0,
    "mif_opps": [{"mhz": 845, "base_mw": 40, "capacity_mbs": 6000},
                 {"mhz": 1539, "base_mw": 90, "capacity_mbs": 12000},
                 {"mhz": 2730, "base_mw": 150, "capacity_mbs": 21000}],
    "qos_lock_mhz_by_dvfs_sn": {"IS_DVFS_SN_UHD60": 1539},
}


def _params(**bw) -> PowerModelParams:
    return PowerModelParams.model_validate({
        "id": "pmp-bw", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x",
        "bw_model": "mif-linear", "bw": {**BW, **bw}})


def _model(**bw):
    return bw_model_from_config(SimulationRunConfig(power_params=_params(**bw)))


def test_governor_level_qos_lock_and_saturation():
    model = _model()
    ctx = lambda dram, sn=None: BwPowerContext(extra={"dram_mbs": dram, "dvfs_sn": sn})  # noqa: E731
    assert model.mif_state(ctx(1500))["mif_mhz"] == 845              # (1500 + 1000) <= 6000 x 0.5
    assert model.mif_state(ctx(2500))["mif_mhz"] == 1539             # 3500 > 3000
    assert model.mif_state(ctx(1500, "IS_DVFS_SN_UHD60"))["reason"] == "qos_lock"
    sat = model.mif_state(ctx(30000))
    assert sat["mif_mhz"] == 2730 and sat["reason"] == "saturated"


def test_port_energy_by_direction_and_aggregate():
    model = _model()
    assert model.port_power_mw(bw_mbs=2000, direction="read", llc_enabled=False, llc_weight=1.0) == pytest.approx(100)
    assert model.port_power_mw(bw_mbs=2000, direction="write", llc_enabled=True, llc_weight=0.5) == pytest.approx(80)
    total = model.aggregate_power_mw([100, 80], context=BwPowerContext(extra={"dram_mbs": 3000}))
    # base at 1539 (4000 > 3000 at 845) + other masters 1 GB/s x 50
    assert total == pytest.approx(180 + 90 + 50)


def test_runner_reports_the_mif_state_and_uses_the_variant_qos_lock():
    inputs = SimulationInputs(
        scenario_id="s", variant_id="v", dvfs_sn="IS_DVFS_SN_UHD60",
        config=SimulationRunConfig(power_params=_params(), fps=30),
        workloads=[IPWorkload(node_id="isp", ip_ref="ip-isp", hw_name="ISP", width=100, height=100, fps=30,
                              sim_params=IPSimParams(hw_name="ISP", ppc=1, unit_power_mw_mp=1))],
        port_transfers=[PortTransferSpec(node_id="isp", hw_name="ISP", port="R", port_type=PortType.DMA_READ,
                                         width=0, height=0, bitrate_mbps=8000)],   # 1000 MB/s read
    )
    result = run_simulation(inputs)
    mif = result.power_breakdown["memory"]["mif"]
    assert mif["mif_mhz"] == 1539 and mif["reason"] == "qos_lock" and mif["dram_mbs"] == pytest.approx(1000)
    assert result.bw_power_mw == pytest.approx(50 + 90 + 50)
    assert result.power_breakdown["model"]["bw_model"]["id"] == "mif-linear"


def test_existing_params_hash_is_unchanged_by_unset_mif_fields():
    plain = PowerModelParams.model_validate({"id": "pmp-a", "schema_version": "2.2", "kind": "power_model_params",
                                             "soc_ref": "soc-x", "bw": {"mw_per_gbps": 50}})
    assert set(plain.model_dump(exclude_none=True)["bw"]) == {"mw_per_gbps", "llc_hit_scale"}


def test_fit_recovers_synthetic_coefficients_and_reports_residuals():
    rows = rows_from_csv(ROOT / "examples" / "bw-fit" / "mem_rows.csv")
    out = fit_mif_linear(rows, capacity_mbs={845.0: 6000})
    bw = out["bw"]
    assert bw["e_read_mw_per_gbps"] == pytest.approx(55, abs=3) and bw["e_write_mw_per_gbps"] == pytest.approx(70, abs=4)
    assert [o["mhz"] for o in bw["mif_opps"]] == [845.0, 1539.0, 2730.0]
    assert bw["mif_opps"][0]["capacity_mbs"] == 6000 and bw["fit"]["r2"] > 0.99
    assert len(out["residuals"]) == len(rows) and out["warnings"] == []
    PowerModelParams.model_validate({"id": "pmp-f", "schema_version": "2.2", "kind": "power_model_params",
                                     "soc_ref": "soc-x", "bw_model": "mif-linear", "bw": bw})


def test_fit_warns_when_under_determined_and_uses_residency():
    rows = [FitRow("a", 1000, 500, 120, {845.0: 0.5, 1539.0: 0.5}), FitRow("b", 2000, 800, 180, {1539.0: 1.0})]
    out = fit_mif_linear(rows)
    assert any("under-determined" in w for w in out["warnings"])
    with pytest.raises(ValueError, match="MIF level"):
        fit_mif_linear([FitRow("x", 1, 1, 1)])


def test_evidence_row_and_cli(tmp_path, capsys):
    doc = {"id": "meas-1", "kind": "evidence.measurement",
           "vdd_power": {"BUCK_MIF": {"mean": 100.0}, "BUCK_DRAM": 50.0, "BUCK_CPU": 999.0},
           "metric_observations": [
               {"metric_id": "bandwidth.mem_read", "scope": {"kind": "mif", "ref": "total"}, "stats": {"mean": 4000}},
               {"metric_id": "bandwidth.mem_write", "scope": {"kind": "mif", "ref": "total"}, "stats": {"mean": 2000}},
               {"metric_id": "clock.ip_dominant", "scope": {"kind": "ip", "ref": "MIF"}, "value": 1539}]}
    row = row_from_evidence(doc, rails=["BUCK_MIF", "BUCK_DRAM"], mif_ref="MIF")
    assert (row.mem_power_mw, row.read_mbs, row.mif_residency) == (150.0, 4000, {1539.0: 1.0})
    out = tmp_path / "bw.yaml"
    assert fit_main(["--csv", str(ROOT / "examples" / "bw-fit" / "mem_rows.csv"), "--out", str(out)]) == 0
    assert "mif-linear" in out.read_text()
