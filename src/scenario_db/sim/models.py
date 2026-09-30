from __future__ import annotations

from enum import StrEnum
import math
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.models.common import BaseScenarioModel
from scenario_db.sim.clock_models import (
    ClockBasis,
    ClockConstraint,
    ClockLedger,
    ConfiguredClock,
    MeasuredClock,
    MeasuredClockStat,
)
from scenario_db.models.sensor import SensorTiming, SensorModeBinding
from scenario_db.sim.driver_models import DriverInput
from scenario_db.sim.constants import SW_MARGIN_DEFAULT
from scenario_db.sim.sw_projection import SwTimingProjection


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
    # v2-vf: share of IP power that scales with the set clock (catalog sim block).
    clock_power_fraction: float | None = Field(default=None, ge=0, le=1)
    # v2-vf gating / leakage (catalog sim block; perfetto gating ratios):
    # share of clock / leakage power removed while the IP idles, and static
    # power at the reference voltage.
    clock_gating_eff: float | None = Field(default=None, ge=0, le=1)
    power_gating_eff: float | None = Field(default=None, ge=0, le=1)
    leakage_mw: float | None = Field(default=None, ge=0)
    source: str | None = None
    source_project: str | None = None
    source_note: str | None = None
    mapping_source: dict[str, Any] = Field(default_factory=dict)


class PortTransferSpec(BaseScenarioModel):
    """Variant-level per-port transfer configuration used by BW calculation."""

    node_id: str
    ip_ref: str | None = None
    hw_name: str
    port: str
    port_type: PortType
    bitrate_mbps: float | None = Field(default=None, gt=0, allow_inf_nan=False)
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
    instance_index: int = Field(default=0, ge=0)
    ip_ref: str | None = None
    hw_name: str
    mode: str = "Normal"
    width: int = 0
    height: int = 0
    format: str | None = None
    fps: float
    sw_margin: float = SW_MARGIN_DEFAULT
    manual_clock_mhz: float | None = None
    clock_correction_mhz: float = 0.0
    clock_correction_reason: str | None = None
    # Every clock lower bound collected while building inputs (the correction
    # above keeps only the max). Informational: derived from inputs already in
    # the hash, so it is excluded from serialisation / params_hash.
    clock_constraints: list[ClockConstraint] = Field(default_factory=list, exclude=True)
    sim_params: IPSimParams

    @property
    def pixels(self) -> int:
        return max(0, self.width) * max(0, self.height)


from scenario_db.models.evidence.profiling import MeasuredTimingProfile


class CpuCounters(BaseScenarioModel):
    """PMU counters per frame (already normalised by the capture window)."""

    cycles: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    instructions: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    stall_cycles: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    bus_bytes: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class CpuTaskProfile(CpuCounters):
    task: str = Field(min_length=1)
    cluster: str = Field(min_length=1)


def _cpu_residency(value: dict[float, float] | None) -> dict[float, float] | None:
    if value is not None and (
        any(not math.isfinite(f) or f <= 0 or not math.isfinite(share) or share < 0 for f, share in value.items())
        or not math.isfinite(sum(value.values()))
        or sum(value.values()) <= 0
    ):
        raise ValueError("CPU residency needs finite positive frequencies and non-negative shares with a positive total")
    return value


class CpuClusterProfile(CpuCounters):
    # {MHz: time share}; shares are normalised by the model.
    freq_residency: dict[float, float] | None = None
    clock_gated_ratio: float | None = Field(default=None, ge=0, le=1)
    power_gated_ratio: float | None = Field(default=None, ge=0, le=1)

    _valid_residency = field_validator("freq_residency")(_cpu_residency)


class CpuDsuProfile(BaseScenarioModel):
    freq_residency: dict[float, float] | None = None
    active_ratio: float | None = Field(default=None, ge=0, le=1)
    power_gated_ratio: float | None = Field(default=None, ge=0, le=1)

    _valid_residency = field_validator("freq_residency")(_cpu_residency)


class CpuProfile(BaseScenarioModel):
    """Measured CPU placement / activity per frame (from PMU / perfetto import)."""

    evidence_ref: str | None = None
    scenario_ref: str | None = None
    variant_ref: str | None = None
    tasks: list[CpuTaskProfile] = Field(default_factory=list)
    clusters: dict[str, CpuClusterProfile] = Field(default_factory=dict)
    dsu: CpuDsuProfile | None = None

    @model_validator(mode="after")
    def _task_clusters(self) -> CpuProfile:
        names = {name.lower() for name in self.clusters}
        if len(names) != len(self.clusters):
            raise ValueError("CPU profile cluster names must be unique ignoring case")
        for task in self.tasks:
            if task.cluster.lower() not in names:
                self.clusters[task.cluster] = CpuClusterProfile()
                names.add(task.cluster.lower())
        return self


