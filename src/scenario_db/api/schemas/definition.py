from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    schema_version: str
    metadata_: dict = {}
    globals_: dict | None = None


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    schema_version: str
    project_ref: str
    metadata_: dict = {}
    pipeline: dict = {}
    size_profile: dict | None = None
    design_axes: list | None = None


class ScenarioVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scenario_id: str
    id: str
    severity: str | None = None
    design_conditions: dict | None = None
    ip_requirements: dict | None = None
    sw_requirements: dict | None = None
    violation_policy: dict | None = None
    tags: list | None = None
    derived_from_variant: str | None = None
