"""meta.yaml contract for measurement import.

A measurement capture is described by a small ``meta.yaml`` sidecar the
measurement team fills in. It carries the static evidence metadata
(execution context, provenance) plus the *instructions* needed to turn raw
artifacts into canonical digests:

- ``rails``: how each power-monitor CSV column maps onto vdd_power / a CPU
  cluster / total power.
- ``cpu_to_cluster``: perfetto CPU index -> logical cluster, for frequency
  residency.
- ``task_mapping``: raw perfetto process/thread -> logical task name, for
  ``sw_task_timing`` (see the task naming convention in the contract doc).
- ``artifacts``: raw artifact pointers recorded in the evidence (path + sha256).
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.models.evidence.measurement import Provenance


class RailRole(BaseScenarioModel):
    """Role of one power-monitor CSV column."""
    role: Literal["vdd", "cpu_cluster", "ignore"] = "vdd"
    cluster: str | None = None        # required when role == cpu_cluster
    # Power domain for dashboard rollups (CPU/MEM/CAM/GPU/...). Optional: only
    # declare rails the name heuristic gets wrong; the rest fall back to it.
    domain: str | None = None

    @model_validator(mode="after")
    def _check_cluster(self) -> RailRole:
        if self.role == "cpu_cluster" and not self.cluster:
            raise ValueError("rail role 'cpu_cluster' requires a 'cluster' name")
        return self


class PowerSpec(BaseScenarioModel):
    """Power-monitor CSV input + how to aggregate it.

    Two layouts are supported via ``format``:

    - ``wide`` (default, legacy): one time column + one column per rail, each
      value a power sample (mW). Aggregated over the rows of a single capture.
    - ``rail_long``: real bench output. One row per (run, rail) with a
      voltage/current/power triplet. Aggregated *across runs* (n = run count),
      producing per-rail {voltage_v, current_ma, power_mw, std_mw} in vdd_power.
      Rail names/count are arbitrary and project-specific.
    """
    csv: str                          # path to the power CSV (relative to meta dir or absolute)
    format: Literal["wide", "rail_long"] = "wide"
    time_column: str = "timestamp_ms"  # wide: the dropped time column
    # rails to sum *per sample/run* before aggregating into total_power_mw.
    # If empty: wide → no total; rail_long → sum all rails, requiring the same
    # rail set in every run. Use an explicit stable subset when captures differ.
    total_power_rails: list[str] = Field(default_factory=list)
    # optional pre-summed total column (wide only); takes precedence.
    total_power_column: str | None = None
    rails: dict[str, RailRole] = Field(default_factory=dict)
    # rail_long column names (override if the bench uses different headers).
    run_column: str = "run"
    rail_column: str = "rail"
    voltage_column: str = "voltage_v"
    current_column: str = "current_ma"
    power_column: str = "power_mw"


class TaskMatch(BaseScenarioModel):
    process: str | None = None        # exact process name
    process_re: str | None = None     # regex on process name
    thread: str | None = None         # exact thread name
    thread_re: str | None = None      # regex on thread name
    slice_re: str | None = None       # regex on slice name

    @model_validator(mode="after")
    def _check_any(self) -> TaskMatch:
        if not any(
            (self.process, self.process_re, self.thread, self.thread_re, self.slice_re)
        ):
            raise ValueError("task match must specify at least one of process/thread/slice")
        return self


class TaskMapping(BaseScenarioModel):
    task: str                         # logical task name (e.g. eis_warp)
    match: TaskMatch
    cluster: str | None = None        # dominant execution cluster (annotation)


class PerfettoSpec(BaseScenarioModel):
    """Perfetto trace input + extraction instructions."""
    trace: str                        # path to the trace (.pb / .pftrace)
    cpu_to_cluster: dict[int, str] = Field(default_factory=dict)
    task_mapping: list[TaskMapping] = Field(default_factory=list)
    # frame counter slice name used to derive frame count (count_per_frame).
    frame_slice_name: str | None = None
    frame_count: int | None = None    # explicit frame count override


class ArtifactSpec(BaseScenarioModel):
    """Raw artifact pointer recorded in the evidence."""
    type: str                         # perfetto_trace | power_monitor_csv | ...
    path: str                         # path recorded in evidence (file-store relative)
    storage: str = "fileshare"
    source: str | None = None         # local file to hash; defaults to path if it exists
    mime: str | None = None


class MeasurementImportMeta(BaseScenarioModel):
    """Top-level meta.yaml contract."""
    schema_version: str = "2.2"
    id: str | None = None             # auto-generated when omitted
    project_ref: str
    scenario_ref: str
    variant_ref: str
    measured_at: str                  # ISO 8601
    execution_context: ExecutionContext
    provenance: Provenance = Field(default_factory=Provenance)
    aggregation_strategy: str = "mean_over_capture"
    # KPIs the extractors do not produce (e.g. frame_latency_ms, fps_effective).
    # Merged into the evidence kpi map; power-derived total_power_mw wins on clash
    # only when the meta does not set it explicitly.
    kpi: dict[str, float | int | dict] = Field(default_factory=dict)
    power: PowerSpec | None = None
    perfetto: PerfettoSpec | None = None
    artifacts: list[ArtifactSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _force_measurement_method(self) -> MeasurementImportMeta:
        # measurement evidence always carries method=measurement.
        if self.execution_context.method is None:
            self.execution_context.method = "measurement"
        elif self.execution_context.method != "measurement":
            raise ValueError(
                "execution_context.method must be 'measurement' for measurement import"
            )
        return self

    @model_validator(mode="after")
    def _need_some_input(self) -> MeasurementImportMeta:
        if self.power is None and self.perfetto is None:
            raise ValueError("meta must provide at least one of 'power' or 'perfetto'")
        return self
