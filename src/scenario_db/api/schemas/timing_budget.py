from __future__ import annotations

from pydantic import BaseModel, Field

from scenario_db.models.common import DocumentId
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.models import DVFSTable, SimulationRunConfig
from scenario_db.sim.timing_budget import TimingBudgetOptions


class _DvfsSelection(BaseModel):
    config: SimulationRunConfig = Field(default_factory=SimulationRunConfig)
    config_profile_ref: str | None = None
    dvfs_tables: dict[str, DVFSTable] = Field(default_factory=dict)
    dvfs_table_ref: DocumentId | None = None
    soc_ref: DocumentId | None = None
    dvfs_version: int | None = Field(default=None, ge=0)
    use_default_dvfs: bool = True


class TimingBudgetRequest(_DvfsSelection):
    """Read-only stage timing budget for one scenario variant."""

    scenario_id: str
    variant_id: str
    options: TimingBudgetOptions = Field(default_factory=TimingBudgetOptions)


class TimingBudgetDvfsWhatIfRequest(TimingBudgetRequest):
    """Each DVFS domain pinned k levels faster (+) / slower (-) than resolved; one budget run per cell."""

    shifts: list[int] = Field(default_factory=lambda: [-2, -1, 1, 2], min_length=1, max_length=6)
    domains: list[str] | None = Field(default=None, max_length=12)
    # several domains moved together, e.g. [{"CAM": -1, "INTCAM": -1}] (TIM-05)
    combos: list[dict[str, int]] | None = Field(default=None, max_length=8)


class TimingBudgetDistributionRequest(TimingBudgetRequest):
    """③ box plot: per-frame SW variance (min..max) over a few seeded trials (read-only)."""

    trials: int = Field(default=8, ge=1, le=16)
    frames: int = Field(default=24, ge=8, le=48)


class TimingBudgetRegisterRequest(TimingBudgetRequest):
    """Register the Timing Budget condition as the variant's current prediction (single-case exploration run)."""

    reason: str = Field(min_length=1, max_length=500)
    expected_project_ref: str | None = None


class TimingBudgetEvidenceRequest(TimingBudgetRequest):
    """Keep the condition's budget run as simulation evidence (deterministic id per condition)."""

    execution_context: ExecutionContext | None = None


class TimingBudgetFleetRequest(_DvfsSelection):
    scenario_id: str
    variant_ids: list[str] | None = Field(default=None, max_length=200)
    include_derived: bool = False
    options: TimingBudgetOptions = Field(default_factory=TimingBudgetOptions)


class TimingBudgetResponse(BaseModel):
    scenario_id: str
    variant_id: str
    config_profile_ref: str | None = None
    dvfs_table_ref: str | None = None
    report: dict


class TimingBudgetFleetResponse(BaseModel):
    scenario_id: str
    config_profile_ref: str | None = None
    dvfs_table_ref: str | None = None
    rows: list[dict]
    errors: list[dict] = Field(default_factory=list)
