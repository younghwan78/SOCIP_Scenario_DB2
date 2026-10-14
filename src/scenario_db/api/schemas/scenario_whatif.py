"""Bounded, explicit What-if conditions and frozen experiment records."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.timing_budget import TimingBudgetOptions


class WhatIfScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_ref: str = Field(min_length=1, max_length=160)
    scenario_id: str = Field(min_length=1, max_length=160)
    variant_id: str = Field(min_length=1, max_length=160)


class WhatIfChange(BaseModel):
    """One condition; ``target`` names a registered ChangeKind (whatif_conditions.CHANGE_KINDS)."""
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=40)
    anchor_id: str | None = Field(default=None, min_length=1, max_length=160)
    node_id: str | None = Field(default=None, min_length=1, max_length=160)
    stream_id: str | None = Field(default=None, min_length=1, max_length=40)
    param: str | None = Field(default=None, min_length=1, max_length=60)
    width: int | None = Field(default=None, ge=16, le=16384)
    height: int | None = Field(default=None, ge=16, le=16384)
    value: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_target(self):
        from scenario_db.api.services.whatif_conditions import CHANGE_KINDS, param_max
        kind = CHANGE_KINDS.get(self.target)
        if kind is None:
            raise ValueError(f"unsupported What-if target: {self.target} (supported: {', '.join(CHANGE_KINDS)})")
        if kind.shape == "size" and (self.width is None or self.height is None or self.value is not None):
            raise ValueError("size changes require width/height and no value")
        if kind.shape == "value" and (self.value is None or self.width is not None or self.height is not None):
            raise ValueError("FPS/clock changes require value and no width/height")
        for name in ("anchor_id", "node_id", "stream_id"):
            given = getattr(self, name) is not None
            if name == kind.selector and not given and not kind.selector_optional:
                raise ValueError({"anchor_id": "anchor_size requires anchor_id", "node_id": "node changes require node_id",
                                  "stream_id": "stream_size requires stream_id"}[name])
            if name != kind.selector and given:
                raise ValueError(f"{name} is only allowed for targets selected by {name}")
        if kind.needs_param != (self.param is not None):
            raise ValueError("param is required for node_param and not allowed otherwise")
        limit = param_max(self.param) if kind.needs_param else kind.max_value
        if limit is not None and self.value is not None and self.value > limit:
            raise ValueError(f"{self.target} must be at most {limit:g}" + (" (FPS must be at most 240)" if self.target == "fps" else ""))
        return self


class WhatIfModelSettings(WhatIfScope):
    config: SimulationRunConfig = Field(default_factory=SimulationRunConfig)
    options: TimingBudgetOptions = Field(default_factory=TimingBudgetOptions)

    @model_validator(mode="after")
    def bounded_model_settings(self):
        if self.config.timing_profile is not None or self.config.sw_timing_projection is not None:
            raise ValueError("measured replay/projection cannot be extrapolated by What-if")
        if self.config.sensor_modes or self.config.sensor_readout:
            raise ValueError("select catalog sensor modes in Sensor Explore before What-if")
        if (self.config.measured_clock_ref or self.config.measured_clocks or self.config.clock_basis == "measured"
                or self.config.cpu_profile_ref or self.config.cpu_profile is not None):
            raise ValueError("measured clock/CPU replay cannot be extrapolated by What-if")
        if self.options.cpu_model == "profile" or self.options.cpu_profile_ref or self.options.cpu_profile is not None:
            raise ValueError("measured CPU replay cannot be extrapolated by What-if")
        if self.options.task_runtime:
            raise ValueError("measured task runtime cannot be extrapolated by What-if")
        if self.options.include_whatif:
            raise ValueError("nested What-if sweeps are not supported")
        return self


class WhatIfPlanRequest(WhatIfModelSettings):
    query: str = Field(min_length=1, max_length=2000)


class WhatIfPreviewRequest(WhatIfModelSettings):
    changes: list[WhatIfChange] = Field(min_length=1, max_length=8)
    expected_baseline_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def bounded_condition(self):
        keys = [(c.target, c.anchor_id, c.node_id, c.stream_id, c.param) for c in self.changes]
        if len(keys) != len(set(keys)):
            raise ValueError("each change target can appear only once")
        return self


class WhatIfExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_request: WhatIfPreviewRequest
    expected_condition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=200)
    purpose: str | None = Field(default=None, max_length=4000)
    description: str | None = Field(default=None, max_length=12000)
    assumptions: str | None = Field(default=None, max_length=6000)
    conclusion: str | None = Field(default=None, max_length=6000)
    query: str | None = Field(default=None, max_length=2000)
    visibility: Literal["private", "shared"] = "private"
