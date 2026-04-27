from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.cache import RuleCache, match_issues_for_variant
from scenario_db.api.deps import get_db, get_rule_cache
from scenario_db.api.pagination import apply_sort, validate_sort_column
from scenario_db.api.schemas.common import PagedResponse
from scenario_db.api.schemas.decision import IssueResponse
from scenario_db.api.schemas.definition import (
    ProjectResponse,
    ScenarioResponse,
    ScenarioVariantResponse,
)
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.repositories.variant_resolution import resolve_variant, resolve_variant_from_rows
from scenario_db.matcher.context import MatcherContext

router = APIRouter(tags=["definition"])


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@router.get("/projects", response_model=PagedResponse[ProjectResponse])
def list_projects(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    sort_by = validate_sort_column(Project, sort_by)
    q = apply_sort(db.query(Project), Project, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db)):
    row = db.query(Project).filter_by(id=project_id).one_or_none()
    if row is None:
        raise NoResultFound(f"Project '{project_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@router.get("/scenarios", response_model=PagedResponse[ScenarioResponse])
def list_scenarios(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    sort_by = validate_sort_column(Scenario, sort_by)
    q = apply_sort(db.query(Scenario), Scenario, sort_by, sort_dir)
    return PagedResponse.from_query(q, limit=limit, offset=offset)


@router.get("/scenarios/{scenario_id}", response_model=ScenarioResponse)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)):
    row = db.query(Scenario).filter_by(id=scenario_id).one_or_none()
    if row is None:
        raise NoResultFound(f"Scenario '{scenario_id}' not found")
    return row


@router.get("/scenarios/{scenario_id}/variants", response_model=PagedResponse[ScenarioVariantResponse])
def list_variants_for_scenario(
    scenario_id: str,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    scenario = db.query(Scenario).filter_by(id=scenario_id).one_or_none()
    if scenario is None:
        raise NoResultFound(f"Scenario '{scenario_id}' not found")
    sort_by = validate_sort_column(ScenarioVariant, sort_by)
    q = db.query(ScenarioVariant).filter_by(scenario_id=scenario_id)
    q = apply_sort(q, ScenarioVariant, sort_by, sort_dir)
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    row_map = {
        row.id: row
        for row in db.query(ScenarioVariant).filter_by(scenario_id=scenario_id).all()
    }
    items = [resolve_variant_from_rows(row_map, scenario_id, row.id) for row in rows]
    return PagedResponse.from_items(items, total=total, limit=limit, offset=offset)


@router.get(
    "/scenarios/{scenario_id}/variants/{variant_id}",
    response_model=ScenarioVariantResponse,
)
def get_variant(scenario_id: str, variant_id: str, db: Session = Depends(get_db)):
    row = resolve_variant(db, scenario_id, variant_id)
    if row is None:
        raise NoResultFound(f"Variant '{scenario_id}/{variant_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Matched Issues — P1 핵심 엔드포인트
# ---------------------------------------------------------------------------

@router.get("/scenarios/{scenario_id}/variants/{variant_id}/matched-issues")
def matched_issues(
    scenario_id: str,
    variant_id: str,
    db: Session = Depends(get_db),
    cache: RuleCache = Depends(get_rule_cache),
):
    """
    Issue.affects 룰을 variant context에 대해 평가하여 해당 variant에 영향을 미치는 Issue 목록 반환.
    eval_time_ms: 룰 평가 순수 소요 시간 (ms).
    """
    variant = resolve_variant(db, scenario_id, variant_id)
    if variant is None:
        raise NoResultFound(f"Variant '{scenario_id}/{variant_id}' not found")

    ctx = MatcherContext.from_variant(variant)

    t0 = time.perf_counter()
    matched: list[IssueResponse] = match_issues_for_variant(ctx, cache.issues, scenario_id=scenario_id)
    eval_ms = (time.perf_counter() - t0) * 1000

    return {
        "matched": [m.model_dump() for m in matched],
        "total": len(matched),
        "eval_time_ms": round(eval_ms, 3),
    }


# ---------------------------------------------------------------------------
# Global Variant List (cross-scenario) — P2
# ---------------------------------------------------------------------------

@router.get("/variants", response_model=PagedResponse[ScenarioVariantResponse])
def list_all_variants(
    project: str | None = Query(None, description="project_ref 필터 (scenario 경유)"),
    severity: str | None = Query(None),
    tag: str | None = Query(None, description="tags 배열에 포함된 값 필터"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    sort_by: str | None = Query(None),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    """전체 variant 목록 (cross-scenario). ?project=, ?severity=, ?tag= 필터 지원."""
    sort_by = validate_sort_column(ScenarioVariant, sort_by)
    q = db.query(ScenarioVariant)
    if severity is not None:
        q = q.filter(ScenarioVariant.severity == severity)
    if tag is not None:
        q = q.filter(ScenarioVariant.tags.contains([tag]))
    if project is not None:
        q = q.join(Scenario, ScenarioVariant.scenario_id == Scenario.id).filter(
            Scenario.project_ref == project
        )
    q = apply_sort(q, ScenarioVariant, sort_by, sort_dir)
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    scenario_ids = {row.scenario_id for row in rows}
    resolved_items = []
    for sid in scenario_ids:
        row_map = {
            row.id: row
            for row in db.query(ScenarioVariant).filter_by(scenario_id=sid).all()
        }
        for row in rows:
            if row.scenario_id == sid:
                resolved_items.append(resolve_variant_from_rows(row_map, sid, row.id))
    # Preserve query order after resolving by scenario group.
    by_key = {(item.scenario_id, item.id): item for item in resolved_items}
    items = [by_key[(row.scenario_id, row.id)] for row in rows]
    return PagedResponse.from_items(items, total=total, limit=limit, offset=offset)
