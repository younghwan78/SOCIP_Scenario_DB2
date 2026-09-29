"""Clock ledger assembly: tier selection (``clock_basis``) and gap analysis.

``select_clock_basis`` decides, per IP, which tier drives the run;
``build_clock_ledger`` records all tiers side by side for one resolved IP.
Both are pure functions over already-resolved data, so the calculated numbers
are never changed by the ledger itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from scenario_db.sim.clock_models import (
    ClockBasis,
    ClockConstraint,
    ClockLedger,
    ConfiguredClock,
    MeasuredClock,
)

if TYPE_CHECKING:
    from scenario_db.sim.models import IPWorkload, ResolvedIPConfig

_EPS = 1e-9
T = TypeVar("T")


@dataclass(frozen=True)
class ClockSelection:
    tier_used: ClockBasis
    mhz: float
    fallback: str | None = None


def lookup_clock(mapping: dict[str, T] | None, workload: IPWorkload) -> T | None:
    """Match a tier value to a workload by node_id, then hw_name, then ip_ref (case-insensitive)."""
    if not mapping:
        return None
    keys = [key for key in (workload.node_id, workload.hw_name, workload.ip_ref) if key]
    for key in keys:
        if key in mapping:
            return mapping[key]
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def select_clock_basis(
    workloads: list[IPWorkload],
    *,
    basis: ClockBasis,
    configured: dict[str, ConfiguredClock],
    measured: dict[str, MeasuredClock],
    warnings: list[str],
) -> dict[str, ClockSelection]:
    """Per-node clock tier for ``basis`` (calculated fallback + warning when data is missing)."""
    selections: dict[str, ClockSelection] = {}
    if basis == "calculated":
        return selections
    tier_map: dict[str, Any] = configured if basis == "configured" else measured
    matched: set[int] = set()
    for workload in workloads:
        value = lookup_clock(tier_map, workload)
        if value is None:
            note = f"no {basis} clock for {workload.node_id}; using the calculated clock"
            selections[workload.node_id] = ClockSelection("calculated", 0.0, note)
            warnings.append(f"clock_basis={basis}: {note}")
            continue
        matched.add(id(value))
        selections[workload.node_id] = ClockSelection(basis, float(value.mhz))
    for key, value in tier_map.items():
        if id(value) not in matched:
            warnings.append(f"clock_basis={basis}: '{key}' matches no simulated IP (node_id / hw_name / ip_ref)")
    return selections


def build_clock_ledger(
    workload: IPWorkload,
    *,
    calculated: ResolvedIPConfig,
    group_max_mhz: float | None,
    basis: ClockBasis,
    selection: ClockSelection | None,
    configured: dict[str, ConfiguredClock],
    measured: dict[str, MeasuredClock],
    warnings: list[str],
) -> ClockLedger:
    throughput = calculated.base_required_clock_mhz
    constraints: list[ClockConstraint] = list(workload.clock_constraints)
    if workload.manual_clock_mhz:
        constraints.append(
            ClockConstraint(
                kind="manual",
                mhz=float(workload.manual_clock_mhz),
                reason="manual_clock_mhz",
                source="node_config.sim",
            )
        )
    pre_alignment = max(throughput, workload.clock_correction_mhz)
    if group_max_mhz is not None and group_max_mhz > pre_alignment + _EPS:
        constraints.append(
            ClockConstraint(
                kind="dvfs_group_align",
                mhz=group_max_mhz,
                reason=f"dvfs_group_align({workload.sim_params.dvfs_group})",
                source="resolver",
            )
        )

    binding_kind: str | None = None
    binding_mhz = 0.0
    for kind, mhz in [("throughput", throughput), *[(c.kind, c.mhz) for c in constraints]]:
        if mhz > binding_mhz + _EPS:
            binding_kind, binding_mhz = kind, mhz

    cfg = lookup_clock(configured, workload)
    meas = lookup_clock(measured, workload)
    calc_set = calculated.set_clock_mhz

    gap: dict[str, object] = {}
    if throughput > 0:
        gap["calculated_over_throughput_pct"] = round((calc_set / throughput - 1.0) * 100.0, 2)
    if cfg is not None:
        gap["configured_minus_calculated_mhz"] = round(cfg.mhz - calc_set, 3)
        if calc_set > 0:
            gap["configured_over_calculated_pct"] = round((cfg.mhz / calc_set - 1.0) * 100.0, 2)
    if meas is not None:
        if cfg is not None:
            gap["measured_minus_configured_mhz"] = round(meas.mhz - cfg.mhz, 3)
        gap["measured_minus_calculated_mhz"] = round(meas.mhz - calc_set, 3)
    if cfg is not None and abs(cfg.mhz - calc_set) > _EPS:
        gap["cause"] = cfg.reason_code
    elif binding_kind not in (None, "throughput"):
        gap["cause"] = binding_kind

    used: ClockBasis = selection.tier_used if selection else "calculated"
    if selection and used != "calculated" and selection.mhz + _EPS < calculated.required_clock_mhz:
        warnings.append(
            f"{workload.node_id}: {used} clock {selection.mhz:.1f}MHz is below the calculated "
            f"requirement {calculated.required_clock_mhz:.1f}MHz"
        )

    return ClockLedger(
        throughput_required_mhz=throughput,
        constraints=constraints,
        binding_kind=binding_kind,
        calculated_required_mhz=calculated.required_clock_mhz,
        calculated_mhz=calc_set,
        configured_mhz=cfg.mhz if cfg else None,
        configured_reason_code=cfg.reason_code if cfg else None,
        configured_note=cfg.note if cfg else None,
        measured_mhz=meas.mhz if meas else None,
        measured_stat=meas.stat if meas else None,
        measured_evidence_ref=meas.evidence_ref if meas else None,
        basis=basis,
        basis_used=used,
        fallback=selection.fallback if selection else None,
        gap=gap,
    )
