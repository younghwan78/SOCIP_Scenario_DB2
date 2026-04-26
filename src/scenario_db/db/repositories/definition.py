"""Definition 도메인 — Project, Scenario, ScenarioVariant."""
from __future__ import annotations

from sqlalchemy.orm import Session

from scenario_db.api.pagination import apply_sort
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant


def list_projects(
    db: Session,
    *,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[Project], int]:
    q = apply_sort(db.query(Project), Project, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_project(db: Session, project_id: str) -> Project | None:
    return db.query(Project).filter_by(id=project_id).one_or_none()


def list_scenarios(
    db: Session,
    *,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[Scenario], int]:
    q = apply_sort(db.query(Scenario), Scenario, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_scenario(db: Session, scenario_id: str) -> Scenario | None:
    return db.query(Scenario).filter_by(id=scenario_id).one_or_none()


def list_variants_for_scenario(
    db: Session,
    scenario_id: str,
    *,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[ScenarioVariant], int]:
    q = db.query(ScenarioVariant).filter_by(scenario_id=scenario_id)
    q = apply_sort(q, ScenarioVariant, sort_by, sort_dir)
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def get_variant(db: Session, scenario_id: str, variant_id: str) -> ScenarioVariant | None:
    return (
        db.query(ScenarioVariant)
        .filter_by(scenario_id=scenario_id, id=variant_id)
        .one_or_none()
    )


def list_all_variants(
    db: Session,
    *,
    project: str | None = None,
    severity: str | None = None,
    tag: str | None = None,
    limit: int,
    offset: int,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> tuple[list[ScenarioVariant], int]:
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
    return q.offset(offset).limit(limit).all(), total
