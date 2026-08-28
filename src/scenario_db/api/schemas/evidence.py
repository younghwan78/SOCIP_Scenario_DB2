from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EvidenceResponse(BaseModel):
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
    ip_breakdown: list | None = None
    dma_breakdown: list | None = None
    timing_breakdown: list | None = None
    dvfs_breakdown: list | None = None
    timeline_events: list | None = None
    external_devices: list | None = None
    topology_order: list | None = None
    vdd_power: dict | None = None
    calculation_trace: dict | None = None
    params_hash: str | None = None
    provenance: dict | None = None
    cpu_breakdown: list | None = None
    sw_task_timing: list | None = None
    metric_observations: list | None = None
    artifacts: list | None = None
    sw_version_hint: str | None = None


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
