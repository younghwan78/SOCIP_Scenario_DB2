from __future__ import annotations

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import JSONB

from scenario_db.db.base import Base


class SocPlatform(Base):
    __tablename__ = "soc_platforms"

    id             = Column(Text, primary_key=True)
    schema_version = Column(Text, nullable=False)
    process_node   = Column(Text)
    memory_type    = Column(Text)
    bus_protocol   = Column(Text)
    ips            = Column(JSONB)          # list[{ref, instance_count}]
    yaml_sha256    = Column(Text, nullable=False)


class IpCatalog(Base):
    __tablename__ = "ip_catalog"

    id             = Column(Text, primary_key=True)
    schema_version = Column(Text, nullable=False)
    category       = Column(Text)
    hierarchy      = Column(JSONB)          # type, submodules
    capabilities   = Column(JSONB)          # operating_modes, supported_features
    rtl_version    = Column(Text)
    compatible_soc = Column(JSONB)          # list[str]
    yaml_sha256    = Column(Text, nullable=False)


class SwProfile(Base):
    __tablename__ = "sw_profiles"

    id             = Column(Text, primary_key=True)
    schema_version = Column(Text, nullable=False)
    metadata_      = Column("metadata", JSONB, nullable=False)
    components     = Column(JSONB, nullable=False)
    feature_flags  = Column(JSONB, nullable=False)
    compatibility  = Column(JSONB)
    yaml_sha256    = Column(Text, nullable=False)


class SwComponent(Base):
    __tablename__ = "sw_components"

    id             = Column(Text, primary_key=True)
    schema_version = Column(Text, nullable=False)
    category       = Column(Text)           # hal | kernel | firmware
    metadata_      = Column("metadata", JSONB)
    feature_flags  = Column(JSONB)
    capabilities   = Column(JSONB)
    yaml_sha256    = Column(Text, nullable=False)
