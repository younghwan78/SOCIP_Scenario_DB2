from __future__ import annotations

from sqlalchemy.orm import Session

from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.models.definition.project import Project as PydanticProject
from scenario_db.models.definition.usecase import Usecase as PydanticUsecase


def upsert_project(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticProject.model_validate(raw)
    row = session.get(Project, obj.id) or Project(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.metadata_      = obj.metadata.model_dump(exclude_none=True)
    row.globals_       = obj.globals.model_dump(exclude_none=True) if obj.globals else None
    row.yaml_sha256    = sha256
    session.add(row)


def upsert_usecase(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticUsecase.model_validate(raw)
    row = session.get(Scenario, obj.id) or Scenario(id=obj.id)
    if row.yaml_sha256 == sha256:
        return

    row.schema_version = obj.schema_version
    row.project_ref    = str(obj.project_ref)
    row.metadata_      = obj.metadata.model_dump(exclude_none=True)
    # by_alias=True 필수 — PipelineEdge.from_ → "from"으로 직렬화
    row.pipeline       = obj.pipeline.model_dump(by_alias=True, exclude_none=True)
    row.size_profile   = obj.size_profile.model_dump(exclude_none=True) if obj.size_profile else None
    row.design_axes    = [a.model_dump(exclude_none=True) for a in obj.design_axes]
    row.yaml_sha256    = sha256
    session.add(row)
    session.flush()  # scenario row 확정 후 variants 삽입

    # variants — usecase YAML 전체가 source of truth → 전량 재삽입
    session.query(ScenarioVariant).filter_by(scenario_id=obj.id).delete()
    for v in obj.variants:
        vrow = ScenarioVariant(scenario_id=obj.id, id=v.id)
        vrow.severity            = str(v.severity)
        vrow.design_conditions   = v.design_conditions or {}
        vrow.design_conditions_override = v.design_conditions_override or {}
        vrow.size_overrides      = v.size_overrides or {}
        vrow.routing_switch      = v.routing_switch or {}
        vrow.topology_patch      = v.topology_patch or {}
        vrow.node_configs        = v.node_configs or {}
        vrow.buffer_overrides    = v.buffer_overrides or {}
        vrow.ip_requirements     = {
            k: vv.model_dump(exclude_none=True)
            for k, vv in v.ip_requirements.items()
        }
        vrow.sw_requirements     = v.sw_requirements.model_dump(exclude_none=True) if v.sw_requirements else None
        vrow.violation_policy    = v.violation_policy.model_dump(exclude_none=True) if v.violation_policy else None
        vrow.tags                = list(v.tags)
        vrow.derived_from_variant = v.derived_from_variant
        session.add(vrow)
