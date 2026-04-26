"""Evidence 도메인 — Evidence, SweepJob."""
from __future__ import annotations

from sqlalchemy.orm import Session

from scenario_db.api.pagination import apply_sort
from scenario_db.db.models.evidence import Evidence


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
