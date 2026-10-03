from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from scenario_db.sim.models import CpuProfile

Growth = Annotated[float, Field(gt=0, le=10, allow_inf_nan=False)]
Budget = Annotated[float, Field(gt=0, allow_inf_nan=False)]
ThreadCount = Annotated[int, Field(ge=1, le=64)]
ClampLevel = Annotated[int, Field(ge=0, le=1024)]
Mhz = Annotated[float, Field(gt=0, le=20000, allow_inf_nan=False)]
DsuMode = Literal["auto", "vote", "proportional", "measured", "fixed"]


class CpuWhatIfRequest(BaseModel):
    """Placement / frequency what-if on a (possibly different) SoC CPU topology."""

    cpu_profile_ref: str | None = None          # measurement evidence id
    cpu_profile: CpuProfile | None = None       # or inline
    power_params_ref: str                       # target SoC topology (id or id@version)
    base_power_params_ref: str | None = None    # measured SoC topology when it differs
    fps: float = Field(default=30.0, gt=0, le=1000)
    growth: dict[str, Growth] = Field(default_factory=dict)
    default_growth: float = Field(default=1.0, gt=0, le=10)
    candidates: dict[str, Annotated[list[str], Field(min_length=1)]] = Field(default_factory=dict)
    budgets_ms: dict[str, Budget] = Field(default_factory=dict)
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
    growth: dict[str, Growth] = Field(default_factory=dict)
    default_growth: float = Field(default=1.0, gt=0, le=10)
    budgets_ms: dict[str, Budget] = Field(default_factory=dict)
    threads: dict[str, ThreadCount] = Field(default_factory=dict)
    sweep_clusters: dict[str, list[str]] = Field(default_factory=dict)   # task -> clusters; missing = auto
    knobs: list[Knob] = Field(default_factory=lambda: list(DEFAULT_KNOBS))
    uclamp_max_levels: list[ClampLevel] = Field(default_factory=list)
    uclamp_min_levels: list[ClampLevel] = Field(default_factory=list)
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
    # DSU <-> cluster clock coupling (architecture-phase assumption): auto = topology vote table if any,
    # else the measured residency, else proportional. dsu_vote overrides the topology table (experiment).
    dsu_mode: DsuMode = "auto"
    dsu_vote: dict[str, Annotated[list[tuple[Mhz, Mhz]], Field(min_length=1)]] | None = None
    dsu_fixed_mhz: Mhz | None = None
