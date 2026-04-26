from __future__ import annotations

from sqlalchemy.orm import Session

from scenario_db.db.models.evidence import Evidence
from scenario_db.models.evidence.measurement import MeasurementEvidence
from scenario_db.models.evidence.simulation import SimulationEvidence


def upsert_simulation(raw: dict, sha256: str, session: Session) -> None:
    obj = SimulationEvidence.model_validate(raw)
    row = session.get(Evidence, obj.id) or Evidence(id=obj.id)
    if row.yaml_sha256 == sha256:
        return

    row.schema_version      = obj.schema_version
    row.kind                = obj.kind
    row.scenario_ref        = str(obj.scenario_ref)
    row.variant_ref         = obj.variant_ref
    row.sw_baseline_ref     = str(obj.execution_context.sw_baseline_ref)
    row.sweep_job_id        = obj.sweep_context.sweep_job_id if obj.sweep_context else None
    row.execution_context   = obj.execution_context.model_dump(exclude_none=True)
    row.sweep_context       = obj.sweep_context.model_dump(exclude_none=True) if obj.sweep_context else None
    row.resolution_result   = obj.resolution_result.model_dump(exclude_none=True) if obj.resolution_result else None
    row.overall_feasibility = (
        str(obj.resolution_result.overall_feasibility)
        if obj.resolution_result else None
    )
    row.aggregation         = obj.aggregation.model_dump(exclude_none=True)
    row.kpi                 = dict(obj.kpi)
    row.run_info            = obj.run.model_dump(exclude_none=True)
    row.ip_breakdown        = [b.model_dump(exclude_none=True) for b in obj.ip_breakdown]
    row.artifacts           = [a.model_dump(exclude_none=True) for a in obj.artifacts]
    row.yaml_sha256         = sha256
    session.add(row)


def upsert_measurement(raw: dict, sha256: str, session: Session) -> None:
    obj = MeasurementEvidence.model_validate(raw)
    row = session.get(Evidence, obj.id) or Evidence(id=obj.id)
    if row.yaml_sha256 == sha256:
        return

    # MeasuredKpi는 float/int와 MeasuredKpi 모델이 혼재 — 직렬화 처리
    def _kpi_val(v):
        if hasattr(v, "model_dump"):
            return v.model_dump(exclude_none=True)
        return v

    row.schema_version      = obj.schema_version
    row.kind                = obj.kind
    row.scenario_ref        = str(obj.scenario_ref)
    row.variant_ref         = obj.variant_ref
    row.sw_baseline_ref     = str(obj.execution_context.sw_baseline_ref)
    row.sweep_job_id        = obj.sweep_context.sweep_job_id if obj.sweep_context else None
    row.execution_context   = obj.execution_context.model_dump(exclude_none=True)
    row.sweep_context       = obj.sweep_context.model_dump(exclude_none=True) if obj.sweep_context else None
    row.aggregation         = obj.aggregation.model_dump(exclude_none=True)
    row.kpi                 = {k: _kpi_val(v) for k, v in obj.kpi.items()}
    row.provenance          = obj.provenance.model_dump(exclude_none=True)
    row.yaml_sha256         = sha256
    session.add(row)
