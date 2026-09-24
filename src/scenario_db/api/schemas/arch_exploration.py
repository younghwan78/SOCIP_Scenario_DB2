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

    @model_validator(mode="after")
    def _user_choice(self) -> PromoteRequest:
        if self.case_key is not None:
            if not self.variant_ids or len(self.variant_ids) != 1:
                raise ValueError("case_key requires exactly one variant_id")
        return self


class ArchReportRequest(BaseModel):
    run_id: str
    title: str | None = Field(default=None, max_length=200)
    status: str = Field(default="draft", pattern="^(draft|published)$")


class ReportStatusRequest(BaseModel):
    status: str = Field(pattern="^(draft|published)$")
