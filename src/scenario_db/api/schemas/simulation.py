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