class SimulationRunConfig(BaseScenarioModel):
    sensor_modes: dict[str, SensorModeBinding] = Field(default_factory=dict)
    driver_model_overrides: dict[str, DriverInput] = Field(default_factory=dict)
    sensor_readout: dict[str, SensorTiming] = Field(default_factory=dict)
    sw_timing_projection: SwTimingProjection | None = None
    timing_profile: MeasuredTimingProfile | None = None
    asv_group: int = 4
    fps: float | None = None
    sw_margin: float = SW_MARGIN_DEFAULT
    bw_power_coeff: float = 80.0
    # Which registered power physics computes ip/memory power (sim/power_model.py).
    power_model: str = "v1-vfps"
    # BW -> memory power model (sim/bw_power.py). None keeps the built-in
    # PowerModel.memory_transfer_power_mw path (default behaviour unchanged);
    # "legacy-coeff" reproduces it via the registry, "linear-per-gbps" is the
    # N mW per GB/s rule of thumb. mw_per_gbps overrides the params/default value.
    bw_power_model: str | None = None
    bw_power_mw_per_gbps: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    # SoC-scoped power_model_params (opt-in). The service resolves the ref
    # (id or id@version) against the DB into ``power_params`` so the request
    # hash and evidence lineage cover the actual coefficients. Precedence for
    # BW: explicit bw_power_* config > params.bw > code defaults.
    power_params_ref: str | None = None
    # SW-task CPU power in the simulation total (sim/cpu_power.py).
    # None = auto: on when the resolved power_model_params carry a cpu block,
    # otherwise off (legacy totals). True / False force it.
    include_cpu_power: bool | None = None
    # Measured CPU profile (PMU per-frame cycles per task x cluster, frequency
    # residency, gating). The service resolves ``cpu_profile_ref`` (a
    # measurement evidence id) into ``cpu_profile``; with a profile, CPU power
    # follows the measured placement instead of the sw_timing estimate.
    cpu_profile_ref: str | None = None
    cpu_profile: CpuProfile | None = None
    # CPU memory traffic from the profile's bus bytes as a pseudo DMA port per
    # cluster ("cpu.<cluster>"). None = on whenever a profile is given.
    include_cpu_bw: bool | None = None
    # DVFS level policy. None / "min_level": lowest level that meets the need.
    # "same_voltage_up": per DVFS group, move to the fastest higher level at the
    # SAME voltage when the group power does not rise by more than
    # dvfs_promote_tolerance_pct (default 0) - more timing margin for free.
    dvfs_policy: Literal["min_level", "same_voltage_up"] | None = None
    dvfs_promote_tolerance_pct: float | None = Field(default=None, ge=0, le=100)
    power_params: PowerModelParams | None = None
    # Clock ledger (sim/clock_models.py). None keeps the calculated clock.
    # configured/measured are keyed by node_id, hw_name or ip_ref; a missing
    # value falls back to the calculated clock with a warning.
    clock_basis: ClockBasis | None = None
    configured_clocks: dict[str, ConfiguredClock] | None = None
    # Configured clocks per DVFS scenario (variant design_conditions.dvfs_sn,
    # e.g. IS_DVFS_SN_REAR_SINGLE_VIDEO_UHD30). The adapter folds project
    # defaults < this table < variant node_configs.<node>.sim.configured_clock
    # into the effective per-variant ``configured_clocks``.
    configured_clocks_by_dvfs_sn: dict[str, dict[str, ConfiguredClock]] | None = None
    measured_clocks: dict[str, MeasuredClock] | None = None
    # Measurement evidence (PMU clock.ip observations) the service turns into
    # measured_clocks; measured_clock_stat picks weighted mean vs dominant level.
    measured_clock_ref: str | None = None
    measured_clock_stat: MeasuredClockStat | None = None
    # Logical rail that carries BW-induced (DRAM/interconnect) power. Measured
    # captures see that power on the MIF buck, never on the initiating IP's
    # rail, so per-rail calibration needs the same attribution here.
    memory_rail: str = "MIF"
    vbat: float = 4.0
    pmic_efficiency: float = 0.85
    h_blank_margin: float = 0.05
    dvfs_overrides: dict[str, int] = Field(default_factory=dict)
    include_timeline: bool = True
    timeline_frame_count: int = Field(default=4, ge=1)
    timeline_frame_period_ms: float | None = None
    debug_trace: bool = False
    debug_trace_level: Literal["summary", "formula", "full"] = "formula"


