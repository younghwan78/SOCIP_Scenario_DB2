from __future__ import annotations

from pydantic import BaseModel, Field

from scenario_db.sim.models import CpuProfile


class CpuWhatIfRequest(BaseModel):
    """Placement / frequency what-if on a (possibly different) SoC CPU topology."""

    cpu_profile_ref: str | None = None          # measurement evidence id
    cpu_profile: CpuProfile | None = None       # or inline
    power_params_ref: str                       # target SoC topology (id or id@version)
    base_power_params_ref: str | None = None    # measured SoC topology when it differs
    fps: float = Field(default=30.0, gt=0, le=1000)
    growth: dict[str, float] = Field(default_factory=dict)
    default_growth: float = Field(default=1.0, gt=0, le=10)
    candidates: dict[str, list[str]] = Field(default_factory=dict)
    budgets_ms: dict[str, float] = Field(default_factory=dict)
    util_cap: float = Field(default=0.8, gt=0, le=1)
    power_gating_eff: float = Field(default=0.9, ge=0, le=1)
    cpu_bw_scale: float = Field(default=1.0, gt=0, le=10)
    max_cases: int = Field(default=5000, ge=1, le=20000)


class CpuWhatIfResponse(BaseModel):
    profile_ref: str | None = None
    power_params_ref: str
    result: dict
