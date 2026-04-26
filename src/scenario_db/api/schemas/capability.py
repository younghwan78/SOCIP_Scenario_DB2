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
