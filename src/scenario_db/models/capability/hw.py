from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from scenario_db.models.common import (
    BaseScenarioModel,
    DocumentId,
    InstanceId,
    SchemaVersion,
)


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


class IpCapabilities(BaseScenarioModel):
    operating_modes: list[OperatingMode] = Field(default_factory=list)
    supported_features: SupportedFeatures | None = None


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


class SocPlatform(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["soc"]
    process_node: str | None = None
    ips: list[IpEntry] = Field(default_factory=list)
    memory_type: str | None = None
    bus_protocol: str | None = None
