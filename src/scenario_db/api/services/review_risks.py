"""Project risk register (RPT-04): automatic rules from report snapshots + people's owner / status / note."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from scenario_db.db.models.definition import Project
from scenario_db.db.models.exploration import RISK_STATUSES, ReviewRisk
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.reporting.risk_rules import SEVERITY_ORDER

_AUTO_FIELDS = ("rule", "severity", "category", "title", "detail", "affected", "mitigation", "validity", "checks")


def _now() -> datetime:
    return datetime.now(UTC)


def risk_view(r: ReviewRisk, *, trend: str | None = None) -> dict[str, Any]:
    return {"id": r.id, "label": f"R-{r.seq:02d}", "seq": r.seq, "project_ref": r.project_ref, "key": r.risk_key,
            "rule": r.rule, "severity": r.severity, "category": r.category, "title": r.title, "detail": r.detail,
            "affected": list(r.affected or []), "mitigation": r.mitigation,
            "validity": getattr(r, "validity", None) or "confirmed", "checks": list(getattr(r, "checks", None) or []), "owner": r.owner, "status": r.status,
            "note": r.note, "auto_state": r.auto_state, "trend": trend,
            "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None, "updated_by": r.updated_by,
            "last_report_ref": r.last_report_ref, "history": list(r.history or [])[-20:]}


def _order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closed = ("closed", "accepted")
    return sorted(rows, key=lambda r: (r["status"] in closed, r["auto_state"] == "resolve_candidate",
                                       SEVERITY_ORDER.get(r["severity"], 9), r["seq"]))


def list_risks(db: Session, project_ref: str) -> list[dict[str, Any]]:
    rows = db.query(ReviewRisk).filter(ReviewRisk.project_ref == project_ref).all()
    return _order([risk_view(r) for r in rows])


def sync_risks(db: Session, project_ref: str, risks: list[dict[str, Any]], *, report_ref: str | None,
               user: str | None) -> list[dict[str, Any]]:
    """Apply one report's automatic risks to the register and return it with each row's trend.

    trend: ``new`` (first seen now) · ``ongoing`` · ``reopened`` (fired again after resolve candidate / close)
    · ``resolve_candidate`` (rule no longer fires; a person closes it) · ``manual`` rows are left alone.
    """
    # The project row also serializes the first sync, when there are no risk rows to lock yet.
    if db.query(Project).filter(Project.id == project_ref).with_for_update().one_or_none() is None:
        raise NotFoundError(f"project not found: {project_ref}")
    now = _now()
    existing = {r.risk_key: r for r in db.query(ReviewRisk).populate_existing().filter(ReviewRisk.project_ref == project_ref)
                .with_for_update().all()}
    seq = max((r.seq for r in existing.values()), default=0)
    trends: dict[str, str] = {}
    fired = set()
    for risk in risks:
        key = risk["key"]
        fired.add(key)
        row = existing.get(key)
        if row is None:
            seq += 1
            row = ReviewRisk(id=f"RISK-{project_ref}-{seq:03d}", project_ref=project_ref, seq=seq, risk_key=key,
                             status="open", auto_state="active", first_seen_at=now, last_seen_at=now, updated_at=now,
                             updated_by=user, last_report_ref=report_ref,
                             history=[{"at": now.isoformat(), "by": user, "field": "auto", "old": None, "new": "opened"}],
                             **{f: (risk.get(f) if f != "checks" else list(risk.get(f) or [])) for f in _AUTO_FIELDS})
            db.add(row)
            existing[key] = row
            trends[key] = "new"
            continue
        reopened = row.auto_state == "resolve_candidate" or row.status == "closed"
        hist = list(row.history or [])
        if reopened:
            hist.append({"at": now.isoformat(), "by": user, "field": "auto", "old": row.auto_state if row.status != "closed" else "closed",
                         "new": "reopened"})
            if row.status == "closed":
                row.status = "open"
        if row.severity != risk["severity"]:
            hist.append({"at": now.isoformat(), "by": user, "field": "severity", "old": row.severity, "new": risk["severity"]})
        for f in _AUTO_FIELDS:
            setattr(row, f, risk.get(f) if f != "checks" else list(risk.get(f) or []))
        row.auto_state = "active" if row.auto_state != "manual" else "manual"
        row.last_seen_at = now
        row.updated_at = now
        row.updated_by = user
        row.last_report_ref = report_ref
        row.history = hist[-50:]
        trends[key] = "reopened" if reopened else "ongoing"
    for key, row in existing.items():
        if key in fired or row.auto_state == "manual" or row.status == "closed":
            continue
        if row.auto_state != "resolve_candidate":
            row.auto_state = "resolve_candidate"
            row.history = [*(row.history or []), {"at": now.isoformat(), "by": user, "field": "auto", "old": "active",
                                                  "new": "resolve_candidate"}][-50:]
            row.updated_at = now
        trends[key] = "resolve_candidate"
    db.flush()
    return _order([risk_view(r, trend=trends.get(r.risk_key)) for r in existing.values()])


def update_risk(db: Session, risk_id: str, *, owner: str | None = None, status: str | None = None,
                note: str | None = None, user: str | None = None) -> dict[str, Any]:
    row = db.query(ReviewRisk).filter_by(id=risk_id).populate_existing().with_for_update().one_or_none()
    if row is None:
        raise NotFoundError(f"risk not found: {risk_id}")
    if status is not None and status not in RISK_STATUSES:
        raise UnprocessableError(f"invalid risk status: {status}")
    now = _now()
    hist = list(row.history or [])
    for field, value in (("owner", owner), ("status", status), ("note", note)):
        if value is None:
            continue
        value = (value.strip() or None) if field != "status" else value
        if getattr(row, field) != value:
            hist.append({"at": now.isoformat(), "by": user, "field": field, "old": getattr(row, field), "new": value})
            setattr(row, field, value)
    row.history = hist[-50:]
    row.updated_at = now
    row.updated_by = user
    db.commit()
    return risk_view(row)


def register_counts(db: Session, project_refs: list[str]) -> dict[str, dict[str, int]]:
    """Open risks per severity for each project (Portfolio)."""
    q = (db.query(ReviewRisk.project_ref, ReviewRisk.severity, func.count())
         .filter(ReviewRisk.project_ref.in_(project_refs), ReviewRisk.status.notin_(("closed", "accepted")),
                 ReviewRisk.auto_state != "resolve_candidate")
         .group_by(ReviewRisk.project_ref, ReviewRisk.severity)) if project_refs else []
    out: dict[str, dict[str, int]] = {p: {k: 0 for k in SEVERITY_ORDER} for p in project_refs}
    for pref, sev, n in q:
        out[pref][sev] = int(n)
    return out
