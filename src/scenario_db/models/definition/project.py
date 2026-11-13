from __future__ import annotations

from typing import Annotated, Literal

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
    values_mw: dict[str, Annotated[float, Field(gt=0, allow_inf_nan=False)]] = Field(default_factory=dict)
    # up to this much above the reference still counts as "similar" (medium risk); above it is high
    tolerance_pct: float = Field(default=3.0, ge=0, le=50)
    source_note: str | None = None
    # REF-01: which previous-project value wins when several exist. "measurement" = silicon capture only;
    # synthetic measurements are used last, after every listed source.
    source_priority: list[Literal["explicit", "measurement", "prediction"]] = Field(
        default_factory=lambda: ["explicit", "measurement", "prediction"], min_length=1, max_length=3)
    # REF-02: current variant id -> previous project's variant id, when the names differ
    mapping: dict[str, str] = Field(default_factory=dict)
    # REF-02: design conditions compared with the previous variant (None = resolution, fps, HDR, sensor, IS version, bitrate ...)
    compare_keys: list[str] | None = Field(default=None, max_length=20)


class ThermalWatch(BaseScenarioModel):
    """A scenario where customers typically ask for power reduction (thermal limits depend on the board)."""
    scenario_ref: DocumentId
    variant_ref: str
    label: str | None = None
    # reduction asks to pre-check, % of the current prediction
    reduction_pct: list[Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]] = Field(default_factory=lambda: [10.0, 20.0])
    note: str | None = None


class SustainedCurrent(BaseScenarioModel):
    """Thermal rule used at the spec stage: a scenario that keeps AP + memory above this battery current for long
    is a power-cut candidate. Temperature itself depends on the phone's heat dissipation, so the current is judged.

    AP + mem = predicted total (CPU + IP + BW incl. DRAM, plus declared assumed loads) + ``base_mw``; mA = mW ÷ Vbat ÷
    PMIC efficiency (the run's config profile, default 4.0 V · 0.85)."""
    limit_ma: float = Field(gt=0, le=20000, allow_inf_nan=False)
    # at or above limit × watch_ratio = 주의 (medium)
    watch_ratio: float = Field(default=0.85, gt=0, le=1.0, allow_inf_nan=False)
    # AP power the scenario model does not carry (always-on, idle domains, other masters), added before converting
    base_mw: float = Field(default=0.0, ge=0, le=20000, allow_inf_nan=False)
    note: str | None = None


IpGroup = Literal["ISP", "Codec", "DPU", "GPU", "NPU", "기타 IP"]


class KpiVariant(BaseScenarioModel):
    """COV-03: a customer KPI scenario shown on the one-page summary (in list order)."""
    variant_ref: str
    scenario_ref: DocumentId | None = None  # None = the variant id is unique in the project
    label: str | None = None
    tier: Literal["base", "heavy", "thermal"] = "base"


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
    # COV-03: KPI scenarios of the one-page summary; empty = thermal watch + reference variants
    kpi: list[KpiVariant] = Field(default_factory=list, max_length=40)
    # SW-03: SW growth the next project must absorb (shown on the summary; ×1.0 = none declared)
    sw_growth_budget: float | None = Field(default=None, ge=1.0, le=3.0)
    # exploration recommendation: what it prefers, most important first (power / growth / iq / bw);
    # None = lowest power (previous behaviour). With "growth", sw_growth_budget is the growth to reach.
    objective_order: list[Literal["power", "growth", "iq", "bw"]] | None = Field(default=None, min_length=1, max_length=4)
    # sustained AP + mem battery current rule (thermal); None = previous behaviour (thermal_watch −10 / −20 % only)
    sustained_current: SustainedCurrent | None = None
    # IP node (glob, e.g. "front_*", "mfc*") -> report power group; overrides the built-in node-name rules
    ip_groups: dict[str, IpGroup] = Field(default_factory=dict, max_length=200)
    # scenario id (glob, e.g. "uc-cam-rec*") -> report category (level 1); overrides the built-in scenario-id rules
    categories: dict[str, Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=dict, max_length=100)


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
