"""Projection recipe contract + calibration result containers."""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel


# --- recipe (input YAML) -----------------------------------------------------

class ProjectionSources(BaseScenarioModel):
    """Evidence inputs. Values are file paths (relative to the recipe dir)."""
    u_measurement: str            # U measurement evidence YAML
    u_simulation: str             # U calculation evidence YAML (same variant as U meas)
    v_simulation: str             # V calculation evidence YAML (the one to project)


class ProjectionTarget(BaseScenarioModel):
    """Identity for the generated projected evidence (V)."""
    id: str | None = None         # auto-generated when omitted
    project_ref: str
    scenario_ref: str
    variant_ref: str
    silicon_rev: str = "PRE_SI"
    sw_baseline_ref: str
    schema_version: str = "2.2"


class ClusterScaling(BaseScenarioModel):
    """SW task time scaling for one CPU cluster (U -> V).

    ``time_scale`` is the multiplier applied to U's measured task times to get
    V's estimate (work fixed, time ∝ 1/capacity). Provide it directly, or give
    U/V capacities and let it be derived as u_capacity / v_capacity.
    """
    time_scale: float | None = None
    u_capacity_mhz: float | None = None
    v_capacity_mhz: float | None = None

    @model_validator(mode="after")
    def _resolve(self) -> ClusterScaling:
        if self.time_scale is None:
            if self.u_capacity_mhz and self.v_capacity_mhz:
                self.time_scale = self.u_capacity_mhz / self.v_capacity_mhz
            else:
                raise ValueError(
                    "cluster scaling requires 'time_scale' or both "
                    "'u_capacity_mhz' and 'v_capacity_mhz'"
                )
        if self.time_scale <= 0:
            raise ValueError("time_scale must be positive")
        return self


class ProjectionRecipe(BaseScenarioModel):
    kind: str = "projection.recipe"
    sources: ProjectionSources
    target: ProjectionTarget
    cluster_scaling: dict[str, ClusterScaling] = Field(default_factory=dict)
    # scale ip_breakdown by the global total-power factor (uniform approximation).
    scale_ip_breakdown: bool = True
    notes: str | None = None


# --- calibration (intermediate result) ---------------------------------------

@dataclass(slots=True)
class Calibration:
    """Correction factors derived from U sim vs U measurement.

    A factor > 1 means measurement exceeded the calculation (sim under-predicts).
    """
    total_power_factor: float | None = None
    rail_factors: dict[str, float] = field(default_factory=dict)
    kpi_factors: dict[str, float] = field(default_factory=dict)
    # diagnostic record: metric -> {sim, meas, factor}
    detail: dict[str, dict] = field(default_factory=dict)

    def to_trace(self) -> dict:
        return {
            "total_power_factor": self.total_power_factor,
            "rail_factors": dict(self.rail_factors),
            "kpi_factors": dict(self.kpi_factors),
            "detail": self.detail,
        }
