from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.pagination import apply_sort, validate_sort_column
from scenario_db.api.schemas.common import PagedResponse
from scenario_db.api.schemas.evidence import EvidenceResponse
from scenario_db.comparison.evidence import compare_prediction_measurement
from scenario_db.db.models.evidence import Evidence

router = APIRouter(tags=["evidence"])


@router.get("/evidence/summary", response_model=list[dict])
def evidence_summary(
    groupby: str = Query("sw_version_hint", description="쉼표 구분 컬럼 (sw_version_hint, overall_feasibility)"),
    db: Session = Depends(get_db),
):
    """Evidence 집계 요약. groupby 컬럼별 count."""
    ALLOWED = {"sw_version_hint", "overall_feasibility"}
    cols = [c.strip() for c in groupby.split(",")]
    invalid = set(cols) - ALLOWED
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid groupby columns: {invalid}. Allowed: {ALLOWED}",
        )

    from sqlalchemy import func
    group_cols = [getattr(Evidence, col) for col in cols]
    rows = (
        db.query(*group_cols, func.count().label("count"))
        .group_by(*group_cols)
        .all()
    )
    result = []
    for row in rows:
        d = {col: getattr(row, col) for col in cols}
        d["count"] = row.count
        result.append(d)
    return result


@router.get("/evidence", response_model=PagedResponse[EvidenceResponse])
def list_evidence(
    scenario_ref: str | None = Query(None),
    variant_ref: str | None = Query(None),
    project_ref: str | None = Query(None, description="project_ref 필터"),
    kind: str | None = Query(None, description="evidence.simulation | evidence.measurement"),
    sw_version: str | None = Query(None, description="sw_version_hint 필터"),
    feasibility: str | None = Query(None, description="overall_feasibility 필터"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    """Evidence 목록 조회. 다중 필터 지원."""
    sort_by = validate_sort_column(Evidence, sort_by)
    q = db.query(Evidence)
    if scenario_ref is not None:
        q = q.filter(Evidence.scenario_ref == scenario_ref)
    if variant_ref is not None:
        q = q.filter(Evidence.variant_ref == variant_ref)
    if project_ref is not None:
        q = q.filter(Evidence.project_ref == project_ref)
    if kind is not None:
        q = q.filter(Evidence.kind == kind)
    if sw_version is not None:
        q = q.filter(Evidence.sw_version_hint == sw_version)
    if feasibility is not None:
        q = q.filter(Evidence.overall_feasibility == feasibility)
    q = apply_sort(q, Evidence, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/evidence/{evidence_id}", response_model=EvidenceResponse)
def get_evidence(evidence_id: str, db: Session = Depends(get_db)):
    row = db.query(Evidence).filter_by(id=evidence_id).one_or_none()
    if row is None:
        raise NoResultFound(f"Evidence '{evidence_id}' not found")
    return row


def _pick_latest(q) -> Evidence | None:
    """비교용 evidence 선택 정책: measured_at 최신 우선(NULL은 후순위), 동률이면 id 역순."""
    return q.order_by(
        Evidence.measured_at.desc().nulls_last(),
        Evidence.id.desc(),
    ).first()


@router.get("/compare/evidence", response_model=dict)
def compare_evidence(
    variant: str = Query(..., description="variant_ref"),
    sw1: str = Query(..., description="첫 번째 sw_version_hint"),
    sw2: str = Query(..., description="두 번째 sw_version_hint"),
    scenario_ref: str | None = Query(None, description="scenario_ref 필터 — variant id는 scenario 간 중복 가능하므로 지정 권장"),
    project_ref: str | None = Query(None, description="project_ref 필터"),
    kind: str | None = Query(None, description="evidence.simulation | evidence.measurement"),
    db: Session = Depends(get_db),
):
    """두 SW 버전의 Evidence KPI 비교. 각 SW 버전에서 최신 evidence를 선택한다."""
    def _fetch(sw: str) -> EvidenceResponse | None:
        q = db.query(Evidence).filter_by(variant_ref=variant, sw_version_hint=sw)
        if scenario_ref is not None:
            q = q.filter(Evidence.scenario_ref == scenario_ref)
        if project_ref is not None:
            q = q.filter(Evidence.project_ref == project_ref)
        if kind is not None:
            q = q.filter(Evidence.kind == kind)
        row = _pick_latest(q)
        return EvidenceResponse.model_validate(row) if row else None

    e1 = _fetch(sw1)
    e2 = _fetch(sw2)
    return {
        sw1: e1.model_dump() if e1 else None,
        sw2: e2.model_dump() if e2 else None,
    }


@router.get("/compare/variants", response_model=dict)
def compare_variants(
    ref1: str = Query(..., description="{scenario_id}::{variant_id}"),
    ref2: str = Query(..., description="{scenario_id}::{variant_id}"),
    project_ref: str | None = Query(None, description="project_ref 필터"),
    kind: str | None = Query(None, description="evidence.simulation | evidence.measurement"),
    db: Session = Depends(get_db),
):
    """두 variant의 최신 Evidence KPI 비교. ref의 scenario_id로 필터링한다."""
    def _parse(ref: str):
        if "::" not in ref:
            raise HTTPException(status_code=400, detail=f"ref 형식: {{scenario_id}}::{{variant_id}} — got: {ref!r}")
        sid, vid = ref.split("::", 1)
        return sid, vid

    sid1, vid1 = _parse(ref1)
    sid2, vid2 = _parse(ref2)

    def _fetch(sid: str, vid: str) -> EvidenceResponse | None:
        q = db.query(Evidence).filter_by(scenario_ref=sid, variant_ref=vid)
        if project_ref is not None:
            q = q.filter(Evidence.project_ref == project_ref)
        if kind is not None:
            q = q.filter(Evidence.kind == kind)
        row = _pick_latest(q)
        return EvidenceResponse.model_validate(row) if row else None

    return {
        ref1: _fetch(sid1, vid1),
        ref2: _fetch(sid2, vid2),
    }


@router.get("/compare/prediction-measurement", response_model=dict)
def compare_prediction_measurement_by_id(
    prediction_id: str = Query(...),
    measurement_id: str = Query(...),
    db: Session = Depends(get_db),
):
    prediction = db.query(Evidence).filter_by(id=prediction_id).one_or_none()
    if prediction is None:
        raise HTTPException(status_code=404, detail=f"Prediction evidence '{prediction_id}' not found")
    if prediction.kind != "evidence.simulation":
        raise HTTPException(status_code=400, detail="prediction_id must reference evidence.simulation")

    measurement = db.query(Evidence).filter_by(id=measurement_id).one_or_none()
    if measurement is None:
        raise HTTPException(status_code=404, detail=f"Measurement evidence '{measurement_id}' not found")
    if measurement.kind != "evidence.measurement":
        raise HTTPException(status_code=400, detail="measurement_id must reference evidence.measurement")

    prediction_doc = EvidenceResponse.model_validate(prediction).model_dump()
    measurement_doc = EvidenceResponse.model_validate(measurement).model_dump()
    return compare_prediction_measurement(prediction_doc, measurement_doc)
