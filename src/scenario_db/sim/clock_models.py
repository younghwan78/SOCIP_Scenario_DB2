"""Clock ledger data types (pure pydantic, no engine imports).

A ledger keeps every clock *tier* of one IP side by side so a report can
explain "why does this IP run 40% above what the workload needs":

- ``calculated``: max(throughput, all constraints) snapped to a DVFS level.
  Every constraint is preserved, not only the largest one.
- ``configured``: what BSP / device tree / kernel actually sets, with a reason
  code (``ConfiguredClock``; declared per project in ``sim.config_profile``).
- ``measured``: PMU / perfetto clock residency reduced to one number per IP.
  When the per-level residency is known it is kept, because a residency-
  weighted mean clock is not an operating point: power is then evaluated as
  the residency-weighted V^2 over the levels actually visited.
- ``gap``: derived differences between the tiers.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from scenario_db.models.common import BaseScenarioModel

ClockBasis = Literal["calculated", "configured", "measured"]
ConfiguredClockReason = Literal[
    "overflow_guard", "vvalid", "bsp_default", "dvfs_scenario", "qos_lock", "thermal", "other"
]
# Where a configured clock came from, lowest to highest precedence.
ConfiguredClockSource = Literal["project", "dvfs_scenario", "variant"]
MeasuredVoltageBasis = Literal["level", "residency_weighted", "snapped_mean"]
MeasuredClockStat = Literal["weighted_mean", "dominant", "mean", "max"]


class ClockConstraint(BaseScenarioModel):
    """One lower bound on an IP clock (kind e.g. mipi_ingress, vvalid_stream, otf_align, manual)."""

    kind: str
    mhz: float
    reason: str | None = None
    source: str | None = None


class ConfiguredClock(BaseScenarioModel):
    mhz: float = Field(gt=0, allow_inf_nan=False)
    reason_code: ConfiguredClockReason
    note: str | None = None
    owner: str | None = None
    ticket: str | None = None
    # Filled by the adapter when the effective per-variant clocks are resolved.
    source: ConfiguredClockSource | None = None


class MeasuredClock(BaseScenarioModel):
    mhz: float = Field(gt=0, allow_inf_nan=False)
    stat: MeasuredClockStat = "weighted_mean"
    evidence_ref: str | None = None
    source: str | None = None
    # {MHz: time share} over the DVFS levels visited during the capture
    # (normalised to 1.0). Present only when the PMU data had residency.
    residency: dict[float, float] | None = None

    @field_validator("residency")
    @classmethod
    def _normalise_residency(cls, value: dict[float, float] | None) -> dict[float, float] | None:
        if not value:
            return None
        if any(mhz <= 0 or share < 0 for mhz, share in value.items()):
            raise ValueError("residency needs positive MHz keys and non-negative shares")
        total = sum(value.values())
        if total <= 0:
            return None
        return {float(mhz): share / total for mhz, share in sorted(value.items()) if share > 0}

    @property
    def dominant_mhz(self) -> float:
        """Highest-residency level (ties: the higher clock); the clock itself without residency."""
        if not self.residency:
            return self.mhz
        return max(self.residency.items(), key=lambda item: (item[1], item[0]))[0]


class ClockLedger(BaseScenarioModel):
    throughput_required_mhz: float = 0.0
    constraints: list[ClockConstraint] = Field(default_factory=list)
    # The constraint (or "throughput") that set the calculated required clock.
    binding_kind: str | None = None
    calculated_required_mhz: float = 0.0
    calculated_mhz: float = 0.0
    configured_mhz: float | None = None
    configured_reason_code: ConfiguredClockReason | None = None
    configured_note: str | None = None
    configured_source: ConfiguredClockSource | None = None
    measured_mhz: float | None = None
    measured_stat: MeasuredClockStat | None = None
    measured_evidence_ref: str | None = None
    # MHz (as text, JSON keys) -> time share, when residency drove the power.
    measured_residency: dict[str, float] | None = None
    # How the measured tier set the voltage: a real DVFS level, the residency-
    # weighted V^2 over visited levels, or a mean snapped up to a level (no
    # residency available; over-estimates power).
    measured_voltage_basis: MeasuredVoltageBasis | None = None
    basis: ClockBasis = "calculated"
    basis_used: ClockBasis = "calculated"
    fallback: str | None = None
    gap: dict[str, Any] = Field(default_factory=dict)