class SimulationInputs(BaseScenarioModel):
    driver_model_report: dict[str, Any] | None = None
    scenario_id: str
    variant_id: str
    project_ref: str | None = None
    config: SimulationRunConfig
    workloads: list[IPWorkload] = Field(default_factory=list)
    port_transfers: list[PortTransferSpec] = Field(default_factory=list)
    timeline_tasks: list[dict] = Field(default_factory=list)
    timeline_edges: list[dict] = Field(default_factory=list)
    sw_task_timing: list[dict[str, Any]] = Field(default_factory=list)
    external_devices: list[dict[str, Any]] = Field(default_factory=list)
    topology_order: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Which sw_timing statistic the timeline durations use (design_conditions
    # sw_timing_case). Derived from inputs already hashed (the durations), so
    # excluded from serialisation / params_hash.
    sw_timing_case: str = Field(default="mean", exclude=True)
    # Variant DVFS scenario (design_conditions.dvfs_sn) for the MIF QoS lock;
    # informational like sw_timing_case, so excluded from params_hash.
    dvfs_sn: str | None = Field(default=None, exclude=True)


class ResolvedIPConfig(BaseScenarioModel):
    node_id: str
    instance_index: int = Field(default=0, ge=0)
    ip_ref: str | None = None
    hw_name: str
    mode: str
    required_clock_mhz: float
    base_required_clock_mhz: float = 0.0
    manual_clock_mhz: float | None = None
    clock_correction_mhz: float = 0.0
    clock_correction_reason: str | None = None
    set_clock_mhz: float
    dvfs_level: int | None = None
    dvfs_group: str | None = None
    required_voltage_mv: float
    set_voltage_mv: float
    vdd: str | None = None
    width: int = 0
    height: int = 0
    format: str | None = None
    unit_power_mw_mp: float
    ppc: float
    input_resolution_mp: float
    fps: float
    active_power_mw: float
    total_power_mw: float
    total_power_ma: float = 0.0
    vdd_leader: str | None = None
    feasible: bool = True
    infeasible_reason: str | None = None
    clock_ledger: ClockLedger | None = None
    # v2-vf clock term: share of power that scales with the set clock, the
    # throughput clock it is referenced to, and the mW the set clock adds above
    # that reference (0 under v1 or when set == reference).
    clock_power_fraction: float | None = None
    # Clock the IP physically needs (throughput, sensor ingress, v-valid,
    # stage budget): the v2-vf reference; clock above it is overhead.
    clock_ref_mhz: float = 0.0
    clock_overhead_mw: float = 0.0
    clock_gating_eff: float | None = None
    power_gating_eff: float | None = None
    leakage_mw: float | None = None
    # Static part of total_power_mw (leakage after power gating; 0 without leakage data).
    leakage_power_mw: float = 0.0
    # Same-voltage DVFS promotion applied to this IP's group: {from_mhz, to_mhz, delta_mw}.
    dvfs_promotion: dict[str, Any] | None = None


class PortBWResult(BaseScenarioModel):
    node_id: str
    ip_ref: str | None = None
    hw_name: str
    port: str
    direction: Literal["read", "write", "otf"]
    bitrate_mbps: float | None = None
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
    comp_ratio: float | None = None
    llc_weight: float | None = None
    r_w_rate: float | None = None
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
    edge_type: str | None = None
    otf_group_id: str | None = None
    latency_offset_ms: float | None = None
    bottleneck: bool = False
    bottleneck_reason: str | None = None
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
    cadence_interval_ms: float | None = None
    cadence_avg_interval_ms: float | None = None
    cadence_budget_ms: float | None = None
    cadence_slack_ms: float | None = None
    cadence_violation: bool = False
    ready_ms: float | None = None
    resource_wait_ms: float = 0.0
    token_wait_ms: float = 0.0
    critical: bool = False
    critical_path_rank: int | None = None
    predecessors: list[str] = Field(default_factory=list)


class SimRunResult(BaseScenarioModel):
    sw_timing_projection: SwTimingProjection | None = None
    timing_profile: MeasuredTimingProfile | None = None
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
    sw_task_timing: list[dict[str, Any]] = Field(default_factory=list)
    external_devices: list[dict[str, Any]] = Field(default_factory=list)
    topology_order: list[str] = Field(default_factory=list)
    vdd_power: dict[str, dict[str, float]] = Field(default_factory=dict)
    power_breakdown: dict[str, Any] = Field(default_factory=dict)
    cpu_power_mw: float = 0.0
    cpu_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    calculation_trace: dict[str, Any] | None = None
