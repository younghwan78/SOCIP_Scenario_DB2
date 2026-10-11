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
    # set by Timing Budget registration: the condition as the user chose it (e.g. which measurement fed which input)
    timing_budget: dict | None = None
    # power-option items (knob:/mode: keys) applied to every explored variant before the search; used to register
    # a prediction that includes IQ-adopted options (the option axis itself is then not explored)
    apply_options: list[str] | None = Field(default=None, max_length=16)

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


OPTION_KEY = r"^(knob|mode):[A-Za-z0-9_.\-]+=[A-Za-z0-9_.\-]+$"


class IqResult(BaseModel):
    """Image-quality evaluation result of one power-option item, entered when registering with that option."""

    option_key: str = Field(pattern=OPTION_KEY, max_length=200)
    status: str = Field(pattern="^(adopted|rejected)$")
    note: str = Field(min_length=1, max_length=1000)


class LeverRegisterRequest(BaseModel):
    """Register the combination chosen in the lever selector as the variant's current prediction.

    compression: buffer -> mode (e.g. COMP_YUV_LOSSLESS) at the resolved DVFS levels of the objective slice.
    options: power-option items; each needs an IQ result (adopted) in ``iq_results`` — rejected items stop the
    registration and are recorded as rejected.
    """

    run_id: str
    scenario_id: str
    variant_id: str
    compression: dict[str, str] = Field(default_factory=dict)
    options: list[str] = Field(default_factory=list, max_length=16)
    iq_results: list[IqResult] = Field(default_factory=list, max_length=16)
    reason: str | None = Field(default=None, max_length=500)
    expected_project_ref: str | None = None

    @model_validator(mode="after")
    def _options(self) -> LeverRegisterRequest:
        import re

        bad = [o for o in self.options if not re.match(OPTION_KEY, o)]
        if bad:
            raise ValueError(f"invalid option keys: {bad}")
        return self
