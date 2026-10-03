from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion
from scenario_db.models.evidence.common import (
    Aggregation,
    Artifact,
    ExecutionContext,
    SweepContext,
)
from scenario_db.models.evidence.metrics import (
    MetricObservation,
    validate_metric_observations,
)

from scenario_db.models.evidence.camera import CameraPipeline, ProfilingMetadata, StageTiming, validate_camera_evidence
from scenario_db.models.evidence.profiling import HwTaskTiming, SwEventLatency

_KPI_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class MeasuredKpi(BaseScenarioModel):
    """Statistical KPI value recorded from repeated measurements."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mean: float
    p95: float | None = None
    std: float | None = Field(default=None, ge=0)
    ci_95: list[float] | None = None     # [lower, upper]; interval at ci_level (default 0.95)
    ci_level: float | None = Field(default=None, gt=0, lt=1)  # level used for ci_95; None == 0.95
    n: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_interval(self) -> MeasuredKpi:
        if self.ci_95 is not None:
            if len(self.ci_95) != 2:
                raise ValueError("ci_95 must be [lower, upper]")
            lo, hi = self.ci_95
            if lo > hi:
                raise ValueError(f"ci_95 lower {lo} > upper {hi}")
        return self


class FreqResidencyBin(BaseScenarioModel):
    """Time share spent at one frequency step (perfetto cpu_frequency digest)."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    freq_mhz: float = Field(gt=0)
    ratio: float = Field(ge=0, le=1)      # 0.0 - 1.0 residency fraction
    time_ms: float | None = Field(default=None, ge=0)


class MeasuredCpuCluster(BaseScenarioModel):
    """Per-cluster CPU digest extracted from power monitor + perfetto trace."""
    cluster: str                          # e.g. LIT / MID / BIG
    power_mw: MeasuredKpi | float | None = None
    avg_freq_mhz: float | None = None
    util_pct: float | None = None
    freq_residency: list[FreqResidencyBin] = Field(default_factory=list)


class SwTaskTiming(BaseScenarioModel):
    """Per-task wall time digest extracted from perfetto sched/slice data."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    task: str                             # logical task name, e.g. eis_warp, depth_npu
    timing_scope: Literal["exclusive_sw", "inclusive_stage"] | None = None
    includes_task_ids: list[str] = Field(default_factory=list)
    sample_unit: Literal["invocation", "frame"] = "invocation"
    process: str | None = None
    thread: str | None = None
    cluster: str | None = None            # dominant execution cluster
    min_ms: float | None = Field(default=None, ge=0)
    mean_ms: float | None = Field(default=None, ge=0)
    p50_ms: float | None = None
    p95_ms: float | None = None
    max_ms: float | None = Field(default=None, ge=0)
    start_jitter_mean_ms: float | None = Field(default=None, ge=0)
    includes_hw_nodes: list[str] = Field(default_factory=list)
    value_source: Literal["assumed", "measured", "projected"] | None = None
    source_note: str | None = None
    count_per_frame: float | None = None
    samples: int | None = Field(default=None, gt=0)
    start_latency_ref: str | None = None
    start_latency_mean_ms: float | None = Field(default=None, ge=0)
    rate_hz: float | None = Field(default=None, gt=0)
    cpu_affinity: str | None = None
    # Share of the wall time that is CPU work (I/O completion / waits are not);
    # used by the CPU power estimate. None = 1.0.
    # Omitted when unset so existing import fingerprints / evidence stay byte-identical.
    cpu_active_ratio: float | None = Field(default=None, gt=0, le=1, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def ordered_runtime(self) -> SwTaskTiming:
        values = [v for v in (self.min_ms, self.mean_ms, self.max_ms) if v is not None]
        if values != sorted(values):
            raise ValueError("SW timing requires min_ms <= mean_ms <= max_ms")
        if self.start_latency_mean_ms is not None and not self.start_latency_ref:
            raise ValueError("start latency requires an explicit predecessor event")
        return self


class RuntimeSwState(BaseScenarioModel):
    kernel_loaded_sha: str | None = None
    hal_loaded_version: str | None = None
    active_firmware: dict[str, str] = Field(default_factory=dict)


class RawArtifact(BaseScenarioModel):
    type: str
    path: str
    sha256: str | None = None


class Provenance(BaseScenarioModel):
    import_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    # Correction counter of one measurement (same id). Fingerprinted (SW timing / profiling)
    # evidence can only be replaced by a document with a higher revision.
    revision: int | None = Field(default=None, ge=1)
    device_id: str | None = None
    chamber_controlled: bool | None = None
    chamber_temp_c: float | None = None
    build_id: str | None = None
    sw_baseline_ref: DocumentId | None = None
    runtime_sw_state: RuntimeSwState | None = None
    collection_method: str | None = None
    # Explicit origin; None = legacy document, classified by calibration.data_origin()
    # (omitted when unset so existing import outputs / fingerprints stay byte-identical)
    data_origin: Literal["synthetic", "physical_capture", "unknown"] | None = Field(
        default=None, exclude_if=lambda value: value is None)
    # sim.config_profile whose rail_domain_map defined the rails at capture time (rail -> CPU/IP/BW);
    # unset = the project's latest profile is used and the comparison says so
    rail_domain_map_ref: str | None = Field(default=None, exclude_if=lambda value: value is None)
    collection_tool_versions: dict[str, str] = Field(default_factory=dict)
    sample_count: int | None = None
    duration_per_sample_s: float | None = None
    confidence_level: float | None = None
    raw_artifacts: list[RawArtifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_confidence_level(self) -> Provenance:
        if self.confidence_level is not None and not 0.0 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be in (0, 1)")
        return self


class MeasurementEvidence(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["evidence.measurement"]
    scenario_ref: DocumentId
    variant_ref: str
    execution_path_id: str | None = None
    pipeline_model: CameraPipeline | None = None
    stage_timing: list[StageTiming] = Field(default_factory=list)
    profiling_metadata: ProfilingMetadata | None = None
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
    hw_task_timing: list[HwTaskTiming] = Field(default_factory=list)
    sw_event_latency: list[SwEventLatency] = Field(default_factory=list)
    # Per-rail digest: numeric metrics (voltage_v/current_ma/power_mw/std_mw/...)
    # plus an optional "domain" string for dashboard rollups. Domain is partial:
    # only rails the name heuristic gets wrong need declaring.
    vdd_power: dict[str, dict[str, float | str]] = Field(default_factory=dict)
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    metric_observations: list[MetricObservation] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _camera(self):
        return validate_camera_evidence(self)

    @model_validator(mode="after")
    def _validate_kpi_keys(self) -> MeasurementEvidence:
        for key in self.kpi:
            if not _KPI_KEY_RE.match(key):
                raise ValueError(
                    f"KPI key must be lowercase snake_case (e.g. total_power_mW). "
                    f"Got: '{key}'"
                )
        validate_metric_observations(self.metric_observations)
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
