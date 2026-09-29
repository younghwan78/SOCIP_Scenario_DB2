"""SoC-scoped power model parameters (``kind: power_model_params``).

The power *model code* stays in ``sim/power_model.py`` / ``sim/bw_power.py``;
the *coefficients* a project calibrates live here as data, so a new process
node or a calibration round never needs a code change:

- ``ref_voltage_mv`` / ``ref_fps``: the operating point ``unit_power_mw_mp``
  was characterised at (previously global constants).
- ``bw_model`` + ``bw``: which BW power model to use and its coefficients
  (e.g. ``linear-per-gbps`` with ``mw_per_gbps: 50``).
- ``cpu.clusters``: per-cluster ``uW / MHz / V^2`` coefficients for the SW/CPU
  power estimate.
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
    llc_hit_scale: float = Field(default=1.0, ge=0, allow_inf_nan=False)


class CpuClusterParams(BaseScenarioModel):
    name: str
    coeff_uw_per_mhz_v2: float = Field(gt=0, allow_inf_nan=False)


class CpuPowerParams(BaseScenarioModel):
    # Index order matches the timing-budget cluster index (0..3).
    clusters: list[CpuClusterParams] = Field(default_factory=list, max_length=4)
    default_cluster: int | None = Field(default=None, ge=0, le=3)
    freq_mhz: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    volt_v: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    source: str | None = None

    @model_validator(mode="after")
    def _clusters_complete(self) -> CpuPowerParams:
        if self.clusters and len(self.clusters) != 4:
            raise ValueError("cpu.clusters must list exactly 4 clusters (index 0..3) or none")
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
