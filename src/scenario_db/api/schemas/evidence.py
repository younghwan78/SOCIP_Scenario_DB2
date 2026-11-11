from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


# Timeline contents and profiling source metadata are used to filter/rank list
# choices. Keep them until the list has an equivalent compact trace index.
EVIDENCE_HEAVY_FIELDS = (
    "calculation_trace", "dma_breakdown", "ip_breakdown", "timing_breakdown",
    "dvfs_breakdown", "external_devices", "cpu_breakdown", "sw_task_timing",
    "hw_task_timing", "stage_timing", "sw_event_latency", "handoff_flows", "pipeline_model",
    "timeline_events",
)


class EvidenceListFields(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: str
    kind: str
    scenario_ref: str
    variant_ref: str
    project_ref: str | None = None
    measured_at: datetime | None = None
    derived_from: list | None = None
    sw_baseline_ref: str | None = None
    sweep_job_id: str | None = None
    execution_context: dict = {}
    sweep_context: dict | None = None
    resolution_result: dict | None = None
    overall_feasibility: str | None = None
    aggregation: dict = {}
    kpi: dict = {}
    run_info: dict | None = None
    topology_order: list | None = None
    vdd_power: dict | None = None
    power_breakdown: dict | None = None
    params_hash: str | None = None
    provenance: dict | None = None
    execution_path_id: str | None = None
    profiling_metadata: dict | None = None
    metric_observations: list | None = None
    artifacts: list | None = None
    sw_version_hint: str | None = None


class EvidenceHeavyField(BaseModel):
    present: bool
    bytes: int


class TraceIndex(BaseModel):
    """What list views read from a timeline (computed in SQL; the events stay in the detail).

    ``frames``: distinct numeric frame indices; ``frame_values``: distinct frame_index values with a
    missing one counted once (the older client-side count); ``layered``: some event has a layer
    (full-stack trace)."""

    events: int
    nodes: list[str]
    frames: int
    frame_values: int
    layered: bool


class EvidenceSummaryResponse(EvidenceListFields):
    heavy: dict[str, EvidenceHeavyField]
    trace_index: TraceIndex


class EvidenceResponse(EvidenceListFields):
    timeline_events: list | None = None
    ip_breakdown: list | None = None
    dma_breakdown: list | None = None
    timing_breakdown: list | None = None
    dvfs_breakdown: list | None = None
    handoff_flows: dict | None = None
    external_devices: list | None = None
    calculation_trace: dict | None = None
    cpu_breakdown: list | None = None
    sw_task_timing: list | None = None
    pipeline_model: dict | None = None
    stage_timing: list | None = None
    hw_task_timing: list | None = None
    sw_event_latency: list | None = None


class SweepJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scenario_ref: str
    variant_ref: str
    sweep_axis: str
    sweep_values: list | dict
    total_runs: int
    completed_runs: int
    status: str | None = None
