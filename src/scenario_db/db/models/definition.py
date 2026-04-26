from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB

from scenario_db.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id             = Column(Text, primary_key=True)
    schema_version = Column(Text, nullable=False)
    metadata_      = Column("metadata", JSONB, nullable=False)
    globals_       = Column("globals", JSONB)
    yaml_sha256    = Column(Text, nullable=False)


class Scenario(Base):
    __tablename__ = "scenarios"

    id             = Column(Text, primary_key=True)
    schema_version = Column(Text, nullable=False)
    project_ref    = Column(Text, ForeignKey("projects.id"), nullable=False)
    metadata_      = Column("metadata", JSONB, nullable=False)
    pipeline       = Column(JSONB, nullable=False)
    size_profile   = Column(JSONB)
    design_axes    = Column(JSONB)
    yaml_sha256    = Column(Text, nullable=False)


class ScenarioVariant(Base):
    __tablename__ = "scenario_variants"

    scenario_id          = Column(Text, ForeignKey("scenarios.id"), primary_key=True)
    id                   = Column(Text, primary_key=True)   # freeform: "UHD60-HDR10-H265"
    severity             = Column(Text)
    design_conditions    = Column(JSONB)
    ip_requirements      = Column(JSONB)
    sw_requirements      = Column(JSONB)
    violation_policy     = Column(JSONB)
    tags                 = Column(JSONB)                    # list[str]
    derived_from_variant = Column(Text)
