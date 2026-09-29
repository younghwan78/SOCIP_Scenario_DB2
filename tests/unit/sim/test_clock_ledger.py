from __future__ import annotations

import pytest

pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.models.capability.sim_config import SimConfigProfile, SimConfigRunDefaults
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.reporting.html_report import generate_simulation_report_html
from scenario_db.reporting.models import ReportContext
from scenario_db.reporting.tables import clock_ledger_rows, has_clock_tier_data, ip_detail_rows
from scenario_db.sim.clock_corrections import _raise_clock_correction
from scenario_db.sim.clock_models import ClockConstraint, ConfiguredClock, MeasuredClock
from scenario_db.sim.dvfs_resolver import DvfsResolver
from scenario_db.sim.models import (
    DVFSLevel,
    DVFSTable,
    IPSimParams,
    IPWorkload,
    SimulationInputs,
    SimulationRunConfig,
)
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation

LEVELS = [400.0, 600.0, 800.0, 1000.0]


def _table() -> dict[str, DVFSTable]:
    return {
        "CAM": DVFSTable(
            domain="CAM",
            levels=[
                DVFSLevel(level=i, speed_mhz=mhz, voltages={4: 600.0 + 50 * i})
                for i, mhz in enumerate(LEVELS)
            ],
        )
    }


def _workload(node_id: str, *, w=1920, h=1080, fps=30.0, ppc=0.5, group="CAM", **kw) -> IPWorkload:
    return IPWorkload(
        node_id=node_id,
        ip_ref=f"ip-{node_id}",
        hw_name=node_id.upper(),
        width=w,
        height=h,
        fps=fps,
        sim_params=IPSimParams(hw_name=node_id.upper(), ppc=ppc, unit_power_mw_mp=10, vdd="VDD_CAM", dvfs_group=group),
        **kw,
    )


def _throughput(w, h, fps, ppc, margin=0.15) -> float:
    return w * h * fps / (1 - margin) / ppc / 1e6


# --- constraint accumulation ---------------------------------------------------
def test_raise_clock_correction_keeps_every_constraint_and_the_legacy_max():
    workload = _workload("isp0")
    _raise_clock_correction(workload, 500.0, kind="mipi_ingress", reason="ingress")
    _raise_clock_correction(workload, 300.0, kind="vvalid_stream", reason="vvalid")
    _raise_clock_correction(workload, 700.0, kind="otf_align", reason="align")
    assert [(c.kind, c.mhz) for c in workload.clock_constraints] == [
        ("mipi_ingress", 500.0),
        ("vvalid_stream", 300.0),
        ("otf_align", 700.0),
    ]
    assert workload.clock_correction_mhz == 700.0
    assert workload.clock_correction_reason == "align"


def test_constraints_do_not_change_the_params_hash():
    plain = _workload("isp0")
    tracked = _workload("isp0")
    _raise_clock_correction(tracked, 0.0, kind="x", reason="zero")  # ignored, mhz <= 0
    tracked.clock_constraints.extend(plain.clock_constraints)
    base = SimulationRunConfig(fps=30.0, include_timeline=False)
    a = SimulationInputs(scenario_id="uc-x", variant_id="v", config=base, workloads=[plain])
    tracked.clock_constraints.append(ClockConstraint(kind="k", mhz=9.0))
    b = SimulationInputs(scenario_id="uc-x", variant_id="v", config=base, workloads=[tracked])
    assert params_hash(a) == params_hash(b)


# --- calculated ledger ----------------------------------------------------------
def test_calculated_ledger_lists_all_tiers_and_binding_constraint():
    big = _workload("mtnr", w=3840, h=2160, fps=30.0, ppc=0.5)
    small = _workload("mcsc", w=1920, h=1080, fps=30.0, ppc=0.5, manual_clock_mhz=450.0)
    _raise_clock_correction(small, 520.0, kind="vvalid_stream", reason="vvalid")
    resolver = DvfsResolver(_table())
    resolved = resolver.resolve([big, small])

    # Default behaviour: same numbers as before the ledger existed.
    need_big = _throughput(3840, 2160, 30, 0.5)
    assert resolved["mtnr"].required_clock_mhz == pytest.approx(need_big)
    assert resolved["mtnr"].set_clock_mhz == 600.0
    assert resolved["mcsc"].set_clock_mhz == 600.0  # shared DVFS group level

    ledger = resolved["mcsc"].clock_ledger
    assert ledger is not None
    assert ledger.basis == ledger.basis_used == "calculated"
    kinds = [c.kind for c in ledger.constraints]
    assert kinds == ["vvalid_stream", "manual", "dvfs_group_align"]
    assert ledger.binding_kind == "dvfs_group_align"
    assert ledger.throughput_required_mhz == pytest.approx(_throughput(1920, 1080, 30, 0.5))
    assert ledger.constraints[2].mhz == pytest.approx(need_big)
    assert ledger.calculated_mhz == 600.0
    assert ledger.gap["calculated_over_throughput_pct"] > 100
    assert ledger.gap["cause"] == "dvfs_group_align"
    assert resolved["mtnr"].clock_ledger.binding_kind == "throughput"
    assert resolver.warnings == []


