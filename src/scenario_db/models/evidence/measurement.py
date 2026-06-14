from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion
from scenario_db.models.evidence.common import (
    Aggregation,
    Artifact,
    ExecutionContext,
    SweepContext,
)

_KPI_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class MeasuredKpi(BaseScenarioModel):
    """Statistical KPI value recorded from repeated measurements."""
    mean: float
    p95: float | None = None
    std: float | None = None
    ci_95: list[float] | None = None     # [lower, upper]; interval at ci_level (default 0.95)
    ci_level: float | None = None        # confidence level used for ci_95; None == 0.95 default
    n: int


class FreqResidencyBin(BaseScenarioModel):
    """Time share spent at one frequency step (perfetto cpu_frequency digest)."""
    freq_mhz: float
    ratio: float                          # 0.0 - 1.0 residency fraction
    time_ms: float | None = None


class MeasuredCpuCluster(BaseScenarioModel):
    """Per-cluster CPU digest extracted from power monitor + perfetto trace."""
    cluster: str                          # e.g. LIT / MID / BIG
    power_mw: MeasuredKpi | float | None = None
    avg_freq_mhz: float | None = None
    util_pct: float | None = None
    freq_residency: list[FreqResidencyBin] = Field(default_factory=list)


class SwTaskTiming(BaseScenarioModel):
    """Per-task wall time digest extracted from perfetto sched/slice data."""
    task: str                             # logical task name, e.g. eis_warp, depth_npu
    process: str | None = None
    thread: str | None = None
    cluster: str | None = None            # dominant execution cluster
    mean_ms: float | None = None
    p50_ms: float | None = None
    p95_ms: float | None = None
    max_ms: float | None = None
    count_per_frame: float | None = None
    samples: int | None = None


class RuntimeSwState(BaseScenarioModel):
    kernel_loaded_sha: str | None = None
    hal_loaded_version: str | None = None
    active_firmware: dict[str, str] = Field(default_factory=dict)


class RawArtifact(BaseScenarioModel):
    type: str
    path: str
    sha256: str | None = None


class Provenance(BaseScenarioModel):
    device_id: str | None = None
    chamber_controlled: bool | None = None
    chamber_temp_c: float | None = None
    build_id: str | None = None
    sw_baseline_ref: DocumentId | None = None
    runtime_sw_state: RuntimeSwState | None = None
    collection_method: str | None = None
    collection_tool_versions: dict[str, str] = Field(default_factory=dict)
    sample_count: int | None = None
    duration_per_sample_s: float | None = None
    confidence_level: float | None = None
    raw_artifacts: list[RawArtifact] = Field(default_factory=list)


class MeasurementEvidence(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["evidence.measurement"]
    scenario_ref: DocumentId
    variant_ref: str
    project_ref: DocumentId | None = None
    measured_at: str | None = None       # ISO 8601, e.g. "2026-06-01T10:00:00+09:00"
    derived_from: list[DocumentId] = Field(default_factory=list)
    execution_context: ExecutionContext
    sweep_context: SweepContext | None = None
    provenance: Provenance
    aggregation: Aggregation
    # KPI values: either flat number (float/int) or statistical object (MeasuredKpi)
    kpi: dict[str, float | int | MeasuredKpi] = Field(default_factory=dict)
    cpu_breakdown: list[MeasuredCpuCluster] = Field(default_factory=list)
    sw_task_timing: list[SwTaskTiming] = Field(default_factory=list)
    vdd_power: dict[str, dict[str, float]] = Field(default_factory=dict)
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_kpi_keys(self) -> MeasurementEvidence:
        for key in self.kpi:
            if not _KPI_KEY_RE.match(key):
                raise ValueError(
                    f"KPI key must be lowercase snake_case (e.g. total_power_mW). "
                    f"Got: '{key}'"
                )
        return self

    @model_validator(mode="after")
    def _validate_measured_at(self) -> MeasurementEvidence:
        if self.measured_at is not None:
            from datetime import datetime
            try:
                datetime.fromisoformat(self.measured_at)
            except ValueError as exc:
                raise ValueError(
                    f"measured_at must be ISO 8601 (e.g. 2026-06-01T10:00:00+09:00). "
                    f"Got: '{self.measured_at}'"
                ) from exc
        return self
