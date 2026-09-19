"""Reusable sensor capabilities and board-specific declarations."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import ConfigDict, Field, model_validator
from scenario_db.models.common import BaseScenarioModel, SchemaVersion

class SensorTiming(BaseScenarioModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    active_width: int = Field(gt=0)
    active_height: int = Field(gt=0)
    pixel_clock_hz: float = Field(gt=0)
    line_length_pck: int = Field(gt=0)
    frame_length_lines: int = Field(gt=0)
    readout_lines: int | None = Field(default=None, gt=0)
    source: dict[str, Any] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_lines(self):
        if (self.readout_lines or self.active_height) > self.frame_length_lines:
            raise ValueError("readout lines must not exceed frame length")
        return self

class SensorTimingProfile(BaseScenarioModel):
    id: str = Field(pattern=r"^sensortiming-[A-Za-z0-9.-]+$")
    schema_version: SchemaVersion
    kind: Literal["sensor.timing_profile"]
    sensor_name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    modes: dict[str, SensorTiming] = Field(min_length=1)
    provenance: dict[str, Any] = Field(default_factory=dict)

class SensorCatalog(BaseScenarioModel):
    id: str = Field(pattern=r"^sensor-[A-Za-z0-9.-]+$")
    schema_version: SchemaVersion
    kind: Literal["sensor.catalog"]
    board: str = Field(min_length=1)
    sensor_name: str = Field(min_length=1)
    position: int
    position_role: str
    module_properties: dict[str, Any]
    csis_wiring: dict[str, Any]
    mode_count: int = Field(ge=0)
    mode_summary: dict[str, Any]
    modes: dict[str, dict[str, Any]]
    provenance: dict[str, Any]

    @model_validator(mode="after")
    def count_modes(self):
        if self.mode_count != len(self.modes):
            raise ValueError("mode_count differs from modes")
        for label, mode in self.modes.items():
            if not label or not isinstance(mode.get("decoded"), dict):
                raise ValueError("each full mode label requires decoded metadata")
            if "timing" in mode:
                SensorTiming.model_validate(mode["timing"])
        return self

class SensorBoardLineup(BaseScenarioModel):
    id: str = Field(pattern=r"^board-lineup-[A-Za-z0-9.-]+$")
    schema_version: SchemaVersion
    kind: Literal["sensor.board_lineup"]
    soc: str
    note: str = ""
    boards: dict[str, dict[str, Any]]
    provenance: dict[str, Any]
