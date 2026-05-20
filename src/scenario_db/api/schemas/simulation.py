from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.models import DVFSTable, SimRunResult, SimulationRunConfig


class SimulateRequest(BaseModel):
    scenario_id: str
    variant_id: str
    execution_context: ExecutionContext
    config: SimulationRunConfig = Field(default_factory=SimulationRunConfig)
    dvfs_tables: dict[str, DVFSTable] = Field(default_factory=dict)
    persist: bool = False
    force: bool = False


class SimulateRunResponse(BaseModel):
    evidence_id: str
    status: Literal["completed"]
    cached: bool
    params_hash: str
    warnings: list[str] = Field(default_factory=list)
    kpi: dict
    result: SimRunResult | None = None
    evidence: dict | None = None
    persisted: bool = False


class SimulationReadinessIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    node_id: str | None = None
    ip_ref: str | None = None


class SimulationReadinessResponse(BaseModel):
    status: Literal["ready", "warning", "blocked"]
    scenario_id: str
    variant_id: str
    soc_id: str
    profile: dict = Field(default_factory=dict)
    summary: dict = Field(default_factory=dict)
    errors: list[SimulationReadinessIssue] = Field(default_factory=list)
    warnings: list[SimulationReadinessIssue] = Field(default_factory=list)


class SimulationArtifactExportRequest(BaseModel):
    output_dir: str | None = None
    overwrite: bool = True
    project_ref: str | None = None
    scenario_name: str | None = None
    variant_name: str | None = None
    soc_ref: str | None = None


class SimulationArtifactResponse(BaseModel):
    type: str
    storage: str
    path: str
    sha256: str
    bytes: int


class SimulationArtifactExportResponse(BaseModel):
    evidence_id: str
    prefix: str
    output_dir: str
    artifacts: list[SimulationArtifactResponse] = Field(default_factory=list)
