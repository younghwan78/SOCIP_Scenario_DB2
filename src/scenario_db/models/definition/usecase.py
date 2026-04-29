from __future__ import annotations

from enum import StrEnum  # EdgeType에서 사용
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scenario_db.models.common import (
    BaseScenarioModel,
    DocumentId,
    FeatureFlagValue,
    SchemaVersion,
    Severity,
    ViolationAction,
    ViolationClassification,
)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class PipelineNode(BaseScenarioModel):
    id: str
    ip_ref: DocumentId
    instance_index: int = 0
    role: str | None = None


class EdgeType(StrEnum):
    OTF = "OTF"
    M2M = "M2M"


class PipelineEdge(BaseModel):
    # "from" is a Python keyword — use alias
    # populate_by_name=True: accepts both "from" (YAML) and "from_" (Python)
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    type: EdgeType
    buffer: str | None = None


class Pipeline(BaseScenarioModel):
    nodes: list[PipelineNode] = Field(default_factory=list)
    edges: list[PipelineEdge] = Field(default_factory=list)
    buffers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    architecture_graph: dict[str, Any] = Field(default_factory=dict)
    task_graph: dict[str, Any] = Field(default_factory=dict)
    level1_graph: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_edge_references(self) -> Pipeline:
        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.from_ not in node_ids:
                raise ValueError(
                    f"Edge source '{edge.from_}' not found in nodes {node_ids}"
                )
            if edge.to not in node_ids:
                raise ValueError(
                    f"Edge target '{edge.to}' not found in nodes {node_ids}"
                )
        return self


# ---------------------------------------------------------------------------
# Size / Axes
# ---------------------------------------------------------------------------

class SizeProfile(BaseScenarioModel):
    anchors: dict[str, str] = Field(default_factory=dict)


class DesignAxis(BaseScenarioModel):
    name: str
    enum: list[str | int | float]


# ---------------------------------------------------------------------------
# IP Requirements
# ---------------------------------------------------------------------------

class IpRequirementSpec(BaseModel):
    # extra="allow": per-IP fields are heterogeneous (isp/mfc/llc differ)
    # known limitation: typos pass silently → Phase 3 will refactor to Discriminated Union
    model_config = ConfigDict(extra="allow")
    required_throughput_mpps: float | None = None
    required_bitdepth: int | None = None
    required_features: list[str] = Field(default_factory=list)
    required_codec: str | None = None
    required_level: str | None = None
    required_allocations: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# SW Requirements
# ---------------------------------------------------------------------------

class ProfileConstraints(BaseScenarioModel):
    min_version: str | None = None
    baseline_family: list[str] = Field(default_factory=list)


class HalVersionConstraint(BaseScenarioModel):
    min_version: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)


class SwRequirements(BaseScenarioModel):
    profile_constraints: ProfileConstraints | None = None
    # Each item is a single-key dict: [{"LLC_dynamic_allocation": "enabled"}, ...]
    required_features: list[dict[str, FeatureFlagValue]] = Field(default_factory=list)
    required_hal: dict[str, HalVersionConstraint] = Field(default_factory=dict)
    required_firmware: dict[str, dict[str, str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Violation Policy
# ---------------------------------------------------------------------------

class PerRequirementPolicy(BaseScenarioModel):
    action: ViolationAction
    cap_source: str | None = None
    report_gap: bool | None = None
    emulation_strategy: str | None = None


class OverallPolicy(BaseScenarioModel):
    if_any_fail: Literal["abort_simulation", "continue_with_flag"]
    if_any_warn: Literal["abort_simulation", "continue_with_flag"] | None = None
    flag_label: str | None = None
    report_level: Literal["error", "warning", "info"] | None = None
    result_flag: str | None = None


class ViolationPolicy(BaseScenarioModel):
    classification: ViolationClassification
    # key: "default" or dotted path like "isp0.required_throughput_mpps"
    per_requirement: dict[str, PerRequirementPolicy] = Field(default_factory=dict)
    overall: OverallPolicy | None = None


# ---------------------------------------------------------------------------
# Variant
# ---------------------------------------------------------------------------

class Variant(BaseScenarioModel):
    id: str  # free-form: "UHD60-HDR10-H265" — not a DocumentId
    severity: Severity
    design_conditions: dict[str, str | int | float] = Field(default_factory=dict)
    size_overrides: dict[str, str] = Field(default_factory=dict)
    routing_switch: dict[str, Any] = Field(default_factory=dict)
    topology_patch: dict[str, Any] = Field(default_factory=dict)
    node_configs: dict[str, Any] = Field(default_factory=dict)
    buffer_overrides: dict[str, Any] = Field(default_factory=dict)
    ip_requirements: dict[str, IpRequirementSpec] = Field(default_factory=dict)
    sw_requirements: SwRequirements | None = None
    violation_policy: ViolationPolicy | None = None
    tags: list[str] = Field(default_factory=list)
    derived_from_variant: str | None = None
    design_conditions_override: dict[str, str | int | float] | None = None


# ---------------------------------------------------------------------------
# Usecase top-level pieces
# ---------------------------------------------------------------------------

class InheritancePolicy(BaseScenarioModel):
    max_depth: int = 3
    cycle_detection: Literal["required", "optional"] = "required"


class ParametricSweep(BaseScenarioModel):
    id: str
    applies_to: list[str] = Field(default_factory=list)
    axis: str
    values: list[str | int | float] = Field(default_factory=list)


class UsecaseReferences(BaseScenarioModel):
    known_issues: list[DocumentId] = Field(default_factory=list)


class UsecaseMetadata(BaseScenarioModel):
    name: str
    category: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Usecase (Definition Layer root)
# ---------------------------------------------------------------------------

class Usecase(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["scenario.usecase"]
    project_ref: DocumentId
    metadata: UsecaseMetadata
    pipeline: Pipeline
    size_profile: SizeProfile | None = None
    design_axes: list[DesignAxis] = Field(default_factory=list)
    variants: list[Variant] = Field(default_factory=list)
    inheritance_policy: InheritancePolicy | None = None
    parametric_sweeps: list[ParametricSweep] = Field(default_factory=list)
    references: UsecaseReferences | None = None

    @model_validator(mode="after")
    def _validate_no_inheritance_cycle(self) -> Usecase:
        parent_map = {
            v.id: v.derived_from_variant
            for v in self.variants
            if v.derived_from_variant is not None
        }
        for start in parent_map:
            visited: set[str] = set()
            current: str | None = start
            while current in parent_map:
                if current in visited:
                    raise ValueError(
                        f"Circular inheritance detected at variant '{current}'"
                    )
                visited.add(current)
                current = parent_map[current]
        return self

    @model_validator(mode="after")
    def _validate_violation_policy_node_refs(self) -> Usecase:
        node_ids = {node.id for node in self.pipeline.nodes}
        for variant in self.variants:
            if not variant.violation_policy:
                continue
            for key in variant.violation_policy.per_requirement:
                if key == "default":
                    continue
                node_ref = key.split(".")[0]
                if node_ref not in node_ids:
                    raise ValueError(
                        f"Variant '{variant.id}': violation_policy key '{key}' "
                        f"references unknown pipeline node '{node_ref}'"
                    )
        return self
