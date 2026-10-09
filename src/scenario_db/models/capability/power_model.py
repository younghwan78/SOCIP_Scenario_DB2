"""SoC-scoped power model parameters (``kind: power_model_params``).

The power *model code* stays in ``sim/power_model.py`` / ``sim/bw_power.py``;
the *coefficients* a project calibrates live here as data, so a new process
node or a calibration round never needs a code change:

- ``ref_voltage_mv`` / ``ref_fps``: the operating point ``unit_power_mw_mp``
  was characterised at (previously global constants).
- ``bw_model`` + ``bw``: which BW power model to use and its coefficients
  (e.g. ``linear-per-gbps`` with ``mw_per_gbps: 50``).
- ``cpu``: the SoC's CPU topology — any number of clusters (core type, core
  count, logical CPU ids, EM OPP table or ``uW / MHz / V^2`` coefficient,
  leakage, measured rail) plus the DSU — for the SW/CPU power estimate.
- ``calibration``: which measurements the numbers were fitted from
  (lineage; ``factor_by_ip`` is recorded only) and ``ip_power_scale``, the
  fitted IP power factor the engine applies (empty = none).

Every field is optional: an absent field falls back to the code constant, so
a partial params document never changes anything it does not mention.
Applying params is opt-in per run (``SimulationRunConfig.power_params_ref``).
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion


class MifOpp(BaseScenarioModel):
    """One MIF (memory interface / DRAM) DVFS level for the ``mif-linear`` BW model."""

    mhz: float = Field(gt=0, allow_inf_nan=False)
    # Memory-rail power at this level with no traffic (fitted intercept).
    base_mw: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    # Deliverable DRAM bandwidth at this level (governor capacity).
    capacity_mbs: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class BwFitInfo(BaseScenarioModel):
    """Lineage of fitted BW coefficients (sim/bw_fit.py)."""

    method: str = "least_squares"
    rows: int = Field(default=0, ge=0)
    r2: float | None = None
    rmse_mw: float | None = None
    source: str | None = None


class BwPowerParams(BaseScenarioModel):
    mw_per_gbps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    llc_hit_scale: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    # --- mif-linear: P_mem = base(MIF level) + e_rd * RD[GB/s] + e_wr * WR[GB/s] ---
    e_read_mw_per_gbps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    e_write_mw_per_gbps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    mif_opps: list[MifOpp] = Field(default_factory=list, exclude_if=lambda v: not v)
    # Governor: lowest level whose capacity x util covers DRAM traffic.
    governor_util: float = Field(default=0.6, gt=0, le=1, allow_inf_nan=False, exclude_if=lambda v: v == 0.6)
    # Scenario QoS floor (IS_DVFS_SN_* -> minimum MIF MHz).
    qos_lock_mhz_by_dvfs_sn: dict[str, float] = Field(default_factory=dict, exclude_if=lambda v: not v)
    # Traffic of masters the scenario does not model (GPU / DPU / modem), MB/s.
    other_masters_mbs: float = Field(default=0.0, ge=0, allow_inf_nan=False, exclude_if=lambda v: v == 0.0)
    # Unset mif-linear fields are omitted from dumps so existing params hashes stay stable.
    fit: BwFitInfo | None = None

    @model_validator(mode="after")
    def _sorted_levels(self) -> BwPowerParams:
        if self.mif_opps != sorted(self.mif_opps, key=lambda o: o.mhz):
            raise ValueError("bw.mif_opps must be sorted by mhz")
        return self


class CpuOpp(BaseScenarioModel):
    """One DVFS operating point of a CPU cluster (or the DSU)."""

    mhz: float = Field(gt=0, allow_inf_nan=False)
    mv: float = Field(gt=0, allow_inf_nan=False)
    # Dynamic power of ONE core at 100% utilisation at this OPP (Energy-Model
    # table). For the DSU: the DSU itself at 100% activity. None = derive from
    # the cluster ``coeff_uw_per_mhz_v2`` (coeff * f * V^2).
    mw_per_core: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class CpuLeakage(BaseScenarioModel):
    """Static power per core: mw_per_core_at_ref * (V / ref_mv) ** exponent."""

    mw_per_core_at_ref: float = Field(ge=0, allow_inf_nan=False)
    ref_mv: float = Field(gt=0, allow_inf_nan=False)
    exponent: float = Field(default=2.0, ge=0, le=10, allow_inf_nan=False)


class CpuClusterParams(BaseScenarioModel):
    """One CPU cluster. Cluster count / composition is per SoC (data, not code).

    e.g. Exynos2600: MID_LF x3, MID_LF x3, MID_HF x3, BIG x1 (+ DSU).
    Either ``opps`` (EM table) or ``coeff_uw_per_mhz_v2`` must be given.
    """

    name: str = Field(min_length=1)
    coeff_uw_per_mhz_v2: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    core_type: str | None = None          # micro-architecture id, reused across SoCs
    cores: int = Field(default=1, ge=1)
    cpus: list[int] = Field(default_factory=list)   # logical CPU ids in traces
    dvfs_domain: str | None = None
    opps: list[CpuOpp] = Field(default_factory=list)
    leakage: CpuLeakage | None = None
    rail: str | None = None               # measured rail name (calibration join)
    ipc_rel: float | None = Field(default=None, gt=0, allow_inf_nan=False)  # vs reference core type

    @model_validator(mode="after")
    def _power_source(self) -> CpuClusterParams:
        if self.coeff_uw_per_mhz_v2 is None and (not self.opps or any(o.mw_per_core is None for o in self.opps)):
            raise ValueError(f"cpu cluster '{self.name}' needs coeff_uw_per_mhz_v2 or opps[].mw_per_core")
        if self.opps != sorted(self.opps, key=lambda o: o.mhz):
            raise ValueError(f"cpu cluster '{self.name}' opps must be sorted by mhz")
        if len({o.mhz for o in self.opps}) != len(self.opps):
            raise ValueError(f"cpu cluster '{self.name}' opp frequencies must be unique")
        if self.cpus and len(self.cpus) != self.cores:
            raise ValueError(f"cpu cluster '{self.name}' lists {len(self.cpus)} cpus for {self.cores} cores")
        return self


class CpuDsuVote(BaseScenarioModel):
    """DSU frequency one cluster requests (DSU <-> cluster clock coupling).

    ``points`` = ascending ``[cluster_mhz, dsu_min_mhz]`` steps: a cluster running at
    ``f`` votes the ``dsu_min_mhz`` of the first point with ``cluster_mhz >= f`` (the
    last point above the table). The DSU runs at the highest vote of the busy clusters.
    In the architecture phase this table is an assumption (``CpuDsuParams.vote_source``).
    """

    cluster: str = Field(min_length=1)    # cluster name or core_type
    points: list[tuple[float, float]] = Field(min_length=1)

    @model_validator(mode="after")
    def _points_valid(self) -> CpuDsuVote:
        for f, d in self.points:
            if not (f > 0 and d > 0) or f != f or d != d:
                raise ValueError(f"DSU vote '{self.cluster}': frequencies must be positive")
        fs = [f for f, _ in self.points]
        if fs != sorted(fs) or len(set(fs)) != len(fs):
            raise ValueError(f"DSU vote '{self.cluster}': cluster_mhz must be strictly ascending")
        ds = [d for _, d in self.points]
        if ds != sorted(ds):
            raise ValueError(f"DSU vote '{self.cluster}': dsu_min_mhz must not decrease")
        return self


class CpuDsuParams(BaseScenarioModel):
    """DynamIQ Shared Unit (L3 / snoop control), shared by all clusters."""

    name: str = "DSU"
    opps: list[CpuOpp] = Field(default_factory=list)
    leakage: CpuLeakage | None = None
    rail: str | None = None
    # cluster -> DSU clock coupling; None = not modelled (measured residency or proportional fallback).
    # None (not []) keeps params_ref of existing documents unchanged (hash drops None fields).
    vote: list[CpuDsuVote] | None = None
    vote_source: Literal["estimate", "ect", "measured"] | None = None

    @model_validator(mode="after")
    def _opps_valid(self) -> CpuDsuParams:
        if any(o.mw_per_core is None for o in self.opps):
            raise ValueError("DSU opps need mw_per_core at every frequency")
        if self.opps != sorted(self.opps, key=lambda o: o.mhz) or len({o.mhz for o in self.opps}) != len(self.opps):
            raise ValueError("DSU opps must be sorted with unique frequencies")
        return self


class CpuTaskPolicy(BaseScenarioModel):
    """Android scheduling attributes of one SW task (cpuset / affinity, uclamp, prefer_idle)."""

    allowed: list[str] | None = None      # cluster names or core types (cpuset / affinity); None = all
    uclamp_min: int | None = Field(default=None, ge=0, le=1024)
    uclamp_max: int | None = Field(default=None, ge=0, le=1024)
    prefer_idle: bool = False             # latency-sensitive: take an idle CPU before saving energy
    threads: int | None = Field(default=None, ge=1, le=64)   # when the profile has no per-thread data


class CpuSchedulerParams(BaseScenarioModel):
    """Scheduler / governor approximation for the CPU what-if (default: Linux EAS + schedutil).

    Vendor kernels (e.g. Exynos EMS + ego) differ in margins and heuristics: tune
    the numbers here per SoC / SW baseline; add a ``model`` when the heuristic
    differs in kind. ``capacity`` takes the device's ``cpu_capacity`` (sysfs,
    0..1024) per cluster; unset = derived from ``ipc_rel * fmax``.
    """

    model: Literal["eas", "ideal"] = "eas"
    freq_margin: float = Field(default=1.25, ge=1.0, le=3.0, allow_inf_nan=False)   # schedutil util->freq
    fits_margin: float = Field(default=1.25, ge=1.0, le=3.0, allow_inf_nan=False)   # fits_capacity
    # Task util seen by the scheduler: "util_est" = PELT peak of a once-per-frame
    # activation (Android util_est), "pelt_avg" = PELT average (= duty cycle).
    util_model: Literal["util_est", "pelt_avg"] = "util_est"
    pelt_halflife_ms: float = Field(default=32.0, ge=1.0, le=128.0, allow_inf_nan=False)  # 32 / 16 / 8 (pelt multiplier)
    # Tasks with a time budget get at least the OPP that meets it (ADPF performance
    # hint / uclamp_min boost by the HAL). False = plain schedutil (may miss budgets).
    deadline_boost: bool = True
    capacity: dict[str, float] = Field(default_factory=dict)
    energy_includes_static: bool = False  # Linux EM compares dynamic energy only
    task_policy: dict[str, CpuTaskPolicy] = Field(default_factory=dict)
    source: str | None = None

    @model_validator(mode="after")
    def _capacity_range(self) -> CpuSchedulerParams:
        bad = {k: v for k, v in self.capacity.items() if not 0 < v <= 1024}
        if bad:
            raise ValueError(f"cpu.scheduler.capacity must be in (0, 1024]: {bad}")
        return self


class CpuPowerParams(BaseScenarioModel):
    clusters: list[CpuClusterParams] = Field(default_factory=list)
    default_cluster: int | None = Field(default=None, ge=0)
    freq_mhz: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    volt_v: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    dsu: CpuDsuParams | None = None
    source: str | None = None
    scheduler: CpuSchedulerParams | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def _clusters_consistent(self) -> CpuPowerParams:
        names = [c.name.lower() for c in self.clusters]
        if len(names) != len(set(names)):
            raise ValueError("cpu.clusters names must be unique")
        cpus = [cpu for c in self.clusters for cpu in c.cpus]
        if len(cpus) != len(set(cpus)):
            raise ValueError("cpu.clusters cpus must not overlap")
        if self.default_cluster is not None and self.clusters and self.default_cluster >= len(self.clusters):
            raise ValueError("cpu.default_cluster is out of range")
        return self


class PowerCalibrationFit(BaseScenarioModel):
    """Lineage of a measurement fit (``api/services/power_fit.py``): per category factor and quality."""

    method: str = "least_squares_through_origin"
    base_params_ref: str | None = None
    statistic: str | None = None
    measured_sw: bool | None = None
    synthetic_rows: int = 0
    factors: dict[str, dict[str, float | int | None]] = Field(default_factory=dict)


class PowerCalibrationParams(BaseScenarioModel):
    source_evidence: list[str] = Field(default_factory=list)
    factor_by_ip: dict[str, float] = Field(default_factory=dict)
    # Applied by the engine (opt-in): IP power x factor; key = node id / hw name / DVFS domain / "*".
    ip_power_scale: dict[str, float] = Field(default_factory=dict, exclude_if=lambda v: not v)
    fit: PowerCalibrationFit | None = Field(default=None, exclude_if=lambda v: v is None)


class PowerModelParams(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["power_model_params"]
    soc_ref: DocumentId
    version: int = Field(default=1, ge=1)
    status: Literal["draft", "approved"] = "draft"
    description: str | None = None
    ip_model: str = "v1-vfps"
    ref_voltage_mv: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    ref_fps: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    # v2-vf: default share of IP power that scales with the set clock (per-IP
    # ``sim.clock_power_fraction`` in the IP catalog wins). None = 0 (v1 physics).
    ip_clock_power_fraction: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    bw_model: str | None = None
    bw: BwPowerParams = Field(default_factory=BwPowerParams)
    cpu: CpuPowerParams = Field(default_factory=CpuPowerParams)
    calibration: PowerCalibrationParams = Field(default_factory=PowerCalibrationParams)
    notes: str | None = None

    @property
    def params_ref(self) -> str:
        return f"{self.id}@{self.version}"

    def params_hash(self) -> str:
        """Content hash of the effective coefficients (storage independent)."""
        payload = self.model_dump(mode="json", exclude_none=True)
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