# --- basis selection --------------------------------------------------------------
def test_configured_basis_drives_set_clock_power_and_records_gap():
    workloads = [_workload("mtnr", w=1920, h=1080, group="CAM")]
    calc = DvfsResolver(_table()).resolve(workloads)
    need = _throughput(1920, 1080, 30, 0.5)
    assert calc["mtnr"].set_clock_mhz == 400.0 and need < 400.0

    resolver = DvfsResolver(
        _table(),
        clock_basis="configured",
        configured_clocks={"MTNR": ConfiguredClock(mhz=900.0, reason_code="overflow_guard", ticket="CAM-1")},
    )
    resolved = resolver.resolve(workloads)["mtnr"]
    assert resolved.set_clock_mhz == 1000.0  # min DVFS level >= configured
    assert resolved.set_voltage_mv > calc["mtnr"].set_voltage_mv
    assert resolved.total_power_mw > calc["mtnr"].total_power_mw
    ledger = resolved.clock_ledger
    assert ledger.basis_used == "configured" and ledger.configured_mhz == 900.0
    assert ledger.calculated_mhz == 400.0  # calculated tier is still the reference
    assert ledger.gap["configured_minus_calculated_mhz"] == 500.0
    assert ledger.gap["cause"] == "overflow_guard"


def test_missing_configured_value_falls_back_to_calculated_with_warning():
    workloads = [_workload("mtnr"), _workload("mcsc")]
    resolver = DvfsResolver(
        _table(),
        clock_basis="configured",
        configured_clocks={"mtnr": ConfiguredClock(mhz=800.0, reason_code="bsp_default"), "ghost": ConfiguredClock(mhz=1.0, reason_code="other")},
    )
    resolved = resolver.resolve(workloads)
    assert resolved["mtnr"].clock_ledger.basis_used == "configured"
    fallback = resolved["mcsc"].clock_ledger
    assert fallback.basis_used == "calculated" and "no configured clock" in fallback.fallback
    assert any("mcsc" in w and "using the calculated clock" in w for w in resolver.warnings)
    assert any("'ghost' matches no simulated IP" in w for w in resolver.warnings)


def test_measured_basis_and_gap_tiers():
    workloads = [_workload("mtnr", group=None)]
    resolver = DvfsResolver(
        {},
        clock_basis="measured",
        configured_clocks={"mtnr": ConfiguredClock(mhz=700.0, reason_code="vvalid")},
        measured_clocks={"MTNR": MeasuredClock(mhz=650.0, stat="dominant", evidence_ref="meas-x")},
    )
    resolved = resolver.resolve(workloads)["mtnr"]
    assert resolved.set_clock_mhz == 650.0  # no DVFS table: clock used as-is
    ledger = resolved.clock_ledger
    assert ledger.basis_used == "measured" and ledger.measured_evidence_ref == "meas-x"
    assert ledger.gap["measured_minus_configured_mhz"] == -50.0
    assert ledger.gap["measured_minus_calculated_mhz"] == pytest.approx(650.0 - _throughput(1920, 1080, 30, 0.5))


def test_configured_below_requirement_warns_but_still_runs():
    workloads = [_workload("mtnr", w=3840, h=2160, group=None)]
    resolver = DvfsResolver(
        {}, clock_basis="configured", configured_clocks={"mtnr": ConfiguredClock(mhz=300.0, reason_code="thermal")}
    )
    resolved = resolver.resolve(workloads)["mtnr"]
    assert resolved.set_clock_mhz == 300.0
    assert any("below the calculated requirement" in w for w in resolver.warnings)


def test_configured_tier_is_recorded_even_when_basis_is_calculated():
    workloads = [_workload("mtnr")]
    resolver = DvfsResolver(
        _table(), configured_clocks={"mtnr": ConfiguredClock(mhz=1000.0, reason_code="overflow_guard")}
    )
    resolved = resolver.resolve(workloads)["mtnr"]
    assert resolved.set_clock_mhz == 400.0  # not applied
    assert resolved.clock_ledger.configured_mhz == 1000.0
    assert resolved.clock_ledger.gap["configured_minus_calculated_mhz"] == 600.0


