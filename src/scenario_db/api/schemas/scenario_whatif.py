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
    model_config = ConfigDict(extra="forbid")
    target: Literal["anchor_size", "node_size", "output_size", "fps", "node_clock_mhz"]
    anchor_id: str | None = Field(default=None, min_length=1, max_length=160)
    node_id: str | None = Field(default=None, min_length=1, max_length=160)
    width: int | None = Field(default=None, ge=16, le=16384)
    height: int | None = Field(default=None, ge=16, le=16384)
    value: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_target(self):
        size = self.target in {"anchor_size", "node_size", "output_size"}
        if size and (self.width is None or self.height is None or self.value is not None):
            raise ValueError("size changes require width/height and no value")
        if not size and (self.value is None or self.width is not None or self.height is not None):
            raise ValueError("FPS/clock changes require value and no width/height")
        if self.target == "anchor_size" and not self.anchor_id:
            raise ValueError("anchor_size requires anchor_id")
        if self.target in {"node_size", "node_clock_mhz"} and not self.node_id:
            raise ValueError("node changes require node_id")
        if self.target not in {"anchor_size", "output_size"} and self.anchor_id is not None:
            raise ValueError("anchor_id is only allowed for anchor/output size")
        if self.target not in {"node_size", "node_clock_mhz"} and self.node_id is not None:
            raise ValueError("node_id is only allowed for node changes")
        if self.target == "fps" and self.value is not None and self.value > 240:
            raise ValueError("FPS must be at most 240")
        if self.target == "node_clock_mhz" and self.value is not None and self.value > 5000:
            raise ValueError("clock must be at most 5000 MHz")
        return self


class WhatIfPlanRequest(WhatIfScope):
    query: str = Field(min_length=1, max_length=2000)


class WhatIfPreviewRequest(WhatIfScope):
    changes: list[WhatIfChange] = Field(min_length=1, max_length=8)
    expected_baseline_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: SimulationRunConfig = Field(default_factory=SimulationRunConfig)
    options: TimingBudgetOptions = Field(default_factory=TimingBudgetOptions)

    @model_validator(mode="after")
    def bounded_condition(self):
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
        keys = [(c.target, c.anchor_id, c.node_id) for c in self.changes]
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
