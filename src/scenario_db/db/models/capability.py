from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Text, UniqueConstraint
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
    compression_modes = Column(JSONB)       # {mode: {compressor, comp_ratio}}
    yaml_sha256    = Column(Text, nullable=False)


class SocDvfsTable(Base):
    __tablename__ = "soc_dvfs_tables"
    __table_args__ = (
        UniqueConstraint("soc_ref", "dvfs_version", name="uq_soc_dvfs_tables_soc_version"),
    )

    id                 = Column(Text, primary_key=True)
    schema_version     = Column(Text, nullable=False)
    soc_ref            = Column(Text, ForeignKey("soc_platforms.id"), nullable=False)
    dvfs_version       = Column(Integer, nullable=False)
    evt_hint           = Column(Text)
    source             = Column(JSONB)
    domains            = Column(JSONB, nullable=False)
    compatibility_scope = Column(Text, nullable=False)
    source_project_ref = Column(Text)
    domain_schema_hash = Column(Text)
    yaml_sha256        = Column(Text, nullable=False)


class SocCdgmProfile(Base):
    __tablename__ = "soc_cdgm_profiles"
    __table_args__ = (
        UniqueConstraint("soc_ref", "profile_version", name="uq_soc_cdgm_profiles_soc_version"),
        CheckConstraint("profile_version >= 0", name="ck_soc_cdgm_profiles_profile_version_nonnegative"),
        CheckConstraint("compatibility_scope in ('soc', 'project')", name="ck_soc_cdgm_profiles_scope"),
    )

    id                  = Column(Text, primary_key=True)
    schema_version      = Column(Text, nullable=False)
    soc_ref             = Column(Text, ForeignKey("soc_platforms.id"), nullable=False)
    profile_version     = Column(Integer, nullable=False)
    evt_hint            = Column(Text)
    source              = Column(JSONB)
    compatibility_scope = Column(Text, nullable=False)
    source_project_ref  = Column(Text)
    domain_schema_hash  = Column(Text)
    role_overrides      = Column(JSONB, nullable=False)
    selection_policy    = Column(JSONB, nullable=False)
    yaml_sha256         = Column(Text, nullable=False)


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


class SimConfigProfile(Base):
    """과제·SoC별 합의된 시뮬레이션 설정 (정합 iteration의 재현 단위)."""

    __tablename__ = "sim_config_profiles"
    __table_args__ = (
        CheckConstraint("status in ('draft', 'approved')", name="ck_simcfg_status"),
    )

    id              = Column(Text, primary_key=True)
    schema_version  = Column(Text, nullable=False)
    project_ref     = Column(Text, ForeignKey("projects.id"), index=True)
    soc_ref         = Column(Text, ForeignKey("soc_platforms.id"), index=True)
    version         = Column(Integer, nullable=False, default=1)
    status          = Column(Text, nullable=False, default="draft")
    approved_by     = Column(Text)
    description     = Column(Text)
    run_config      = Column(JSONB, nullable=False)  # SimulationRunConfig 기본값 (None=미고정)
    rail_domain_map = Column(JSONB)                  # 벤치 physical rail -> power domain
    notes           = Column(Text)
    yaml_sha256     = Column(Text, nullable=False)
