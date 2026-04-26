from __future__ import annotations

from sqlalchemy import Column, Computed, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB

from scenario_db.db.base import Base


class SweepJob(Base):
    __tablename__ = "sweep_jobs"

    id             = Column(Text, primary_key=True)
    scenario_ref   = Column(Text, ForeignKey("scenarios.id"), nullable=False)
    variant_ref    = Column(Text, nullable=False)
    sweep_axis     = Column(Text, nullable=False)
    sweep_values   = Column(JSONB, nullable=False)
    total_runs     = Column(Integer, nullable=False)
    completed_runs = Column(Integer, default=0)
    status         = Column(Text)
    launched_at    = Column(DateTime(timezone=True))
    completed_at   = Column(DateTime(timezone=True))


class Evidence(Base):
    __tablename__ = "evidence"

    id                  = Column(Text, primary_key=True)
    schema_version      = Column(Text, nullable=False)
    kind                = Column(Text, nullable=False)  # evidence.simulation | evidence.measurement
    scenario_ref        = Column(Text, ForeignKey("scenarios.id"), nullable=False)
    variant_ref         = Column(Text, nullable=False)
    sw_baseline_ref     = Column(Text, ForeignKey("sw_profiles.id"))
    sweep_job_id        = Column(Text, ForeignKey("sweep_jobs.id"))
    execution_context   = Column(JSONB, nullable=False)
    sweep_context       = Column(JSONB)
    resolution_result   = Column(JSONB)
    overall_feasibility = Column(Text)              # 승격 컬럼 — 쿼리 최적화
    aggregation         = Column(JSONB, nullable=False)
    kpi                 = Column(JSONB, nullable=False)
    run_info            = Column(JSONB)             # sim only
    ip_breakdown        = Column(JSONB)             # sim only
    provenance          = Column(JSONB)             # meas only
    artifacts           = Column(JSONB)
    yaml_sha256         = Column(Text, nullable=False)
    # §22 Generated columns (PostgreSQL ≥12) — ::text 캐스트 + index=True
    sw_version_hint     = Column(
        Text,
        Computed("(execution_context->>'sw_baseline_ref')::text", persisted=True),
        index=True,
    )
    sweep_value_hint    = Column(
        Text,
        Computed("(sweep_context->>'sweep_value')::text", persisted=True),
        index=True,
    )
