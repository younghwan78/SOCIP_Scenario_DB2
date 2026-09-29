from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.api.schemas.simulation import SimulateRequest
from scenario_db.db.models.capability import PowerModelParams as PowerModelParamsRow
from scenario_db.etl.mappers.capability import upsert_power_model_params
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.models import (
    DVFSLevel,
    DVFSTable,
    IPSimParams,
    IPWorkload,
    PortTransferSpec,
    PortType,
    SimulationInputs,
    SimulationRunConfig,
)
from scenario_db.sim.power_model import V1VfpsModel, resolve_power_model
from scenario_db.sim.runner import run_simulation
from scenario_db.sim.service import _apply_power_params, _check_power_params_scope
from scenario_db.sim.timing_budget import CpuPowerConfig

ROOT = Path(__file__).resolve().parents[3]

RAW = {
    "id": "pmp-x-v1",
    "schema_version": "2.2",
    "kind": "power_model_params",
    "soc_ref": "soc-x",
    "version": 3,
    "ip_model": "v1-vfps",
    "ref_voltage_mv": 700.0,
    "ref_fps": 60.0,
    "bw_model": "linear-per-gbps",
    "bw": {"mw_per_gbps": 50.0},
    "cpu": {
        "clusters": [
            {"name": "l", "coeff_uw_per_mhz_v2": 100.0},
            {"name": "m", "coeff_uw_per_mhz_v2": 200.0},
            {"name": "b", "coeff_uw_per_mhz_v2": 300.0},
            {"name": "p", "coeff_uw_per_mhz_v2": 400.0},
        ],
        "default_cluster": 2,
        "source": "unit test",
    },
    "calibration": {"source_evidence": ["meas-x"], "factor_by_ip": {"mcsc": 0.93}},
}


def _params(**over) -> PowerModelParams:
    return PowerModelParams.model_validate({**RAW, **over})


def _inputs(config: SimulationRunConfig) -> SimulationInputs:
    return SimulationInputs(
        scenario_id="uc-x",
        variant_id="v1",
        config=config,
        workloads=[
            IPWorkload(
                node_id="isp0", ip_ref="ip-isp0", hw_name="ISP0", width=1920, height=1080, fps=30.0,
                sim_params=IPSimParams(hw_name="ISP0", ppc=4, unit_power_mw_mp=10, vdd="VDD_CAM"),
            )
        ],
        port_transfers=[
            PortTransferSpec(
                node_id="isp0", ip_ref="ip-isp0", hw_name="ISP0", port="WDMA0",
                port_type=PortType.DMA_WRITE, width=3840, height=2160, format="YUV420", bitwidth=10,
            )
        ],
    )


def _run(**config):
    base = dict(fps=30.0, include_timeline=False)
    dvfs = {"CAM": DVFSTable(domain="CAM", levels=[DVFSLevel(level=0, speed_mhz=800.0, voltages={4: 650.0})])}
    inputs = _inputs(SimulationRunConfig(**{**base, **config}))
    inputs.workloads[0].sim_params.dvfs_group = "CAM"
    return run_simulation(inputs, dvfs_tables=dvfs)


# --- model -------------------------------------------------------------------
def test_model_accepts_document_id_prefix_and_rejects_bad_input():
    assert _params().params_ref == "pmp-x-v1@3"
    with pytest.raises(ValueError):
        _params(id="power-x-v1")
    with pytest.raises(ValueError):
        _params(cpu={"clusters": [{"name": "only", "coeff_uw_per_mhz_v2": 1.0}]})  # not 4
    with pytest.raises(ValueError):
        _params(ref_voltage_mv=0)
    with pytest.raises(ValueError):
        _params(bogus_field=1)


def test_params_hash_tracks_coefficients_not_storage():
    assert _params().params_hash() == _params().params_hash()
    assert _params().params_hash() != _params(ref_voltage_mv=705.0).params_hash()


