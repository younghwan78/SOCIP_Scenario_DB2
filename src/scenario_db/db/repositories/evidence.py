"""Evidence 도메인 — Evidence, SweepJob."""
from __future__ import annotations

from sqlalchemy.orm import Session

from scenario_db.api.pagination import apply_sort
from scenario_db.db.models.evidence import Evidence
from scenario_db.models.evidence.simulation import SimulationEvidence


def list_evidence(
    db: Session,
    *,
    scenario_ref: str | None = None,
    variant_ref: str | None = None,
    sw_version_hint: str | None = None,
    overall_feasibility: str | None = None,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[Evidence], int]:
    q = db.query(Evidence)
    if scenario_ref is not None:
        q = q.filter(Evidence.scenario_ref == scenario_ref)
    if variant_ref is not None:
        q = q.filter(Evidence.variant_ref == variant_ref)
    if sw_version_hint is not None:
        q = q.filter(Evidence.sw_version_hint == sw_version_hint)
    if overall_feasibility is not None:
        q = q.filter(Evidence.overall_feasibility == overall_feasibility)
    q = apply_sort(q, Evidence, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_evidence(db: Session, evidence_id: str) -> Evidence | None:
    return db.query(Evidence).filter_by(id=evidence_id).one_or_none()


def delete_simulation_evidence(db: Session, evidence_id: str) -> bool:
    row = db.query(Evidence).filter_by(id=evidence_id).one_or_none()
    if row is None or row.kind != "evidence.simulation":
        return False
    db.delete(row)
    return True


def update_simulation_artifacts(
    db: Session,
    evidence_id: str,
    artifacts: list[dict],
) -> Evidence | None:
    row = db.query(Evidence).filter_by(id=evidence_id).one_or_none()
    if row is None or row.kind != "evidence.simulation":
        return None
    replacement_types = {str(item.get("type")) for item in artifacts if isinstance(item, dict)}
    existing = [
        item
        for item in row.artifacts or []
        if not isinstance(item, dict) or str(item.get("type")) not in replacement_types
    ]
    row.artifacts = existing + [dict(item) for item in artifacts if isinstance(item, dict)]
    db.add(row)
    return row


def get_simulation_evidence_by_params_hash(
    db: Session,
    *,
    scenario_ref: str,
    variant_ref: str,
    params_hash: str,
) -> Evidence | None:
    return (
        db.query(Evidence)
        .filter_by(
            kind="evidence.simulation",
            scenario_ref=scenario_ref,
            variant_ref=variant_ref,
            params_hash=params_hash,
        )
        .order_by(Evidence.id.desc())
        .first()
    )


def list_simulation_results(
    db: Session,
    *,
    scenario_ref: str | None = None,
    variant_ref: str | None = None,
    latest: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Evidence], int]:
    q = db.query(Evidence).filter_by(kind="evidence.simulation")
    if scenario_ref is not None:
        q = q.filter(Evidence.scenario_ref == scenario_ref)
    if variant_ref is not None:
        q = q.filter(Evidence.variant_ref == variant_ref)
    q = q.order_by(Evidence.run_info["timestamp"].astext.desc().nullslast(), Evidence.id.desc())
    total = q.count()
    if latest:
        rows = q.limit(1).all()
        return rows, min(total, len(rows))
    return q.offset(offset).limit(limit).all(), total


def upsert_simulation_evidence(
    db: Session,
    evidence: SimulationEvidence,
    *,
    yaml_sha256: str | None = None,
) -> Evidence:
    row = db.query(Evidence).filter_by(id=evidence.id).one_or_none() or Evidence(id=evidence.id)
    row.schema_version = evidence.schema_version
    row.kind = evidence.kind
    row.scenario_ref = str(evidence.scenario_ref)
    row.variant_ref = evidence.variant_ref
    row.sw_baseline_ref = str(evidence.execution_context.sw_baseline_ref)
    row.sweep_job_id = evidence.sweep_context.sweep_job_id if evidence.sweep_context else None
    row.execution_context = evidence.execution_context.model_dump(exclude_none=True)
    row.sweep_context = evidence.sweep_context.model_dump(exclude_none=True) if evidence.sweep_context else None
    row.resolution_result = evidence.resolution_result.model_dump(exclude_none=True) if evidence.resolution_result else None
    row.overall_feasibility = (
        str(evidence.resolution_result.overall_feasibility)
        if evidence.resolution_result else None
    )
    row.aggregation = evidence.aggregation.model_dump(exclude_none=True)
    row.kpi = dict(evidence.kpi)
    row.run_info = evidence.run.model_dump(exclude_none=True)
    row.ip_breakdown = [item.model_dump(exclude_none=True) for item in evidence.ip_breakdown]
    row.dma_breakdown = [item.model_dump(exclude_none=True) for item in evidence.dma_breakdown]
    row.timing_breakdown = [item.model_dump(exclude_none=True) for item in evidence.timing_breakdown]
    row.dvfs_breakdown = [item.model_dump(exclude_none=True) for item in evidence.dvfs_breakdown]
    row.timeline_events = [item.model_dump(exclude_none=True) for item in evidence.timeline_events]
    row.external_devices = list(evidence.external_devices or [])
    row.topology_order = list(evidence.topology_order or [])
    row.vdd_power = evidence.vdd_power or {}
    row.calculation_trace = evidence.calculation_trace
    row.params_hash = evidence.params_hash
    row.artifacts = [item.model_dump(exclude_none=True) for item in evidence.artifacts]
    row.yaml_sha256 = yaml_sha256 or _evidence_sha256(evidence)
    db.add(row)
    return row


def _evidence_sha256(evidence: SimulationEvidence) -> str:
    import hashlib

    return hashlib.sha256(
        evidence.model_dump_json(exclude_none=True).encode("utf-8")
    ).hexdigest()
