from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion
from scenario_db.models.evidence.common import (
    Aggregation,
    ExecutionContext,
    SweepContext,
)

_KPI_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class MeasuredKpi(BaseScenarioModel):
    """Statistical KPI value recorded from repeated measurements."""
    mean: float
    p95: float | None = None
    std: float | None = None
    ci_95: list[float] | None = None     # [lower, upper]
    n: int


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
    execution_context: ExecutionContext
    sweep_context: SweepContext | None = None
    provenance: Provenance
    aggregation: Aggregation
    # KPI values: either flat number (float/int) or statistical object (MeasuredKpi)
    kpi: dict[str, float | int | MeasuredKpi] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_kpi_keys(self) -> MeasurementEvidence:
        for key in self.kpi:
            if not _KPI_KEY_RE.match(key):
                raise ValueError(
                    f"KPI key must be lowercase snake_case (e.g. total_power_mW). "
                    f"Got: '{key}'"
                )
        return self
