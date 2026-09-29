"""Per-project / per-SoC simulation configuration profiles.

Correlation work (matching prediction against silicon) converges through
human iteration: a team agrees on coefficients and settings, reruns, reviews,
and adjusts. Those agreed settings must be reproducible data — not values
someone retypes into an API request body. A ``sim.config_profile`` document
captures them:

- ``run_config``: defaults for ``SimulationRunConfig`` fields. Anything the
  request sets explicitly still wins (profile < request), so per-run
  experiments never require editing the profile.
- ``rail_domain_map``: declared physical-buck -> power-domain mapping for
  this project's bench, complementing the per-evidence ``domain`` fields.
- ``version`` / ``status`` / ``approved_by``: which agreed state produced a
  result. Evidence stamps ``run.config_profile_ref`` when a profile is used.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from scenario_db.models.common import (
    BaseScenarioModel,
    DocumentId,
    SchemaVersion,
)
from scenario_db.sim.clock_models import ClockBasis, ConfiguredClock, MeasuredClockStat


class SimConfigRunDefaults(BaseScenarioModel):
    """Optional defaults for SimulationRunConfig — None means 'not pinned'."""

    asv_group: int | None = None
    fps: float | None = None
    sw_margin: float | None = None
    bw_power_coeff: float | None = None
    vbat: float | None = None
    pmic_efficiency: float | None = None
    h_blank_margin: float | None = None
    power_model: str | None = None
    bw_power_model: str | None = None
    bw_power_mw_per_gbps: float | None = None
    power_params_ref: str | None = None
    # Clock ledger: configured (BSP / DT / kernel) clocks per node_id / hw_name /
    # ip_ref, each with a mandatory reason code (validated at ETL), and which
    # tier drives the run. None = not pinned (calculated clock).
    clock_basis: ClockBasis | None = None
    configured_clocks: dict[str, ConfiguredClock] | None = None
    # Per DVFS scenario (variant dvfs_sn) configured clocks; overrides the
    # project-wide map above for variants running that DVFS scenario.
    configured_clocks_by_dvfs_sn: dict[str, dict[str, ConfiguredClock]] | None = None
    measured_clock_ref: str | None = None
    measured_clock_stat: MeasuredClockStat | None = None
    memory_rail: str | None = None
    dvfs_overrides: dict[str, int] = Field(default_factory=dict)


class SimConfigProfile(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["sim.config_profile"]
    project_ref: DocumentId | None = None
    soc_ref: DocumentId | None = None
    version: int = Field(default=1, ge=1)
    status: Literal["draft", "approved"] = "draft"
    approved_by: str | None = None
    description: str | None = None
    run_config: SimConfigRunDefaults = Field(default_factory=SimConfigRunDefaults)
    # Physical bench rail name -> logical power domain (e.g. MIF, CPU, CAM).
    rail_domain_map: dict[str, str] = Field(default_factory=dict)
    notes: str | None = None
