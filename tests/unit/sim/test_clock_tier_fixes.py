"""Review fixes H1-H4 on the clock ledger / PMU path.

H1 measured weighted-mean clock must not be snapped up to a DVFS level
H2 one measured/configured value must not be copied onto several HW instances
H3 configured clocks follow the variant's DVFS scenario, not one project map
H4 comparisons use the calculated clock tier and report model-lineage changes
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.comparison.evidence import compare_prediction_measurement, normalize_evidence_observations
from scenario_db.meas_import.pmu_digest import PmuDigestError, build_pmu_digest, PmuSample
from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.models.capability.sim_config import SimConfigRunDefaults
from scenario_db.models.evidence.metrics import load_default_metric_catalog
from scenario_db.sim.adapter import effective_configured_clocks
from scenario_db.sim.clock_models import ConfiguredClock, MeasuredClock
from scenario_db.sim.dvfs_resolver import DvfsResolver
from scenario_db.sim.measured_clock import measured_clocks_from_observations
from scenario_db.sim.model_lineage import lineage_differences, run_model_lineage
from scenario_db.sim.models import DVFSLevel, DVFSTable, IPSimParams, IPWorkload, SimulationRunConfig

V = {400.0: 650.0, 666.0: 750.0}


@pytest.mark.parametrize("residency", [{float("nan"): 1}, {float("inf"): 1}, {400: float("nan")}, {400: float("inf")}])
def test_nonfinite_residency_is_rejected(residency):
    with pytest.raises(ValueError, match="residency"):
        MeasuredClock(mhz=400, residency=residency)


def test_residency_preserves_explicit_dvfs_override():
    resolver = DvfsResolver(_tables(), clock_basis="measured", measured_clocks={
        "ip-gdc": MeasuredClock(mhz=533, residency={400: 1, 666: 1}),
    })
    cfg = resolver.resolve([_wl("gdc")], dvfs_overrides={"CAM": 1})["gdc"]
    assert (cfg.set_clock_mhz, cfg.set_voltage_mv, cfg.dvfs_level) == (666, 750, 1)
    assert any("override takes precedence" in warning for warning in resolver.warnings)


def test_residency_does_not_lower_calculated_peer_requirement():
    resolver = DvfsResolver(_tables(), clock_basis="measured", measured_clocks={
        "gdc": MeasuredClock(mhz=453.2, residency={400: 4, 666: 1}),
    })
    out = resolver.resolve([_wl("gdc"), _wl("peer", ip_ref="ip-peer", w=17000)])
    assert out["peer"].clock_ledger.basis_used == "calculated"
    assert out["peer"].set_clock_mhz >= out["peer"].required_clock_mhz
    assert out["gdc"].set_clock_mhz == out["peer"].set_clock_mhz == 666
    assert any("peer needs a higher clock" in warning for warning in resolver.warnings)


def test_nondominant_residency_level_above_table_is_infeasible():
    resolver = DvfsResolver(_tables(), clock_basis="measured", measured_clocks={
        "ip-gdc": MeasuredClock(mhz=460, residency={400: 9, 1000: 1}),
    })
    cfg = resolver.resolve([_wl("gdc")])["gdc"]
    assert not cfg.feasible
    assert "exceeds supported clock" in cfg.infeasible_reason


def _tables() -> dict[str, DVFSTable]:
    return {
        "CAM": DVFSTable(
            domain="CAM",
            levels=[DVFSLevel(level=i, speed_mhz=mhz, voltages={4: V[mhz]}) for i, mhz in enumerate(sorted(V))],
        )
    }


def _wl(node_id: str, *, ip_ref="ip-gdc", instance=0, w=2000, group="CAM") -> IPWorkload:
    return IPWorkload(
        node_id=node_id, instance_index=instance, ip_ref=ip_ref, hw_name="GDC",
        width=w, height=1000, fps=30.0,
        sim_params=IPSimParams(hw_name="GDC", ppc=1, unit_power_mw_mp=10, dvfs_group=group),
    )


# --- H1 ---------------------------------------------------------------------------
def test_residency_weighted_voltage_replaces_snapped_mean():
    meas = MeasuredClock(mhz=533.0, residency={400.0: 5, 666.0: 5})
    calc = DvfsResolver(_tables()).resolve([_wl("gdc_m")])["gdc_m"]
    out = DvfsResolver(_tables(), clock_basis="measured", measured_clocks={"ip-gdc": meas}).resolve([_wl("gdc_m")])
    cfg = out["gdc_m"]
    v_eff = math.sqrt(0.5 * 650.0**2 + 0.5 * 750.0**2)
    assert cfg.set_clock_mhz == pytest.approx(533.0)
    assert cfg.set_voltage_mv == pytest.approx(v_eff)
    assert cfg.total_power_mw == pytest.approx(calc.total_power_mw * (v_eff / 650.0) ** 2)
    ledger = cfg.clock_ledger
    assert ledger.measured_voltage_basis == "residency_weighted"
    assert ledger.measured_residency == {"400": 0.5, "666": 0.5}


def test_mean_without_residency_is_flagged_as_snapped():
    resolver = DvfsResolver(_tables(), clock_basis="measured", measured_clocks={"ip-gdc": MeasuredClock(mhz=533.0)})
    cfg = resolver.resolve([_wl("gdc_m")])["gdc_m"]
    assert cfg.set_clock_mhz == 666.0
    assert cfg.clock_ledger.measured_voltage_basis == "snapped_mean"
    assert any("snapped up" in w for w in resolver.warnings)


def test_dominant_level_is_a_real_operating_point():
    resolver = DvfsResolver(
        _tables(), clock_basis="measured", measured_clocks={"ip-gdc": MeasuredClock(mhz=666.0, stat="dominant")}
    )
    cfg = resolver.resolve([_wl("gdc_m")])["gdc_m"]
    assert (cfg.set_clock_mhz, cfg.set_voltage_mv) == (666.0, 750.0)
    assert cfg.clock_ledger.measured_voltage_basis == "level" and resolver.warnings == []


def test_residency_blend_applies_to_the_whole_dvfs_group():
    meas = {"gdc_m": MeasuredClock(mhz=533.0, residency={400.0: 1, 666.0: 1})}
    out = DvfsResolver(_tables(), clock_basis="measured", measured_clocks=meas).resolve(
        [_wl("gdc_m"), _wl("mcsc", ip_ref="ip-mcsc")]
    )
    assert out["mcsc"].set_clock_mhz == pytest.approx(533.0)
    assert out["mcsc"].set_voltage_mv == pytest.approx(out["gdc_m"].set_voltage_mv)


def test_pmu_residency_survives_into_the_measured_clock():
    samples = [
        PmuSample("ip_clock_residency", "ip", "MTNR", value, freq_mhz=freq, line=i)
        for i, (freq, value) in enumerate([(600.0, 300), (800.0, 600), (1000.0, 100)])
    ]
    digest = build_pmu_digest(samples, ip_map={"MTNR": "ip-mtnr"})
    clocks = measured_clocks_from_observations(digest.observations)
    assert clocks["ip-mtnr"].residency == pytest.approx({600.0: 0.3, 800.0: 0.6, 1000.0: 0.1})
    assert clocks["ip-mtnr"].dominant_mhz == 800.0
    assert measured_clocks_from_observations(digest.observations, stat="dominant")["ip-mtnr"].residency is None


# --- H2 ---------------------------------------------------------------------------
def test_generic_key_is_not_copied_onto_distinct_instances():
    resolver = DvfsResolver(
        _tables(), clock_basis="measured",
        measured_clocks={"ip-gdc": MeasuredClock(mhz=666.0, stat="dominant"),
                         "ip-gdc#1": MeasuredClock(mhz=400.0, stat="dominant")},
    )
    out = resolver.resolve([_wl("gdc0", group=None), _wl("gdc1", instance=1, group=None)])
    assert out["gdc0"].clock_ledger.basis_used == "calculated"
    assert out["gdc1"].clock_ledger.measured_mhz == 400.0
    assert any("several HW instances" in w and "ip-gdc#0" in w for w in resolver.warnings)


def test_time_shared_nodes_of_one_instance_share_the_generic_key():
    resolver = DvfsResolver(
        _tables(), clock_basis="measured", measured_clocks={"ip-gdc": MeasuredClock(mhz=666.0, stat="dominant")}
    )
    out = resolver.resolve([_wl("gdc_m"), _wl("gdc_o")])
    assert {cfg.clock_ledger.basis_used for cfg in out.values()} == {"measured"}


def test_pmu_map_rejects_two_instances_on_one_id():
    samples = [
        PmuSample("ip_clock_mhz", "ip", "MCSC0", 600.0, unit="MHz", stat="mean", line=1),
        PmuSample("ip_clock_mhz", "ip", "MCSC1", 400.0, unit="MHz", stat="mean", line=2),
    ]
    with pytest.raises(PmuDigestError, match="all map to 'ip-mcsc'"):
        build_pmu_digest(samples, ip_map={"MCSC0": "ip-mcsc", "MCSC1": "ip-mcsc"})
    digest = build_pmu_digest(samples, ip_map={"MCSC0": "ip-mcsc#0", "MCSC1": "ip-mcsc#1"})
    assert {o["scope"]["ref"] for o in digest.observations} == {"ip-mcsc#0", "ip-mcsc#1"}


def test_prediction_clock_refs_are_instance_qualified():
    doc = {"dvfs_breakdown": [
        {"node_id": "a", "ip_ref": "ip-mcsc", "instance_index": 0, "set_clock_mhz": 600.0},
        {"node_id": "b", "ip_ref": "ip-mcsc", "instance_index": 1, "set_clock_mhz": 400.0},
        {"node_id": "c", "ip_ref": "ip-gdc", "instance_index": 0, "set_clock_mhz": 500.0},
    ]}
    refs = {o["scope"]["ref"] for o in normalize_evidence_observations(doc, load_default_metric_catalog())
            if o["metric_id"] == "clock.ip"}
    assert refs == {"ip-mcsc#0", "ip-mcsc#1", "ip-gdc#0", "ip-gdc"}


# --- H3 ---------------------------------------------------------------------------
def _graph(dvfs_sn="SN_UHD30", node_configs=None):
    return SimpleNamespace(variant=SimpleNamespace(design_conditions={"dvfs_sn": dvfs_sn}, node_configs=node_configs or {}))


def test_configured_clock_precedence_project_dvfs_scenario_variant():
    config = SimulationRunConfig(
        configured_clocks={"mcsc": ConfiguredClock(mhz=400, reason_code="bsp_default"),
                           "gdc": ConfiguredClock(mhz=400, reason_code="bsp_default")},
        configured_clocks_by_dvfs_sn={
            "SN_UHD30": {"mcsc": ConfiguredClock(mhz=533, reason_code="dvfs_scenario"),
                         "CAM": ConfiguredClock(mhz=533, reason_code="dvfs_scenario")},
            "SN_FHD30": {"mcsc": ConfiguredClock(mhz=333, reason_code="dvfs_scenario")},
        },
    )
    graph = _graph(node_configs={"gdc": {"sim": {"configured_clock": {"mhz": 666, "reason_code": "overflow_guard"}}}})
    warnings: list[str] = []
    merged = effective_configured_clocks(graph, config, warnings)
    assert (merged["mcsc"].mhz, merged["mcsc"].source) == (533, "dvfs_scenario")
    assert (merged["gdc"].mhz, merged["gdc"].source) == (666, "variant")
    assert merged["CAM"].source == "dvfs_scenario" and warnings == []


def test_missing_dvfs_scenario_table_warns_and_invalid_node_value_fails():
    config = SimulationRunConfig(
        configured_clocks_by_dvfs_sn={"SN_FHD30": {"mcsc": ConfiguredClock(mhz=333, reason_code="dvfs_scenario")}}
    )
    warnings: list[str] = []
    assert effective_configured_clocks(_graph(), config, warnings) is None
    assert "SN_UHD30" in warnings[0]
    with pytest.raises(ValueError, match="gdc: invalid sim.configured_clock"):
        effective_configured_clocks(_graph(node_configs={"gdc": {"sim": {"configured_clock": {"mhz": 1}}}}),
                                    SimulationRunConfig(), [])


def test_dvfs_domain_key_configures_every_ip_on_the_shared_clock():
    resolver = DvfsResolver(
        _tables(), clock_basis="configured",
        configured_clocks={"CAM": ConfiguredClock(mhz=666, reason_code="dvfs_scenario", source="dvfs_scenario")},
    )
    out = resolver.resolve([_wl("gdc_m"), _wl("mcsc", ip_ref="ip-mcsc")])
    assert {cfg.set_clock_mhz for cfg in out.values()} == {666.0}
    assert out["mcsc"].clock_ledger.configured_source == "dvfs_scenario"


def test_sim_config_profile_accepts_dvfs_scenario_tables():
    defaults = SimConfigRunDefaults.model_validate(
        {"configured_clocks_by_dvfs_sn": {"SN": {"CAM": {"mhz": 666, "reason_code": "dvfs_scenario"}}}}
    )
    assert defaults.configured_clocks_by_dvfs_sn["SN"]["CAM"].mhz == 666


# --- H4 ---------------------------------------------------------------------------
def _pred(**ledger):
    return {
        "id": "sim-x", "kind": "evidence.simulation", "project_ref": "p", "scenario_ref": "s", "variant_ref": "v",
        "execution_context": {"sw_baseline_ref": "sw", "thermal": "room", "power_state": "d"},
        "power_breakdown": {"model": {"id": "v1-vfps", "version": "1.0"}},
        "dvfs_breakdown": [{"node_id": "m", "ip_ref": "ip-m", "set_clock_mhz": 700.0,
                            "clock_ledger": {"calculated_mhz": 600.0, **ledger}}],
    }


def _meas(mhz=650.0):
    return {
        "id": "meas-x", "kind": "evidence.measurement", "project_ref": "p", "scenario_ref": "s", "variant_ref": "v",
        "execution_context": {"sw_baseline_ref": "sw", "thermal": "room", "power_state": "d"},
        "metric_observations": [{"metric_id": "clock.ip", "scope": {"kind": "ip", "ref": "ip-m"},
                                 "unit": "MHz", "stats": {"mean": mhz}}],
    }


def test_prediction_side_is_the_calculated_tier_with_lineage_warnings():
    result = compare_prediction_measurement(
        _pred(basis="measured", basis_used="measured", measured_evidence_ref="meas-x"), _meas()
    )
    row = next(r for r in result["rows"] if r["metric_id"] == "clock.ip" and r["scope_ref"] == "ip-m")
    assert (row["prediction"], row["measurement"]) == (600.0, 650.0)
    codes = {w["code"] for w in result["model_lineage"]["warnings"]}
    assert codes == {"CLOCK_BASIS_SUBSTITUTED", "CIRCULAR_MEASURED_CLOCK", "CODE_CONSTANT_COEFFICIENTS"}


def test_lineage_differences_against_legacy_predictions():
    params = PowerModelParams.model_validate({
        "id": "pmp-x", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x",
        "bw_model": "linear-per-gbps", "bw": {"mw_per_gbps": 50.0},
    })
    new = run_model_lineage(SimulationRunConfig(power_params=params))
    fields = {c["field"] for c in lineage_differences(None, new)}
    assert fields == {"bw_power_model", "bw_coefficient", "power_params_hash"}
    assert lineage_differences(None, run_model_lineage(SimulationRunConfig())) == []
