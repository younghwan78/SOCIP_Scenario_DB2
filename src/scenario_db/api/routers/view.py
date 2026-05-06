"""FastAPI view router ??GET /api/v1/scenarios/{sid}/variants/{vid}/view."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.view import ViewResponse
from scenario_db.db.repositories.evidence import get_evidence, list_simulation_results
from scenario_db.view.service import apply_simulation_overlay, project_level0, project_level1, project_level2

router = APIRouter(tags=["view"])


@router.get(
    "/scenarios/{scenario_id}/view",
    response_model=ViewResponse,
    summary="Base scenario pipeline view data (no variant overlay)",
)
def get_base_view(
    scenario_id: str,
    level: int = Query(0, ge=0, le=2, description="View depth: 0=overview/topology, 1=IP DAG, 2=drill-down"),
    mode: str = Query("architecture", description="architecture | topology"),
    expand: str | None = Query(None, description="IP id to expand (Level 2 only)"),
    sim: str = Query("none", description="none | latest"),
    sim_evidence_id: str | None = Query(None, description="Specific simulation evidence id to overlay"),
    db: Session = Depends(get_db),
):
    return _build_view(
        scenario_id,
        None,
        level=level,
        mode=mode,
        expand=expand,
        sim=sim,
        sim_evidence_id=sim_evidence_id,
        db=db,
    )


@router.get(
    "/scenarios/{scenario_id}/variants/{variant_id}/view",
    response_model=ViewResponse,
    summary="Pipeline view data (Level 0/1/2)",
)
def get_view(
    scenario_id: str,
    variant_id: str,
    level: int = Query(0, ge=0, le=2, description="View depth: 0=overview/topology, 1=IP DAG, 2=drill-down"),
    mode: str = Query("architecture", description="architecture | topology"),
    expand: str | None = Query(None, description="IP id to expand (Level 2 only)"),
    sim: str = Query("none", description="none | latest"),
    sim_evidence_id: str | None = Query(None, description="Specific simulation evidence id to overlay"),
    db: Session = Depends(get_db),
):
    """Return viewer projection data for the ELK/SVG pipeline viewer.

    Level 0:
      - mode=architecture: App/Framework/HAL/Kernel/HW/Memory overview.
      - mode=topology: SW task topology DAG.
    Level 1:
      - Grouped IP detail DAG.
    Level 2:
      - Drill-down view. Requires expand=camera|video|display or an IP/node id.
    """
    return _build_view(
        scenario_id,
        variant_id,
        level=level,
        mode=mode,
        expand=expand,
        sim=sim,
        sim_evidence_id=sim_evidence_id,
        db=db,
    )


def _build_view(
    scenario_id: str,
    variant_id: str | None,
    *,
    level: int,
    mode: str,
    expand: str | None,
    sim: str,
    sim_evidence_id: str | None,
    db: Session,
) -> ViewResponse:
    try:
        if level == 0:
            view = project_level0(scenario_id, variant_id, db=db, mode=mode)
        if level == 1:
            view = project_level1(scenario_id, variant_id, db=db)
        if level == 2:
            if not expand:
                raise HTTPException(status_code=422, detail="expand= required for level=2")
            view = project_level2(scenario_id, variant_id, expand=expand, db=db)
        return _apply_optional_sim_overlay(
            view,
            db=db,
            scenario_id=scenario_id,
            variant_id=variant_id,
            sim=sim,
            sim_evidence_id=sim_evidence_id,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail=f"Unsupported level: {level}")


def _apply_optional_sim_overlay(
    view: ViewResponse,
    *,
    db: Session,
    scenario_id: str,
    variant_id: str | None,
    sim: str,
    sim_evidence_id: str | None,
) -> ViewResponse:
    if sim not in {"none", "latest"}:
        raise HTTPException(status_code=400, detail="sim must be 'none' or 'latest'")
    evidence = None
    if sim_evidence_id:
        evidence = get_evidence(db, sim_evidence_id)
        if evidence is None or evidence.kind != "evidence.simulation":
            raise HTTPException(status_code=404, detail=f"Simulation evidence not found: {sim_evidence_id}")
    elif sim == "latest" and variant_id:
        rows, _ = list_simulation_results(
            db,
            scenario_ref=scenario_id,
            variant_ref=variant_id,
            latest=True,
            limit=1,
            offset=0,
        )
        evidence = rows[0] if rows else None
    return apply_simulation_overlay(view, evidence)

