from __future__ import annotations

from typing import Literal

from pydantic import Field

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion


class ProjectMetadata(BaseScenarioModel):
    name: str
    soc_ref: DocumentId
    board_type: str | None = None
    board_name: str | None = None
    sensor_module_ref: str | None = None
    display_module_ref: str | None = None
    default_sw_profile_ref: DocumentId | None = None
    target_launch_date: str | None = None


class ProjectGlobals(BaseScenarioModel):
    default_sw_profile_ref: DocumentId | None = None
    tested_sw_profiles: list[DocumentId] = Field(default_factory=list)


class Project(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["project"]
    metadata: ProjectMetadata
    globals: ProjectGlobals | None = None
