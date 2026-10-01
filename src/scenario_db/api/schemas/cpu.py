from __future__ import annotations

from typing import Literal

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


Knob = Literal["pin", "upto", "uclamp_max", "uclamp_min"]
DEFAULT_KNOBS: tuple[Knob, ...] = ("pin", "upto")


class CpuTaskPolicyIn(BaseModel):
    allowed: list[str] | None = None
    uclamp_min: int | None = Field(default=None, ge=0, le=1024)
    uclamp_max: int | None = Field(default=None, ge=0, le=1024)
    prefer_idle: bool = False
    threads: int | None = Field(default=None, ge=1, le=64)


class CpuSweepRequest(BaseModel):
    """EAS reproduction of a measured CPU profile + automatic cpuset / uclamp knob sweep."""

    cpu_profile_ref: str | None = None
    cpu_profile: CpuProfile | None = None
    power_params_ref: str
    base_power_params_ref: str | None = None
    fps: float = Field(default=30.0, gt=0, le=1000)
    growth: dict[str, float] = Field(default_factory=dict)
    default_growth: float = Field(default=1.0, gt=0, le=10)
    budgets_ms: dict[str, float] = Field(default_factory=dict)
    threads: dict[str, int] = Field(default_factory=dict)
    sweep_clusters: dict[str, list[str]] = Field(default_factory=dict)   # task -> clusters; missing = auto
    knobs: list[Knob] = Field(default_factory=lambda: list(DEFAULT_KNOBS))
    uclamp_max_levels: list[int] = Field(default_factory=list)
    uclamp_min_levels: list[int] = Field(default_factory=list)
    task_policy: dict[str, CpuTaskPolicyIn] = Field(default_factory=dict)
    reference: Literal["measured", "eas"] = "measured"
    power_gating_eff: float = Field(default=0.9, ge=0, le=1)
    cpu_bw_scale: float = Field(default=1.0, gt=0, le=10)
    freq_margin: float | None = Field(default=None, ge=1.0, le=3.0)
    fits_margin: float | None = Field(default=None, ge=1.0, le=3.0)
    util_model: Literal["util_est", "pelt_avg"] | None = None
    pelt_halflife_ms: float | None = Field(default=None, ge=1.0, le=128.0)
    deadline_boost: bool | None = None
    energy_includes_static: bool | None = None
    max_cases: int = Field(default=3000, ge=1, le=20000)
    top: int = Field(default=60, ge=1, le=500)
