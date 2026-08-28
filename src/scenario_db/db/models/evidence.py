from __future__ import annotations

from sqlalchemy import ARRAY, CheckConstraint, Column, Computed, DateTime, ForeignKey, Index, Integer, Text
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
    __table_args__ = (
        CheckConstraint(
            "kind in ('evidence.simulation', 'evidence.measurement')",
            name="ck_evidence_kind",
        ),
        Index("idx_ev_scenario_variant", "scenario_ref", "variant_ref"),
    )

    id                  = Column(Text, primary_key=True)
    schema_version      = Column(Text, nullable=False)
    kind                = Column(Text, nullable=False)  # evidence.simulation | evidence.measurement
    scenario_ref        = Column(Text, ForeignKey("scenarios.id"), nullable=False)
    variant_ref         = Column(Text, nullable=False)
    project_ref         = Column(Text, ForeignKey("projects.id"), index=True)
    measured_at         = Column(DateTime(timezone=True), index=True)  # meas: 측정 시각, projection: 산출 시각
    derived_from        = Column(JSONB)             # lineage: 원본 evidence id 목록
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
    dma_breakdown       = Column(JSONB)             # sim only
    timing_breakdown    = Column(JSONB)             # sim only
    dvfs_breakdown      = Column(JSONB)             # sim only
    timeline_events     = Column(JSONB)             # sim + meas
    external_devices    = Column(JSONB)             # sim only
    topology_order      = Column(ARRAY(Text))       # sim only
    vdd_power           = Column(JSONB)             # sim + meas (rail별 전력)
    calculation_trace   = Column(JSONB)             # sim debug trace, optional
    params_hash         = Column(Text, index=True)  # sim cache key
    provenance          = Column(JSONB)             # meas only
    cpu_breakdown       = Column(JSONB)             # meas: cluster별 power/freq residency digest
    sw_task_timing      = Column(JSONB)             # meas: perfetto 기반 task별 수행시간 digest
    metric_observations = Column(JSONB)             # sim + meas: catalog-validated comparable metrics
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
