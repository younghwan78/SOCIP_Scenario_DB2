from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: str
    kind: str
    scenario_ref: str
    variant_ref: str
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
    provenance: dict | None = None
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
