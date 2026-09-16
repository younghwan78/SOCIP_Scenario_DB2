"""Measured timing contracts. All durations are milliseconds, timestamps nanoseconds."""
from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from scenario_db.models.common import BaseScenarioModel


class TimingStatistics(BaseScenarioModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    min_ms: float = Field(ge=0)
    mean_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)
    samples: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> TimingStatistics:
        if not self.min_ms <= self.mean_ms <= self.max_ms:
            raise ValueError("timing requires min_ms <= mean_ms <= max_ms")
        return self


class HwTaskTiming(TimingStatistics):
    task: str
    node_id: str
    runtime_basis: Literal["wall", "active"] = "wall"
    value_source: Literal["measured"] = "measured"


class SwEventLatency(TimingStatistics):
    edge_id: str
    predecessor_task: str
    successor_task: str
    source_anchor: Literal["start", "end"] = "end"
    target_anchor: Literal["start"] = "start"
    pairing: Literal["flow", "correlation_id"]
    value_source: Literal["measured"] = "measured"


class ProfilingSummary(BaseScenarioModel):
    """Optional summary-only input; does not fabricate sequence or samples."""
    hw_task_timing: list[HwTaskTiming] = Field(default_factory=list)
    sw_event_latency: list[SwEventLatency] = Field(default_factory=list)
    @model_validator(mode="after")
    def unique_identities(self) -> ProfilingSummary:
        for values in ([v.task for v in self.hw_task_timing], [v.edge_id for v in self.sw_event_latency]):
            if len(values) != len(set(values)):
                raise ValueError("profiling summary identities must be unique")
        return self


class MeasuredTimingProfile(BaseScenarioModel):
    """Explicit, condition-scoped override; serialized into simulation config/cache."""
    profile_id: str
    revision: int = Field(ge=1)
    evidence_ref: str
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_ref: str
    scenario_ref: str
    variant_ref: str
    design_conditions: dict[str, object]
    capture_context: dict[str, object] = Field(default_factory=dict)
    baseline_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    statistic: Literal["min", "mean", "max"] = "mean"
    source_task_mapping: dict[str, str] = Field(default_factory=dict)
    task_runtime: dict[str, TimingStatistics] = Field(default_factory=dict)
    event_latency: list[SwEventLatency] = Field(default_factory=list)
