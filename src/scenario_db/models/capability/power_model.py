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
  (lineage only; ``factor_by_ip`` is recorded, not applied by the engine yet).

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


class BwPowerParams(BaseScenarioModel):
    mw_per_gbps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    llc_hit_scale: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)


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

    e.g. Exynos2700: MID_LF x4, MID_HF x4, BIG_LF x1, BIG x1 (+ DSU).
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
        if self.coeff_uw_per_mhz_v2 is None and not any(o.mw_per_core is not None for o in self.opps):
            raise ValueError(f"cpu cluster '{self.name}' needs coeff_uw_per_mhz_v2 or opps[].mw_per_core")
        if self.opps != sorted(self.opps, key=lambda o: o.mhz):
            raise ValueError(f"cpu cluster '{self.name}' opps must be sorted by mhz")
        if self.cpus and len(self.cpus) != self.cores:
            raise ValueError(f"cpu cluster '{self.name}' lists {len(self.cpus)} cpus for {self.cores} cores")
        return self


class CpuDsuParams(BaseScenarioModel):
    """DynamIQ Shared Unit (L3 / snoop control), shared by all clusters."""

    name: str = "DSU"
    opps: list[CpuOpp] = Field(default_factory=list)
    leakage: CpuLeakage | None = None
    rail: str | None = None


class CpuPowerParams(BaseScenarioModel):
    clusters: list[CpuClusterParams] = Field(default_factory=list)
    default_cluster: int | None = Field(default=None, ge=0)
    freq_mhz: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    volt_v: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    dsu: CpuDsuParams | None = None
    source: str | None = None

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


class PowerCalibrationParams(BaseScenarioModel):
    source_evidence: list[str] = Field(default_factory=list)
    factor_by_ip: dict[str, float] = Field(default_factory=dict)


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
