from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel, DocumentId, InstanceId, SchemaVersion
from scenario_db.models.evidence.common import (
    Aggregation,
    Artifact,
    ExecutionContext,
    RunInfo,
    SweepContext,
)
from scenario_db.models.evidence.resolution import ResolutionResult

_KPI_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SubmoduleBreakdown(BaseScenarioModel):
    sub: InstanceId                      # e.g. ISP.TNR
    power_mW: float


class IpBreakdown(BaseScenarioModel):
    ip: DocumentId
    instance_index: int = 0
    power_mW: float
    submodules: list[SubmoduleBreakdown] = Field(default_factory=list)


class SimulationEvidence(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["evidence.simulation"]
    scenario_ref: DocumentId
    variant_ref: str                     # Variant.id is free-form, not a DocumentId
    project_ref: DocumentId | None = None
    execution_context: ExecutionContext
    sweep_context: SweepContext | None = None
    resolution_result: ResolutionResult | None = None
    run: RunInfo
    aggregation: Aggregation
    kpi: dict[str, float | int] = Field(default_factory=dict)
    ip_breakdown: list[IpBreakdown] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_kpi_keys(self) -> SimulationEvidence:
        for key in self.kpi:
            if not _KPI_KEY_RE.match(key):
                raise ValueError(
                    f"KPI key must be lowercase snake_case (e.g. total_power_mW). "
                    f"Got: '{key}'"
                )
        return self
