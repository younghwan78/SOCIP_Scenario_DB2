"""Clock ledger data types (pure pydantic, no engine imports).

A ledger keeps every clock *tier* of one IP side by side so a report can
explain "why does this IP run 40% above what the workload needs":

- ``calculated``: max(throughput, all constraints) snapped to a DVFS level.
  Every constraint is preserved, not only the largest one.
- ``configured``: what BSP / device tree / kernel actually sets, with a reason
  code (``ConfiguredClock``; declared per project in ``sim.config_profile``).
- ``measured``: PMU / perfetto clock residency reduced to one number per IP.
- ``gap``: derived differences between the tiers.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from scenario_db.models.common import BaseScenarioModel

ClockBasis = Literal["calculated", "configured", "measured"]
ConfiguredClockReason = Literal["overflow_guard", "vvalid", "bsp_default", "thermal", "other"]
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


class MeasuredClock(BaseScenarioModel):
    mhz: float = Field(gt=0, allow_inf_nan=False)
    stat: MeasuredClockStat = "weighted_mean"
    evidence_ref: str | None = None
    source: str | None = None


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
    measured_mhz: float | None = None
    measured_stat: MeasuredClockStat | None = None
    measured_evidence_ref: str | None = None
    basis: ClockBasis = "calculated"
    basis_used: ClockBasis = "calculated"
    fallback: str | None = None
    gap: dict[str, Any] = Field(default_factory=dict)
