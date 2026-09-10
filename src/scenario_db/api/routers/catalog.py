"""Small, paged catalog records for navigation; full resource APIs stay intact."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Text, case, cast, func, or_
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.common import PagedResponse
from scenario_db.db.models.capability import SocPlatform
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant

router = APIRouter(tags=["catalog"])
CatalogKind = Literal["soc-platforms", "projects", "scenarios", "variants"]


class CatalogItem(BaseModel):
    id: str
    name: str
    project_ref: str | None = None
    soc_ref: str | None = None
    board_type: str | None = None
    scenario_id: str | None = None
    category: list[str] = Field(default_factory=list)


def _name(metadata, fallback):
    value = metadata["name"]
    return func.coalesce(case((func.jsonb_typeof(value) == "string", func.nullif(value.astext, ""))), fallback)


@router.get("/catalog/{kind}", response_model=PagedResponse[CatalogItem])
def list_catalog(
    kind: CatalogKind,
    q: str = Query("", max_length=200),
    id: str | None = Query(None, description="Exact ID lookup within the same scope"),
    soc_ref: str | None = Query(None),
    project_ref: str | None = Query(None),
    board_type: str | None = Query(None),
    scenario_id: str | None = Query(None),
    sort_by: Literal["id", "name", "category"] = "id",
    sort_dir: Literal["asc", "desc"] = "asc",
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    category = None
    if kind == "soc-platforms":
        identity, name = SocPlatform.id, SocPlatform.id
        query = db.query(identity.label("id"), name.label("name"))
    elif kind == "projects":
        identity, name = Project.id, _name(Project.metadata_, Project.id)
        query = db.query(identity.label("id"), name.label("name"),
                         Project.metadata_["soc_ref"].astext.label("soc_ref"),
                         Project.metadata_["board_type"].astext.label("board_type"))
        if project_ref is not None:
            query = query.filter(Project.id == project_ref)
    elif kind == "scenarios":
        identity, name = Scenario.id, _name(Scenario.metadata_, Scenario.id)
        category = Scenario.metadata_["category"]
        query = db.query(identity.label("id"), name.label("name"),
                         Scenario.project_ref.label("project_ref"),
                         Project.metadata_["soc_ref"].astext.label("soc_ref"),
                         category.label("category")).join(Project, Scenario.project_ref == Project.id)
        if project_ref is not None:
            query = query.filter(Scenario.project_ref == project_ref)
    else:
        if scenario_id is None:
            raise HTTPException(422, "scenario_id is required for the variant catalog")
        identity, name = ScenarioVariant.id, ScenarioVariant.id
        query = db.query(identity.label("id"), name.label("name"),
                         ScenarioVariant.scenario_id.label("scenario_id")).join(
            Scenario, ScenarioVariant.scenario_id == Scenario.id
        ).join(Project, Scenario.project_ref == Project.id).filter(ScenarioVariant.scenario_id == scenario_id)
        if project_ref is not None:
            query = query.filter(Scenario.project_ref == project_ref)
    if kind != "soc-platforms":
        if soc_ref is not None:
            query = query.filter(Project.metadata_["soc_ref"].astext == soc_ref)
        if board_type is not None:
            query = query.filter(Project.metadata_["board_type"].astext == board_type)
    if id is not None:
        query = query.filter(identity == id)
    if q:
        conditions = [identity.icontains(q, autoescape=True), name.icontains(q, autoescape=True)]
        if category is not None:
            conditions.append(cast(category, Text).icontains(q, autoescape=True))
        query = query.filter(or_(*conditions))
    if sort_by == "category" and category is None:
        raise HTTPException(422, "category sorting is only supported for scenarios")
    column = name if sort_by == "name" else cast(category, Text) if sort_by == "category" else identity
    total = query.count()
    order = column.desc() if sort_dir == "desc" else column.asc()
    rows = query.order_by(order, identity.asc()).offset(offset).limit(limit).all()
    items = []
    for row in rows:
        data = dict(row._mapping)
        data["name"] = data.get("name") or data["id"]
        categories = data.get("category")
        data["category"] = [str(value) for value in categories] if isinstance(categories, list) else [str(categories)] if categories else []
        items.append(CatalogItem(**data))
    return PagedResponse.from_items(items, total=total, limit=limit, offset=offset)