def test_max_clock_feasibility_applies_to_substituted_clock():
    workload = _workload("mtnr", group=None)
    workload.sim_params.max_clock_mhz = 500.0
    resolver = DvfsResolver(
        {}, clock_basis="configured", configured_clocks={"mtnr": ConfiguredClock(mhz=600.0, reason_code="other")}
    )
    resolved = resolver.resolve([workload])["mtnr"]
    assert not resolved.feasible and "max_clock" in (resolved.infeasible_reason or "")


# --- config / schema ----------------------------------------------------------------
def test_reason_code_is_mandatory_and_validated():
    with pytest.raises(ValueError):
        ConfiguredClock(mhz=800.0)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        ConfiguredClock(mhz=800.0, reason_code="because")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SimulationRunConfig(clock_basis="wishful")  # type: ignore[arg-type]


def test_config_profile_carries_configured_clocks_through_etl_model():
    profile = SimConfigProfile.model_validate(
        {
            "id": "simcfg-proj-x-v1", "schema_version": "1.0", "kind": "sim.config_profile",
            "project_ref": "proj-x",
            "run_config": {
                "clock_basis": "configured",
                "configured_clocks": {"MTNR": {"mhz": 800, "reason_code": "bsp_default", "owner": "bsp"}},
            },
        }
    )
    dumped = profile.run_config.model_dump(exclude_none=True)
    assert dumped["configured_clocks"]["MTNR"]["reason_code"] == "bsp_default"
    assert SimulationRunConfig(**dumped).configured_clocks["MTNR"].mhz == 800
    assert SimConfigRunDefaults().model_dump(exclude_none=True) == {"dvfs_overrides": {}}
    with pytest.raises(ValueError):
        SimConfigProfile.model_validate(
            {
                "id": "simcfg-proj-x-v1", "schema_version": "1.0", "kind": "sim.config_profile",
                "project_ref": "proj-x",
                "run_config": {"configured_clocks": {"MTNR": {"mhz": 800}}},
            }
        )


def test_default_run_config_hash_inputs_are_unchanged():
    dumped = SimulationRunConfig().model_dump(mode="json", exclude_none=True)
    for key in ("clock_basis", "configured_clocks", "measured_clocks", "power_params", "bw_power_model"):
        assert key not in dumped


# --- evidence + reporting -------------------------------------------------------------
def _evidence(config: SimulationRunConfig):
    inputs = SimulationInputs(
        scenario_id="uc-x",
        variant_id="v1",
        config=config,
        workloads=[_workload("mtnr")],
    )
    result = run_simulation(inputs, dvfs_tables=_table())
    return result, build_simulation_evidence(
        result,
        execution_context=ExecutionContext(silicon_rev="EVT1", sw_baseline_ref="sw-x", thermal="room"),
    )


def test_evidence_exposes_the_ledger_and_reporting_adds_tier_columns_only_when_present():
    _, plain = _evidence(SimulationRunConfig(fps=30.0, include_timeline=False))
    dumped = plain.model_dump(mode="json", exclude_none=True)
    assert dumped["dvfs_breakdown"][0]["clock_ledger"]["calculated_mhz"] == 400.0
    assert not has_clock_tier_data(dumped)
    assert "Calc Clk" not in ip_detail_rows(dumped)[0]
    assert "Clock Ledger" not in generate_simulation_report_html(dumped, context=ReportContext(evidence_id="e", scenario_ref="uc-x", variant_ref="v1"))

    cfg = SimulationRunConfig(
        fps=30.0, include_timeline=False, clock_basis="configured",
        configured_clocks={"mtnr": ConfiguredClock(mhz=800.0, reason_code="overflow_guard")},
        measured_clocks={"mtnr": MeasuredClock(mhz=780.0)},
    )
    _, tiered = _evidence(cfg)
    dumped = tiered.model_dump(mode="json", exclude_none=True)
    assert has_clock_tier_data(dumped)
    row = ip_detail_rows(dumped)[0]
    assert (row["Calc Clk"], row["Cfg Clk"], row["Meas Clk"]) == ("400.0", "800.0", "780.0")
    assert row["Clk Gap"] == "+380.0"
    ledger_row = clock_ledger_rows(dumped)[0]
    assert ledger_row["Cfg Reason"] == "overflow_guard" and ledger_row["Cfg-Calc (MHz)"] == "+400.0"
    assert ledger_row["Meas-Cfg (MHz)"] == "-20.0" and ledger_row["Basis"] == "configured"
    html = generate_simulation_report_html(dumped, context=ReportContext(evidence_id="e", scenario_ref="uc-x", variant_ref="v1"))
    assert "Clock Ledger" in html
