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


class PowerReference(BaseScenarioModel):
    """Customer current target = "similar to or below the previous project" for the same scenario.

    ``project_ref`` = the previous project in this DB (its current predictions, then measurements, matched by
    variant id); ``values_mw`` = explicit per-variant values when the previous project is not in the DB.
    """
    project_ref: DocumentId | None = None
    values_mw: dict[str, float] = Field(default_factory=dict)
    # up to this much above the reference still counts as "similar" (medium risk); above it is high
    tolerance_pct: float = Field(default=3.0, ge=0, le=50)
    source_note: str | None = None


class ThermalWatch(BaseScenarioModel):
    """A scenario where customers typically ask for power reduction (thermal limits depend on the board)."""
    scenario_ref: DocumentId
    variant_ref: str
    label: str | None = None
    # reduction asks to pre-check, % of the current prediction
    reduction_pct: list[float] = Field(default_factory=lambda: [10.0, 20.0])
    note: str | None = None


class ReviewPolicy(BaseScenarioModel):
    """Project review rules (all optional; absent = previous behaviour)."""
    # NRT/Post timing judgement; "pipelined" = stages decoupled by M2M buffers, fps judged by the output interval
    throughput_model: Literal["stage", "pipelined"] | None = None
    # fps drop is never allowed; latency growth from buffering is reported, and flagged above this many frames
    max_latency_frames: int | None = Field(default=None, ge=1, le=10)
    # default registration: "iq_keep" = lowest power without lossy / assumed-ratio compression (no IQ evaluation needed);
    # None / "min_power" = lowest power overall (previous behaviour)
    register_baseline: Literal["min_power", "iq_keep"] | None = None
    power_reference: PowerReference | None = None
    thermal_watch: list[ThermalWatch] = Field(default_factory=list)


class ProjectGlobals(BaseScenarioModel):
    default_sw_profile_ref: DocumentId | None = None
    tested_sw_profiles: list[DocumentId] = Field(default_factory=list)
    review_policy: ReviewPolicy | None = None


class Project(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["project"]
    metadata: ProjectMetadata
    globals: ProjectGlobals | None = None
