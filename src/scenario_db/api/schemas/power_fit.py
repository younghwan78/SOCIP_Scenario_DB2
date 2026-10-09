from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class PowerFitRequest(BaseModel):
    """Fit CPU / IP / BW power factors to the project's measurements (read-only proposal)."""

    project_ref: str
    scenario_id: str | None = None
    base_params_ref: str | None = None      # default: the config profile's power_params_ref
    config_profile_ref: str | None = None
    include_synthetic: bool = False
    statistic: Literal["min", "mean", "max"] = "mean"
    measured_sw: bool = True                # use the measured SW runtime as input where the measurement has it


class PowerParamsCreateRequest(BaseModel):
    """New draft power_model_params version = base x accepted factors (category -> k; None / 1 = unchanged)."""

    base_params_ref: str
    factors: dict[Literal["cpu", "ip", "bw"], Annotated[float, Field(ge=0.2, le=5.0, allow_inf_nan=False)] | None]
    source_evidence: list[str] = Field(default_factory=list, max_length=500)
    statistic: Literal["min", "mean", "max"] = "mean"
    measured_sw: bool = True
    synthetic_rows: int = 0
    fit_stats: dict[str, dict] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=500)
