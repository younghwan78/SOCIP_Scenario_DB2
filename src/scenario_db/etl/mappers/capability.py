from __future__ import annotations

from sqlalchemy.orm import Session

from scenario_db.db.models.capability import IpCatalog, SocDvfsTable, SocPlatform, SwComponent, SwProfile
from scenario_db.models.capability.hw import IpCatalog as PydanticIp
from scenario_db.models.capability.hw import SocDvfsTable as PydanticSocDvfsTable
from scenario_db.models.capability.hw import SocPlatform as PydanticSoc
from scenario_db.models.capability.sw import SwComponent as PydanticSwComponent
from scenario_db.models.capability.sw import SwProfile as PydanticSwProfile


def upsert_soc(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticSoc.model_validate(raw)
    row = session.get(SocPlatform, obj.id) or SocPlatform(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.process_node   = obj.process_node
    row.memory_type    = obj.memory_type
    row.bus_protocol   = obj.bus_protocol
    row.ips            = [e.model_dump(exclude_none=True) for e in obj.ips]
    row.yaml_sha256    = sha256
    session.add(row)


def upsert_soc_dvfs_table(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticSocDvfsTable.model_validate(raw)
    row = session.get(SocDvfsTable, obj.id) or SocDvfsTable(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.soc_ref = str(obj.soc_ref)
    row.dvfs_version = obj.dvfs_version
    row.evt_hint = obj.evt_hint
    row.source = obj.source.model_dump(exclude_none=True) if obj.source else None
    row.domains = {
        key: value.model_dump(exclude_none=True)
        for key, value in obj.domains.items()
    }
    row.compatibility_scope = obj.compatibility_scope
    row.source_project_ref = str(obj.source_project_ref) if obj.source_project_ref else None
    row.domain_schema_hash = obj.domain_schema_hash
    row.yaml_sha256 = sha256
    session.add(row)


def upsert_ip(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticIp.model_validate(raw)
    row = session.get(IpCatalog, obj.id) or IpCatalog(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.category       = obj.category
    row.hierarchy      = obj.hierarchy.model_dump(exclude_none=True)
    row.capabilities   = obj.capabilities.model_dump(exclude_none=True) if obj.capabilities else None
    row.rtl_version    = obj.rtl_version
    row.compatible_soc = list(obj.compatible_soc)
    row.yaml_sha256    = sha256
    session.add(row)


def upsert_sw_profile(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticSwProfile.model_validate(raw)
    row = session.get(SwProfile, obj.id) or SwProfile(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.metadata_      = obj.metadata.model_dump(exclude_none=True)
    row.components     = obj.components.model_dump(exclude_none=True)
    row.feature_flags  = dict(obj.feature_flags)
    row.compatibility  = obj.compatibility.model_dump(exclude_none=True) if obj.compatibility else None
    row.yaml_sha256    = sha256
    session.add(row)


def upsert_sw_component(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticSwComponent.model_validate(raw)
    row = session.get(SwComponent, obj.id) or SwComponent(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.category       = obj.category
    row.metadata_      = obj.metadata.model_dump(exclude_none=True) if obj.metadata else None
    row.feature_flags  = dict(obj.feature_flags) if obj.feature_flags else None
    row.capabilities   = obj.capabilities.model_dump(exclude_none=True) if obj.capabilities else None
    row.yaml_sha256    = sha256
    session.add(row)