def test_all_fields_optional_except_identity():
    minimal = PowerModelParams.model_validate(
        {"id": "pmp-min-v1", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x"}
    )
    assert minimal.ref_voltage_mv is None and minimal.bw_model is None


# --- power model injection ----------------------------------------------------
def test_v1_model_defaults_equal_historical_constants_and_params_override():
    default = V1VfpsModel()
    assert (default.ref_voltage_mv, default.ref_fps) == (710.0, 30.0)
    tuned = default.with_params(_params())
    assert (tuned.ref_voltage_mv, tuned.ref_fps) == (700.0, 60.0)
    kwargs = dict(unit_power_mw_mp=10.0, resolution_mp=2.0, voltage_mv=710.0, fps=30.0)
    assert default.ip_active_power_mw(**kwargs) == pytest.approx(20.0 * 1.0 * 1.0)
    assert tuned.ip_active_power_mw(**kwargs) == pytest.approx(20.0 * (710 / 700) ** 2 * 0.5)


def test_partial_params_keep_code_constants():
    tuned = V1VfpsModel().with_params(_params(ref_voltage_mv=None, ref_fps=None))
    assert (tuned.ref_voltage_mv, tuned.ref_fps) == (710.0, 30.0)


def test_resolve_power_model_rejects_ip_model_mismatch():
    with pytest.raises(ValueError, match="ip_model"):
        resolve_power_model("v1-vfps", _params(ip_model="v2-dyn-static"))


# --- run behaviour --------------------------------------------------------------
def test_no_params_is_unchanged_and_carries_no_lineage():
    result = _run()
    model = result.power_breakdown["model"]
    assert model == {"id": "v1-vfps", "version": "1.0"}


def test_params_change_power_and_stamp_lineage():
    base = _run()
    with_params = _run(power_params=_params())
    assert with_params.core_power_mw != base.core_power_mw
    assert with_params.core_power_mw == pytest.approx(10 * 2.0736 * (650 / 700) ** 2 * (30 / 60))
    model = with_params.power_breakdown["model"]
    assert model["params_ref"] == "pmp-x-v1@3"
    assert model["params_hash"] == _params().params_hash()
    assert model["calibration_evidence"] == ["meas-x"]
    assert (model["ref_voltage_mv"], model["ref_fps"]) == (700.0, 60.0)
    assert model["bw_model"]["id"] == "linear-per-gbps"
    # BW power: linear 50 mW/GB/s from params.
    assert with_params.bw_power_mw == pytest.approx(with_params.bw_total_mbs / 1000 * 50.0)


def test_explicit_bw_config_beats_params_and_params_bw_absent_means_builtin():
    explicit = _run(power_params=_params(), bw_power_mw_per_gbps=20.0)
    assert explicit.bw_power_mw == pytest.approx(explicit.bw_total_mbs / 1000 * 20.0)
    builtin = _run(power_params=_params(bw_model=None))
    assert "bw_model" not in builtin.power_breakdown["model"]
    assert builtin.bw_power_mw == pytest.approx(builtin.bw_total_mbs * 80.0 / 1000)


def test_unresolved_ref_fails_loudly_instead_of_silently_using_constants():
    with pytest.raises(ValueError, match="not resolved"):
        _run(power_params_ref="pmp-x-v1")


def test_no_reference_voltage_ip_uses_params_reference_voltage():
    result = _run(power_params=_params())
    inputs = _inputs(SimulationRunConfig(fps=30.0, include_timeline=False, power_params=_params()))
    no_table = run_simulation(inputs, dvfs_tables={})
    assert no_table.resolved["isp0"].set_voltage_mv == 700.0
    assert result.resolved["isp0"].set_voltage_mv == 650.0


# --- CPU -------------------------------------------------------------------------
def test_cpu_config_from_params_and_absent_cpu_block():
    cfg = CpuPowerConfig.from_params(_params())
    assert cfg is not None
    assert cfg.coeff_uw_per_mhz_v2 == [100.0, 200.0, 300.0, 400.0]
    assert cfg.cluster == 2
    assert cfg.source.startswith("pmp-x-v1@3")
    assert CpuPowerConfig.from_params(_params(cpu={})) is None


def test_partial_cpu_params_preserve_default_coefficients():
    cfg = CpuPowerConfig.from_params(_params(cpu={"freq_mhz": 1234, "volt_v": 0.8, "default_cluster": 1}))
    assert cfg is not None
    assert (cfg.freq_mhz, cfg.volt_v, cfg.cluster) == (1234, 0.8, 1)
    assert cfg.coeff_uw_per_mhz_v2 == CpuPowerConfig().coeff_uw_per_mhz_v2


def test_llc_scale_cannot_make_memory_power_negative():
    with pytest.raises(ValueError, match="llc_hit_scale"):
        _params(bw={"llc_hit_scale": 2})


# --- ETL mapper / service ------------------------------------------------------
class _Session:
    def __init__(self):
        self.rows: dict = {}

    def get(self, model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.id] = row


def _stored() -> tuple[_Session, PowerModelParamsRow]:
    db = _Session()
    upsert_power_model_params(RAW, "sha-1", db)
    return db, db.rows["pmp-x-v1"]


def _request(**config) -> SimulateRequest:
    return SimulateRequest.model_validate(
        {
            "scenario_id": "uc-x",
            "variant_id": "v1",
            "execution_context": {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-x", "thermal": "room"},
            "config": config,
        }
    )


def test_mapper_persists_body_and_is_idempotent_on_sha():
    db, row = _stored()
    assert (row.soc_ref, row.version, row.status) == ("soc-x", 3, "draft")
    assert row.params["bw"] == {"mw_per_gbps": 50.0, "llc_hit_scale": 1.0}
    assert row.params["calibration"]["factor_by_ip"] == {"mcsc": 0.93}
    upsert_power_model_params({**RAW, "ref_fps": 24.0}, "sha-1", db)  # same sha -> skipped
    assert row.params["ref_fps"] == 60.0


def test_apply_power_params_resolves_ref_and_hash_covers_coefficients():
    db, _ = _stored()
    request = _request(power_params_ref="pmp-x-v1@3")
    _apply_power_params(db, request)
    assert request.config.power_params is not None
    assert request.config.power_params.params_hash() == _params().params_hash()
    assert run_simulation(_inputs(request.config)).power_breakdown["model"]["params_ref"] == "pmp-x-v1@3"


def test_apply_power_params_is_a_noop_without_ref_and_errors_are_typed():
    db, _ = _stored()
    request = _request()
    _apply_power_params(db, request)
    assert request.config.power_params is None
    with pytest.raises(NotFoundError, match="pmp-nope"):
        _apply_power_params(db, _request(power_params_ref="pmp-nope"))
    with pytest.raises(UnprocessableError, match="version"):
        _apply_power_params(db, _request(power_params_ref="pmp-x-v1@9"))


def test_soc_scope_is_enforced():
    class _Graph:
        soc = type("S", (), {"id": "soc-other"})()

    with pytest.raises(ValueError, match="belongs to soc-x"):
        _check_power_params_scope(SimulationRunConfig(power_params=_params()), _Graph())
    _check_power_params_scope(SimulationRunConfig(), _Graph())  # no params -> fine


# --- shipped fixtures ------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "db_Exynos2600_SM-S947B/00_hw/pmp-exynos2600-v1.yaml",
        "db_Exynos2700_SM-S957B/00_hw/pmp-exynos2700-v1.yaml",
    ],
)
def test_shipped_params_fixtures_validate_and_match_code_defaults(path):
    raw = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    params = PowerModelParams.model_validate(raw)
    assert (params.ref_voltage_mv, params.ref_fps) == (710.0, 30.0)
    assert params.bw_model == "linear-per-gbps" and params.bw.mw_per_gbps == 50.0
    cpu = CpuPowerConfig.from_params(params)
    assert cpu is not None and cpu.coeff_uw_per_mhz_v2 == CpuPowerConfig().coeff_uw_per_mhz_v2


# --- readiness advisory -----------------------------------------------------------
class _Query:
    def __init__(self, hit):
        self._hit = hit

    def filter_by(self, **_):
        return self

    def first(self):
        return self._hit


class _QueryDb:
    def __init__(self, hit):
        self._hit = hit

    def query(self, *_):
        return _Query(self._hit)


def test_readiness_advises_missing_params_without_flipping_status():
    from scenario_db.sim.service import _advise_missing_power_params

    class _Graph:
        soc = type("S", (), {"id": "soc-x"})()

    report = {"status": "ready", "warnings": []}
    _advise_missing_power_params(_QueryDb(None), _Graph(), report)
    assert [w["code"] for w in report["warnings"]] == ["MISSING_POWER_MODEL_PARAMS"]
    assert report["status"] == "ready"
    covered = {"status": "ready", "warnings": []}
    _advise_missing_power_params(_QueryDb(("pmp-x-v1",)), _Graph(), covered)
    assert covered["warnings"] == []
