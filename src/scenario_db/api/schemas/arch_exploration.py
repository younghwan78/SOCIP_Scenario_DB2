from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from scenario_db.api.schemas.timing_budget import _DvfsSelection
from scenario_db.sim.arch_exploration import ArchExplorationSpec


class ArchExplorationRunRequest(_DvfsSelection):
    """Explore every variant of a scenario type and persist the run."""

    title: str | None = Field(default=None, max_length=200)
    scenario_type: str | None = Field(default=None, max_length=120)
    scenario_ids: list[str] | None = Field(default=None, max_length=50)
    category: str | None = None  # scenario metadata.category, e.g. "camera"
    project_ref: str | None = None
    variant_ids: list[str] | None = Field(default=None, max_length=500)
    include_derived: bool = False
    max_variants: int = Field(default=200, ge=1, le=500)
    spec: ArchExplorationSpec = Field(default_factory=ArchExplorationSpec)
    # EXP-05: per-variant power budget = previous-project reference x (1 + tolerance) from the project review_policy
    # (the tighter of it and spec.constraints.power_budget_mw); variants without a reference keep the spec budget.
    power_budget_from_reference: bool = False

    @model_validator(mode="after")
    def _scope(self) -> ArchExplorationRunRequest:
        if not self.scenario_ids and not self.category:
            raise ValueError("scenario_ids or category is required")
        return self


class PromoteRequest(BaseModel):
    run_id: str
    scenario_id: str | None = None
    variant_ids: list[str] | None = Field(default=None, max_length=500)
    case_key: str | None = None  # non-default choice for exactly one variant
    reason: str | None = Field(default=None, max_length=500)
    # Project the caller believes it is changing; a mismatch with the run's project is refused
    expected_project_ref: str | None = None

    @model_validator(mode="after")
    def _user_choice(self) -> PromoteRequest:
        if self.case_key is not None:
            if not self.variant_ids or len(self.variant_ids) != 1:
                raise ValueError("case_key requires exactly one variant_id")
        return self


class ArchReportRequest(BaseModel):
    run_id: str
    title: str | None = Field(default=None, max_length=200)
    status: str = Field(default="draft", pattern="^draft$")


class ReportStatusRequest(BaseModel):
    status: str = Field(pattern="^(draft|published)$")
    reviewer: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _publish_needs_review(self) -> ReportStatusRequest:
        if self.status == "published" and (not (self.reviewer or "").strip() or not (self.note or "").strip()):
            raise ValueError("publishing requires reviewer and note")
        return self


class PowerOptionReviewRequest(BaseModel):
    """IQ review state of one power-option item (e.g. knob:crop_strategy=byrp_bcrop, mode:mtnr=LowPower)."""

    scenario_id: str
    variant_id: str = Field(default="*", max_length=200)  # '*' = every variant of the scenario
    option_key: str = Field(pattern=r"^(knob|mode):[A-Za-z0-9_.\-]+=[A-Za-z0-9_.\-]+$", max_length=200)
    status: str = Field(pattern="^(candidate|iq_eval|adopted|rejected)$")
    note: str | None = Field(default=None, max_length=1000)
