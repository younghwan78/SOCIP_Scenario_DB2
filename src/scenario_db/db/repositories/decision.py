"""Decision 도메인 — Issue, GateRule, Waiver, Review."""
from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from scenario_db.api.pagination import apply_sort
from scenario_db.db.models.decision import GateRule, Issue, Review, Waiver


def list_issues(
    db: Session,
    *,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[Issue], int]:
    q = apply_sort(db.query(Issue), Issue, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_issue(db: Session, issue_id: str) -> Issue | None:
    return db.query(Issue).filter_by(id=issue_id).one_or_none()


def list_gate_rules(
    db: Session,
    *,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[GateRule], int]:
    q = apply_sort(db.query(GateRule), GateRule, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def list_waivers(
    db: Session,
    *,
    expiring_within_days: int | None = None,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[Waiver], int]:
    q = db.query(Waiver)
    if expiring_within_days is not None:
        cutoff = datetime.date.today() + datetime.timedelta(days=expiring_within_days)
        q = q.filter(Waiver.expires_on <= cutoff, Waiver.expires_on >= datetime.date.today())
    q = apply_sort(q, Waiver, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_waiver(db: Session, waiver_id: str) -> Waiver | None:
    return db.query(Waiver).filter_by(id=waiver_id).one_or_none()


def list_reviews(
    db: Session,
    *,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[Review], int]:
    q = apply_sort(db.query(Review), Review, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_review(db: Session, review_id: str) -> Review | None:
    return db.query(Review).filter_by(id=review_id).one_or_none()
