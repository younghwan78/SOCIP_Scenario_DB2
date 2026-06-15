from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from scenario_db.models.common import (
    BaseScenarioModel,
    DocumentId,
    InstanceId,
    SchemaVersion,
)
from scenario_db.sim.models import DVFSTable


# ---------------------------------------------------------------------------
# Operating modes
# ---------------------------------------------------------------------------

class OperatingMode(BaseScenarioModel):
    id: str
    throughput_mpps: float | None = None
    max_clock_mhz: float | None = None
    min_clock_mhz: float | None = None
    power_mW: float | None = None


class SupportedFeatures(BaseScenarioModel):
    bitdepth: list[int] = Field(default_factory=list)
    hdr_formats: list[str] = Field(default_factory=list)
    compression: list[str] = Field(default_factory=list)
    crop: bool | None = None
    scale: bool | None = None
    rotate: bool | None = None


class IpCapabilities(BaseScenarioModel):
    operating_modes: list[OperatingMode] = Field(default_factory=list)
    supported_features: SupportedFeatures | None = None
    sim: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------

class SubmoduleRef(BaseScenarioModel):
    """Reference from a composite IP to one of its submodules.

    ref        → DocumentId pointing to a sub-*.yaml document
    instance_id → runtime path name (e.g. ISP.TNR); InstanceId type
                  enforces the 1-depth ceiling — no nested SubmoduleRef possible
    """
    ref: DocumentId
    instance_id: InstanceId


class IpHierarchy(BaseScenarioModel):
    type: Literal["simple", "composite"]
    submodules: list[SubmoduleRef] | None = None

    @model_validator(mode="after")
    def _check_submodules_only_for_composite(self) -> IpHierarchy:
        if self.type == "simple" and self.submodules:
            raise ValueError("simple hierarchy must not declare submodules")
        if self.type == "composite" and not self.submodules:
            raise ValueError("composite hierarchy must declare at least one submodule")
        return self


# ---------------------------------------------------------------------------
# IP Submodule (sub-*.yaml)
# ---------------------------------------------------------------------------

class IpSubmodule(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["submodule"]
    category: str
    parent_ip_ref: DocumentId | None = None
    capabilities: IpCapabilities | None = None


# ---------------------------------------------------------------------------
# IP Catalog entry (ip-*.yaml)
# ---------------------------------------------------------------------------

class IpCatalog(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["ip"]
    category: str
    hierarchy: IpHierarchy
    capabilities: IpCapabilities
    rtl_version: str | None = None
    compatible_soc: list[DocumentId] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# SoC Platform (soc-*.yaml)
# ---------------------------------------------------------------------------

class IpEntry(BaseScenarioModel):
    """Thin reference to an IP within a SoC."""
    ref: DocumentId
    instance_count: int = 1


class CompressionMode(BaseScenarioModel):
    """One declared DMA compression mode and its representative BW behaviour.

    The mode key (e.g. COMP_YUV_LOSSY) names the content class + quality a DMA
    port may select; COMP_OFF is implicit (no entry needed, ratio 1.0). Pixel
    subsampling (420/422/444) is NOT encoded here — it lives in the buffer
    format and is already captured by the bandwidth model's bpp factor.

    comp_ratio is the only value the bandwidth model consumes: the fraction of
    uncompressed BW that remains (1.0 = no reduction, 0.5 = half). compressor
    records the providing HW block (SBWC / SAJC / ...) for display and grouping.
    """
    compressor: str
    comp_ratio: float
    note: str | None = None

    @model_validator(mode="after")
    def _validate_comp_ratio(self) -> CompressionMode:
        if not 0.0 < self.comp_ratio <= 1.0:
            raise ValueError("comp_ratio must be in (0, 1]")
        return self


class SocPlatform(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["soc"]
    process_node: str | None = None
    ips: list[IpEntry] = Field(default_factory=list)
    memory_type: str | None = None
    bus_protocol: str | None = None
    # mode name -> {compressor, comp_ratio}. SSOT for per-mode BW reduction;
    # DMA ports reference these names in capabilities.properties.modules[].
    compression_modes: dict[str, CompressionMode] = Field(default_factory=dict)


class SocDvfsTableSource(BaseScenarioModel):
    guide_name: str | None = None
    source_revision: str | None = None
    path: str | None = None
    note: str | None = None


class SocDvfsTable(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["soc.dvfs_table"]
    soc_ref: DocumentId
    dvfs_version: int
    evt_hint: str | None = None
    source: SocDvfsTableSource | None = None
    domains: dict[str, DVFSTable] = Field(default_factory=dict)
    compatibility_scope: Literal["soc", "project"] = "soc"
    source_project_ref: DocumentId | None = None
    domain_schema_hash: str | None = None

    @model_validator(mode="after")
    def _validate_dvfs_table(self) -> SocDvfsTable:
        if self.dvfs_version < 0:
            raise ValueError("dvfs_version must be non-negative")
        for key, table in self.domains.items():
            if table.domain != key:
                raise ValueError(f"domains.{key}.domain must match the domain key")
        return self


class CdgmProfileSource(SocDvfsTableSource):
    pass


class CdgmRoleOverride(BaseScenarioModel):
    extends: str | None = None
    ip_ref: DocumentId | None = None
    arch_ip: str
    path_type: Literal["rt", "nrt", "codec", "input", "output", "generic"] = "generic"
    ppc: float
    vdd: str | None = None
    dvfs_domain: str
    pos: list[str] = Field(default_factory=list)
    when: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_role_override(self) -> CdgmRoleOverride:
        if self.ppc <= 0:
            raise ValueError("ppc must be positive")
        if self.path_type == "nrt" and not self.pos:
            raise ValueError("nrt CDGM role override must declare pos")
        return self


class SocCdgmProfile(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["soc.cdgm_profile"]
    soc_ref: DocumentId
    profile_version: int
    evt_hint: str | None = None
    source: CdgmProfileSource | None = None
    compatibility_scope: Literal["soc", "project"] = "soc"
    source_project_ref: DocumentId | None = None
    domain_schema_hash: str | None = None
    role_overrides: dict[str, CdgmRoleOverride] = Field(default_factory=dict)
    selection_policy: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_cdgm_profile(self) -> SocCdgmProfile:
        if self.profile_version < 0:
            raise ValueError("profile_version must be non-negative")
        if self.compatibility_scope == "project" and not self.source_project_ref:
            raise ValueError("source_project_ref is required when compatibility_scope is project")
        return self
