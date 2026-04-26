from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.cache import RuleCache
from scenario_db.api.deps import get_db, get_rule_cache
from scenario_db.api.pagination import apply_sort, validate_sort_column
from scenario_db.api.schemas.common import PagedResponse
from scenario_db.api.schemas.decision import (
    GateRuleResponse,
    IssueResponse,
    ReviewResponse,
    WaiverResponse,
)
from scenario_db.db.models.decision import GateRule, Issue, Review, Waiver

router = APIRouter(tags=["decision"])


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@router.get("/reviews", response_model=PagedResponse[ReviewResponse])
def list_reviews(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    sort_by = validate_sort_column(Review, sort_by)
    q = apply_sort(db.query(Review), Review, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/reviews/{review_id}", response_model=ReviewResponse)
def get_review(review_id: str, db: Session = Depends(get_db)):
    row = db.query(Review).filter_by(id=review_id).one_or_none()
    if row is None:
        raise NoResultFound(f"Review '{review_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Issues — RuleCache 우선 서빙 (캐시 경로에서는 sort 미적용)
# ---------------------------------------------------------------------------

@router.get("/issues", response_model=PagedResponse[IssueResponse])
def list_issues(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    cache: RuleCache = Depends(get_rule_cache),
    db: Session = Depends(get_db),
):
    """Issue 목록. 캐시 적재 성공 시 캐시 우선(sort 미지원), 실패 시 DB fallback."""
    if cache.loaded:
        items = cache.issues[offset: offset + limit]
        return PagedResponse(
            items=items,
            total=len(cache.issues),
            limit=limit,
            offset=offset,
            has_next=(offset + limit) < len(cache.issues),
        )
    sort_by = validate_sort_column(Issue, sort_by)
    q = apply_sort(db.query(Issue), Issue, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/issues/{issue_id}", response_model=IssueResponse)
def get_issue(
    issue_id: str,
    cache: RuleCache = Depends(get_rule_cache),
    db: Session = Depends(get_db),
):
    if cache.loaded:
        for iss in cache.issues:
            if iss.id == issue_id:
                return iss
        raise NoResultFound(f"Issue '{issue_id}' not found")
    row = db.query(Issue).filter_by(id=issue_id).one_or_none()
    if row is None:
        raise NoResultFound(f"Issue '{issue_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------

@router.get("/waivers", response_model=PagedResponse[WaiverResponse])
def list_waivers(
    expiring_within_days: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    sort_by = validate_sort_column(Waiver, sort_by)
    q = db.query(Waiver)
    if expiring_within_days is not None:
        cutoff = datetime.date.today() + datetime.timedelta(days=expiring_within_days)
        q = q.filter(Waiver.expires_on <= cutoff, Waiver.expires_on >= datetime.date.today())
    q = apply_sort(q, Waiver, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/waivers/{waiver_id}", response_model=WaiverResponse)
def get_waiver(waiver_id: str, db: Session = Depends(get_db)):
    row = db.query(Waiver).filter_by(id=waiver_id).one_or_none()
    if row is None:
        raise NoResultFound(f"Waiver '{waiver_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Gate Rules — RuleCache 우선 서빙 (캐시 경로에서는 sort 미적용)
# ---------------------------------------------------------------------------

@router.get("/gate-rules", response_model=PagedResponse[GateRuleResponse])
def list_gate_rules(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    cache: RuleCache = Depends(get_rule_cache),
    db: Session = Depends(get_db),
):
    if cache.loaded:
        items = cache.gate_rules[offset: offset + limit]
        return PagedResponse(
            items=items,
            total=len(cache.gate_rules),
            limit=limit,
            offset=offset,
            has_next=(offset + limit) < len(cache.gate_rules),
        )
    sort_by = validate_sort_column(GateRule, sort_by)
    q = apply_sort(db.query(GateRule), GateRule, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)
