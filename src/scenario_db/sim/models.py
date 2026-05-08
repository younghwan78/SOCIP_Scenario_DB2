from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel


class PortType(StrEnum):
    DMA_READ = "DMA_READ"
    DMA_WRITE = "DMA_WRITE"
    OTF_IN = "OTF_IN"
    OTF_OUT = "OTF_OUT"


class IPSimParams(BaseScenarioModel):
    """Per-IP simulation parameters sourced from IpCatalog capabilities."""

    hw_name: str
    ppc: float = 0.0
    unit_power_mw_mp: float = 0.0
    idc: float = 0.0
    vdd: str | None = None
    dvfs_group: str | None = None
    max_clock_mhz: float | None = None


class PortTransferSpec(BaseScenarioModel):
    """Variant-level per-port transfer configuration used by BW calculation."""

    node_id: str
    ip_ref: str | None = None
    hw_name: str
    port: str
    port_type: PortType
    width: int
    height: int
    format: str | None = None
    bitwidth: int = 8
    compression: str = "disable"
    comp_ratio: float = 1.0
    comp_ratio_min: float | None = None
    comp_ratio_max: float | None = None
    llc_enabled: bool = False
    llc_weight: float = 1.0
    r_w_rate: float = 1.0

    @model_validator(mode="after")
    def _validate_shape(self) -> PortTransferSpec:
        if self.width < 0 or self.height < 0:
            raise ValueError("port width/height must be non-negative")
        if self.bitwidth <= 0:
            raise ValueError("port bitwidth must be positive")
        return self


class DVFSLevel(BaseScenarioModel):
    level: int
    speed_mhz: float
    voltages: dict[int, float] = Field(default_factory=dict)


class DVFSTable(BaseScenarioModel):
    domain: str
    levels: list[DVFSLevel] = Field(default_factory=list)

    def get_level(self, level_num: int) -> DVFSLevel | None:
        for level in self.levels:
            if level.level == level_num:
                return level
        return None

    def find_min_level_for_speed(
        self,
        required_mhz: float,
        *,
        asv_group: int | None = None,
    ) -> DVFSLevel | None:
        candidates = [
            level
            for level in self.levels
            if level.speed_mhz > 0
            and level.speed_mhz >= required_mhz
            and (asv_group is None or level.voltages.get(asv_group, 0.0) > 0)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda level: level.speed_mhz)

    def voltage_for(self, level: DVFSLevel, asv_group: int) -> float:
        return level.voltages.get(asv_group, 0.0)


class IPWorkload(BaseScenarioModel):
    node_id: str
    ip_ref: str | None = None
    hw_name: str
    mode: str = "Normal"
    width: int = 0
    height: int = 0
    fps: float
    sw_margin: float = 0.25
    manual_clock_mhz: float | None = None
    sim_params: IPSimParams

    @property
    def pixels(self) -> int:
        return max(0, self.width) * max(0, self.height)


class SimulationRunConfig(BaseScenarioModel):
    asv_group: int = 4
    fps: float | None = None
    sw_margin: float = 0.25
    bw_power_coeff: float = 80.0
    vbat: float = 4.0
    pmic_efficiency: float = 0.85
    h_blank_margin: float = 0.05
    dvfs_overrides: dict[str, int] = Field(default_factory=dict)
    include_timeline: bool = True
    timeline_frame_count: int = 1
    timeline_frame_period_ms: float | None = None


class SimulationInputs(BaseScenarioModel):
    scenario_id: str
    variant_id: str
    project_ref: str | None = None
    config: SimulationRunConfig
    workloads: list[IPWorkload] = Field(default_factory=list)
    port_transfers: list[PortTransferSpec] = Field(default_factory=list)
    timeline_tasks: list[dict] = Field(default_factory=list)
    timeline_edges: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResolvedIPConfig(BaseScenarioModel):
    node_id: str
    ip_ref: str | None = None
    hw_name: str
    mode: str
    required_clock_mhz: float
    set_clock_mhz: float
    dvfs_level: int | None = None
    dvfs_group: str | None = None
    required_voltage_mv: float
    set_voltage_mv: float
    vdd: str | None = None
    unit_power_mw_mp: float
    ppc: float
    input_resolution_mp: float
    fps: float
    active_power_mw: float
    total_power_mw: float
    vdd_leader: str | None = None
    feasible: bool = True
    infeasible_reason: str | None = None


class PortBWResult(BaseScenarioModel):
    node_id: str
    ip_ref: str | None = None
    hw_name: str
    port: str
    direction: Literal["read", "write", "otf"]
    width: int | None = None
    height: int | None = None
    size_mp: float | None = None
    bw_mbs: float
    bw_mbs_best: float | None = None
    bw_mbs_worst: float | None = None
    bw_power_mw: float
    bw_power_ma: float
    format: str | None = None
    bitwidth: int | None = None
    compression: str | None = None
    llc_enabled: bool = False


class IPTimingResult(BaseScenarioModel):
    node_id: str
    ip_ref: str | None = None
    hw_name: str
    task_type: Literal["hw", "sw"] = "hw"
    hw_time_ms: float
    required_clock_mhz: float | None = None
    set_clock_mhz: float | None = None
    set_voltage_mv: float | None = None
    feasible: bool = True
    infeasible_reason: str | None = None


class TimelineEvent(BaseScenarioModel):
    task_id: str
    node_id: str | None = None
    hw_name: str | None = None
    task_type: Literal["hw", "sw"] = "hw"
    frame_index: int | None = None
    resource_id: str | None = None
    constraint_type: Literal["source", "sink"] | None = None
    source_fps: float | None = None
    v_valid_ms: float | None = None
    refresh_hz: float | None = None
    scanout_ms: float | None = None
    start_ms: float
    end_ms: float
    duration_ms: float
    deadline_ms: float | None = None
    slack_ms: float | None = None
    ready_ms: float | None = None
    resource_wait_ms: float = 0.0
    token_wait_ms: float = 0.0
    critical: bool = False
    critical_path_rank: int | None = None
    predecessors: list[str] = Field(default_factory=list)


class SimRunResult(BaseScenarioModel):
    scenario_id: str
    variant_id: str
    total_power_mw: float
    total_power_ma: float
    core_power_mw: float
    bw_power_mw: float
    bw_total_mbs: float
    hw_time_max_ms: float
    timeline_end_ms: float | None = None
    feasible: bool
    infeasible_reason: str | None = None
    resolved: dict[str, ResolvedIPConfig] = Field(default_factory=dict)
    dma_breakdown: list[PortBWResult] = Field(default_factory=list)
    timing_breakdown: list[IPTimingResult] = Field(default_factory=list)
    timeline_events: list[TimelineEvent] = Field(default_factory=list)
    vdd_power: dict[str, dict[str, float]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
