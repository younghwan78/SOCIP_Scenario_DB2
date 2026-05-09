from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.models.definition.project import Project as PydanticProject
from scenario_db.models.definition.usecase import Usecase as PydanticUsecase


logger = logging.getLogger(__name__)


class ScenarioProjectCollisionError(ValueError):
    """Raised when a global scenario id would move between projects."""


def upsert_project(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticProject.model_validate(raw)
    row = session.get(Project, obj.id) or Project(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.metadata_ = obj.metadata.model_dump(exclude_none=True)
    row.globals_ = obj.globals.model_dump(exclude_none=True) if obj.globals else None
    row.yaml_sha256 = sha256
    session.add(row)


def upsert_usecase(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticUsecase.model_validate(raw)
    row = session.get(Scenario, obj.id) or Scenario(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    previous_project = getattr(row, "project_ref", None)
    if previous_project and previous_project != str(obj.project_ref):
        policy = _scenario_project_collision_policy(session)
        message = (
            f"scenario id collision: {obj.id} already belongs to project_ref={previous_project}; "
            f"incoming project_ref={obj.project_ref}. Scenario ids are global in the current schema."
        )
        if policy == "replace":
            logger.warning("%s Replacing because collision_policy=replace.", message)
        elif policy == "skip":
            logger.warning("%s Skipping incoming scenario because collision_policy=skip.", message)
            return
        else:
            raise ScenarioProjectCollisionError(
                f"{message} Load into a clean DB, rename one scenario id, or rerun ETL with "
                "scenario_project_collision_policy='replace' only when this replacement is intentional."
            )

    row.schema_version = obj.schema_version
    row.project_ref = str(obj.project_ref)
    row.metadata_ = obj.metadata.model_dump(exclude_none=True)
    row.pipeline = obj.pipeline.model_dump(by_alias=True, exclude_none=True)
    row.size_profile = obj.size_profile.model_dump(exclude_none=True) if obj.size_profile else None
    row.design_axes = [a.model_dump(exclude_none=True) for a in obj.design_axes]
    row.yaml_sha256 = sha256
    session.add(row)
    session.flush()

    # The usecase YAML is the source of truth for variants in that scenario.
    session.query(ScenarioVariant).filter_by(scenario_id=obj.id).delete()
    for v in obj.variants:
        vrow = ScenarioVariant(scenario_id=obj.id, id=v.id)
        vrow.severity = str(v.severity)
        vrow.design_conditions = v.design_conditions or {}
        vrow.design_conditions_override = v.design_conditions_override or {}
        vrow.size_overrides = v.size_overrides or {}
        vrow.routing_switch = v.routing_switch or {}
        vrow.topology_patch = v.topology_patch or {}
        vrow.node_configs = v.node_configs or {}
        vrow.buffer_overrides = v.buffer_overrides or {}
        vrow.ip_requirements = {
            k: vv.model_dump(exclude_none=True)
            for k, vv in v.ip_requirements.items()
        }
        vrow.sw_requirements = v.sw_requirements.model_dump(exclude_none=True) if v.sw_requirements else None
        vrow.violation_policy = v.violation_policy.model_dump(exclude_none=True) if v.violation_policy else None
        vrow.tags = list(v.tags)
        vrow.derived_from_variant = v.derived_from_variant
        session.add(vrow)


def _scenario_project_collision_policy(session: Session) -> str:
    info = getattr(session, "info", {}) or {}
    policy = str(info.get("scenario_project_collision_policy") or "error").lower()
    if policy not in {"error", "replace", "skip"}:
        return "error"
    return policy
