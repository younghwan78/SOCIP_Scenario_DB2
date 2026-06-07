from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SocPlatformResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: str
    process_node: str | None = None
    memory_type: str | None = None
    bus_protocol: str | None = None
    ips: list | dict | None = None


class SocDvfsTableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: str
    soc_ref: str
    dvfs_version: int
    evt_hint: str | None = None
    source: dict | None = None
    domains: dict = {}
    compatibility_scope: str
    source_project_ref: str | None = None
    domain_schema_hash: str | None = None


class SocCdgmProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: str
    soc_ref: str
    profile_version: int
    evt_hint: str | None = None
    source: dict | None = None
    compatibility_scope: str
    source_project_ref: str | None = None
    domain_schema_hash: str | None = None
    role_overrides: dict = {}
    selection_policy: dict = {}


class IpCatalogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: str
    category: str | None = None
    hierarchy: dict | None = None
    capabilities: dict | None = None
    rtl_version: str | None = None
    compatible_soc: list | None = None


class SwProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: str
    metadata_: dict = {}
    components: dict = {}
    feature_flags: dict = {}
    compatibility: dict | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SwComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    schema_version: str
    category: str | None = None
    metadata_: dict | None = None
    feature_flags: dict | None = None
    capabilities: dict | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
