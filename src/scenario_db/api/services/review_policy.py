"""Project review policy (``project.globals.review_policy``): throughput judgement, power reference, thermal watch.

Absent policy = previous behaviour everywhere (stage throughput, no reference, no watch list), so projects that do not
declare one (in-house SoCs included) are unaffected.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from scenario_db.db.models.definition import Project, Scenario
from scenario_db.models.definition.project import ReviewPolicy

T = TypeVar("T", bound=BaseModel)


def project_policy(db: Session, project_ref: str | None) -> ReviewPolicy | None:
    if not project_ref:
        return None
    row = db.get(Project, project_ref)
    globals_ = getattr(row, "globals_", None) if row is not None else None
    raw = globals_.get("review_policy") if isinstance(globals_, dict) else None
    return ReviewPolicy.model_validate(raw) if isinstance(raw, dict) and raw else None


def scenario_policy(db: Session, scenario_id: str) -> ReviewPolicy | None:
    project_ref = db.query(Scenario.project_ref).filter(Scenario.id == scenario_id).scalar()
    return project_policy(db, project_ref) if isinstance(project_ref, str) else None


def apply_throughput(options: T, policy: ReviewPolicy | None) -> T:
    """Fill ``throughput_model`` from the project policy unless the request set it explicitly."""
    if policy is None or policy.throughput_model is None or "throughput_model" in options.model_fields_set:
        return options
    return options.model_copy(update={"throughput_model": policy.throughput_model})


def policy_view(policy: ReviewPolicy | None) -> dict[str, Any]:
    if policy is None:
        return {"declared": False, "throughput_model": "stage", "max_latency_frames": None,
                "power_reference": None, "thermal_watch": []}
    return {"declared": True, "throughput_model": policy.throughput_model or "stage", **policy.model_dump(
        mode="json", exclude={"throughput_model"})}
