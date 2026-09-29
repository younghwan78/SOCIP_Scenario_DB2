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
    MeasuredVoltageBasis,
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


def instance_key(workload: IPWorkload) -> str | None:
    """``<ip_ref>#<instance_index>``: the physical-instance key a PMU map can target."""
    return f"{workload.ip_ref}#{workload.instance_index}" if workload.ip_ref else None


def ambiguous_clock_keys(workloads: list[IPWorkload]) -> set[str]:
    """Generic keys (ip_ref / hw_name, lower-case) that name more than one physical instance.

    Nodes sharing an ip_ref *and* instance_index are one HW block time-shared
    by several scenario nodes (e.g. gdc_m / gdc_o), so they are not ambiguous.
    """
    owners: dict[str, set[tuple[str, int]]] = {}
    for workload in workloads:
        physical = (str(workload.ip_ref or workload.hw_name), workload.instance_index)
        for key in (workload.ip_ref, workload.hw_name):
            if key:
                owners.setdefault(str(key).lower(), set()).add(physical)
    return {key for key, found in owners.items() if len(found) > 1}


def lookup_clock(
    mapping: dict[str, T] | None,
    workload: IPWorkload,
    *,
    ambiguous: set[str] | None = None,
) -> T | None:
    """Match a tier value by node_id, ``ip_ref#instance``, ip_ref, hw_name, then DVFS group.

    Matching is case-insensitive. A generic key (ip_ref / hw_name) listed in
    ``ambiguous`` names several physical instances and is never matched: one
    measured value would otherwise be copied onto every instance.
    """
    if not mapping:
        return None
    ambiguous = ambiguous or set()
    specific = [key for key in (workload.node_id, instance_key(workload)) if key]
    generic = [
        key for key in (workload.ip_ref, workload.hw_name)
        if key and str(key).lower() not in ambiguous
    ]
    # A DVFS-domain key (e.g. "CAM") covers every IP on that shared clock,
    # which is how DVFS scenario tables are written.
    if workload.sim_params.dvfs_group:
        generic.append(workload.sim_params.dvfs_group)
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for key in [*specific, *generic]:
        if key in mapping:
            return mapping[key]
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _ambiguous_hit(mapping: dict[str, Any], workload: IPWorkload, ambiguous: set[str]) -> str | None:
    lowered = {str(key).lower(): key for key in mapping}
    for key in (workload.ip_ref, workload.hw_name):
        if key and str(key).lower() in ambiguous and str(key).lower() in lowered:
            return str(lowered[str(key).lower()])
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
    ambiguous = ambiguous_clock_keys(workloads)
    matched: set[int] = set()
    for workload in workloads:
        value = lookup_clock(tier_map, workload, ambiguous=ambiguous)
        if value is None:
            shared = _ambiguous_hit(tier_map, workload, ambiguous)
            if shared is not None:
                note = (
                    f"'{shared}' names several HW instances; key the {basis} clock for "
                    f"{workload.node_id} by node_id or '{instance_key(workload)}'. Using the calculated clock"
                )
            else:
                note = f"no {basis} clock for {workload.node_id}; using the calculated clock"
            selections[workload.node_id] = ClockSelection("calculated", 0.0, note)
            warnings.append(f"clock_basis={basis}: {note}")
            continue
        matched.add(id(value))
        selections[workload.node_id] = ClockSelection(basis, float(value.mhz))
    for key, value in tier_map.items():
        # Only hand-authored configured clocks are worth flagging: a measurement
        # normally covers IPs that are not part of the simulated scenario.
        if basis == "configured" and id(value) not in matched:
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
    ambiguous: set[str] | None = None,
    measured_voltage_basis: MeasuredVoltageBasis | None = None,
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

    cfg = lookup_clock(configured, workload, ambiguous=ambiguous)
    meas = lookup_clock(measured, workload, ambiguous=ambiguous)
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
        configured_source=cfg.source if cfg else None,
        measured_mhz=meas.mhz if meas else None,
        measured_stat=meas.stat if meas else None,
        measured_evidence_ref=meas.evidence_ref if meas else None,
        measured_residency=(
            {f"{mhz:g}": round(share, 6) for mhz, share in meas.residency.items()}
            if meas and meas.residency
            else None
        ),
        measured_voltage_basis=measured_voltage_basis if used == "measured" else None,
        basis=basis,
        basis_used=used,
        fallback=selection.fallback if selection else None,
        gap=gap,
    )
