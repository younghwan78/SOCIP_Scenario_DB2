from __future__ import annotations

from typing import Literal

from pydantic import Field

from scenario_db.models.common import (
    BaseScenarioModel,
    DocumentId,
    FeatureFlagValue,
    RegressionRisk,
    SchemaVersion,
)


# ---------------------------------------------------------------------------
# SW Profile components
# ---------------------------------------------------------------------------

class HalRef(BaseScenarioModel):
    domain: str
    ref: DocumentId


class KernelRef(BaseScenarioModel):
    ref: DocumentId
    config_deltas: list[str] = Field(default_factory=list)


class FirmwareRef(BaseScenarioModel):
    target: str
    ref: DocumentId


class SwComponents(BaseScenarioModel):
    hal: list[HalRef] = Field(default_factory=list)
    kernel: KernelRef | None = None
    firmware: list[FirmwareRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Compatibility / regression tracking
# ---------------------------------------------------------------------------

class BreakingChange(BaseScenarioModel):
    area: str
    description: str
    regression_risk: RegressionRisk


class Compatibility(BaseScenarioModel):
    replaces: DocumentId | None = None
    min_compatible_version: str | None = None
    breaking_changes: list[BreakingChange] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SW Profile (sw-*.yaml)
# ---------------------------------------------------------------------------

class SwProfileMetadata(BaseScenarioModel):
    baseline_family: Literal["vendor", "aosp", "engineering"]
    version: str
    release_date: str | None = None
    release_type: Literal["engineering", "beta", "production"] | None = None
    compatible_soc: list[DocumentId] = Field(default_factory=list)
    git_branch: str | None = None
    git_commit_sha: str | None = None


class KnownIssueRef(BaseScenarioModel):
    ref: DocumentId
    status: str


class SwProfile(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["sw_profile"]
    metadata: SwProfileMetadata
    components: SwComponents
    feature_flags: dict[str, FeatureFlagValue] = Field(default_factory=dict)
    compatibility: Compatibility | None = None
    known_issues_at_release: list[KnownIssueRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SW Component (hal-*.yaml / kernel-*.yaml / fw-*.yaml)
# ---------------------------------------------------------------------------

class HwBindings(BaseScenarioModel):
    required_ips: list[DocumentId] = Field(default_factory=list)
    required_min_ip_version: dict[str, str] = Field(default_factory=dict)


class SwComponentMetadata(BaseScenarioModel):
    name: str | None = None
    version: str
    compatible_soc: list[DocumentId] = Field(default_factory=list)
    source: str | None = None


class SwComponent(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["sw_component"]
    category: Literal["hal", "kernel", "firmware"]
    metadata: SwComponentMetadata
    feature_flags: dict[str, FeatureFlagValue] = Field(default_factory=dict)
    capabilities: dict[str, FeatureFlagValue | list | dict] | None = None
    hw_bindings: HwBindings | None = None
    # Interface contracts this component depends on (e.g. AIDL spec, ioctl version)
    required_interfaces: list[str] | None = None
    performance_notes: dict[str, float] | None = None
