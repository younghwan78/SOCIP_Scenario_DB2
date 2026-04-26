from __future__ import annotations

from pydantic import Field

from scenario_db.models.common import (
    BaseScenarioModel,
    DocumentId,
    FeatureFlagValue,
    SourceType,
)


class ExecutionContext(BaseScenarioModel):
    silicon_rev: str
    sw_baseline_ref: DocumentId          # v2.2: FK → sw_profiles (not a plain string)
    thermal: str
    ambient_temp_c: float | None = None
    power_state: str | None = None
    sw_runtime_overrides: dict[str, FeatureFlagValue] | None = None


class SweepContext(BaseScenarioModel):
    sweep_job_id: str
    sweep_definition_ref: str            # scenario.parametric_sweeps.id
    sweep_axis: str
    sweep_value: float | int | str
    sweep_index: int
    sweep_total_runs: int


class RunInfo(BaseScenarioModel):
    timestamp: str                       # ISO 8601
    tool: str
    tool_version: str | None = None
    writer: str | None = None
    git_commit: str | None = None
    source: SourceType


class SweepAggregation(BaseScenarioModel):
    strategy: str
    axis: str
    plot_metrics: list[str] = Field(default_factory=list)


class PerSweepValueAggregation(BaseScenarioModel):
    strategy: str
    n: int | None = None


class Aggregation(BaseScenarioModel):
    strategy: str
    sweep_aggregation: SweepAggregation | None = None
    per_sweep_value_aggregation: PerSweepValueAggregation | None = None


class Artifact(BaseScenarioModel):
    type: str
    storage: str
    path: str
    sha256: str | None = None
