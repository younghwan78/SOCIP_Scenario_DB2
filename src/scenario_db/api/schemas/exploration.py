from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from scenario_db.sim.exploration_runner import SweepPreviewCase
from scenario_db.sim.models import DVFSTable, SimulationRunConfig


class ExplorationExampleSummary(BaseModel):
    id: str
    type: Literal["recipe", "sweep", "template"]
    title: str
    fixture_id: str | None = None
    path: str
    scenario_id: str | None = None
    variant_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class ExplorationExampleListResponse(BaseModel):
    items: list[ExplorationExampleSummary]
    total: int


class ExplorationExampleResponse(ExplorationExampleSummary):
    yaml_text: str
    payload: dict[str, Any]


class ExplorationRecipeCompileRequest(BaseModel):
    recipe: dict[str, Any] | None = None
    source_yaml: str | None = None


class ExplorationRecipeCompileResponse(BaseModel):
    persisted: bool = False
    scenario: dict[str, Any]
    import_bundle: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    mapping_trace: list[dict[str, Any]] = Field(default_factory=list)


class ExplorationSweepCompileRequest(BaseModel):
    sweep: dict[str, Any] | None = None
    source_yaml: str | None = None


class ExplorationSweepCompileResponse(BaseModel):
    persisted: bool = False
    import_bundle: dict[str, Any]
    cases: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExplorationTemplateCompileRequest(BaseModel):
    template: dict[str, Any] | None = None
    source_yaml: str | None = None


class ExplorationTemplateCompileResponse(BaseModel):
    persisted: bool = False
    scenario: dict[str, Any]
    import_bundle: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    mapping_trace: list[dict[str, Any]] = Field(default_factory=list)


class ExplorationTemplatePreviewRequest(BaseModel):
    template: dict[str, Any] | None = None
    source_yaml: str | None = None
    config: SimulationRunConfig = Field(default_factory=lambda: SimulationRunConfig(include_timeline=False))
    dvfs_tables: dict[str, DVFSTable] = Field(default_factory=dict)
    include_results: bool = False


class ExplorationSweepPreviewRequest(BaseModel):
    sweep: dict[str, Any] | None = None
    source_yaml: str | None = None
    config: SimulationRunConfig = Field(default_factory=lambda: SimulationRunConfig(include_timeline=False))
    dvfs_tables: dict[str, DVFSTable] = Field(default_factory=dict)
    include_results: bool = False


class ExplorationSweepPreviewResponse(BaseModel):
    persisted: bool = False
    baseline_case_id: str | None = None
    cases: list[SweepPreviewCase] = Field(default_factory=list)
    comparison: list[dict[str, Any]] = Field(default_factory=list)
    import_bundle: dict[str, Any] = Field(default_factory=dict)
