"""Private/shared experiments contain frozen results, never official predictions."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Text, Integer, Boolean, func
from sqlalchemy.dialects.postgresql import JSONB

from scenario_db.db.base import Base


class WhatIfExperiment(Base):
    __tablename__ = "whatif_experiments"
    __table_args__ = (
        CheckConstraint("visibility in ('private', 'shared')", name="ck_whatif_visibility"),
        Index("idx_whatif_scope", "project_ref", "scenario_ref", "variant_ref", "created_at"),
        Index("idx_whatif_owner", "created_by", "created_at"),
    )
    id = Column(Text, primary_key=True)
    project_ref = Column(Text, ForeignKey("projects.id"), nullable=False)
    scenario_ref = Column(Text, ForeignKey("scenarios.id"), nullable=False)
    variant_ref = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    purpose = Column(Text)
    description = Column(Text)
    assumptions = Column(Text)
    conclusion = Column(Text)
    query = Column(Text)
    visibility = Column(Text, nullable=False)
    created_by = Column(Text, nullable=False)
    baseline_hash = Column(Text, nullable=False)
    condition_hash = Column(Text, nullable=False)
    preview_request = Column(JSONB, nullable=False)
    normalized_condition = Column(JSONB, nullable=False)
    result = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WhatIfJob(Base):
    __tablename__ = "whatif_jobs"
    __table_args__ = (
        CheckConstraint("status in ('queued','running','completed','cancelled','failed','interrupted')", name="ck_whatif_job_status"),
        Index("idx_whatif_job_actor", "created_by", "created_at"),
    )
    id = Column(Text, primary_key=True)
    project_ref = Column(Text, ForeignKey("projects.id"), nullable=False)
    created_by = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    request = Column(JSONB, nullable=False)
    result = Column(JSONB)
    error = Column(Text)
    completed_cases = Column(Integer, nullable=False, default=0)
    total_cases = Column(Integer, nullable=False)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    worker_token = Column(Text)
    heartbeat_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
