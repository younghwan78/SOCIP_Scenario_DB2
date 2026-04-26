"""FastAPI view router ??GET /api/v1/scenarios/{sid}/variants/{vid}/view."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.view import ViewResponse
from scenario_db.view.service import project_level0, project_level1, project_level2

router = APIRouter(tags=["view"])


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
    try:
        if level == 0:
            return project_level0(scenario_id, variant_id, db=db, mode=mode)
        if level == 1:
            return project_level1(scenario_id, variant_id, db=db)
        if level == 2:
            if not expand:
                raise HTTPException(status_code=422, detail="expand= required for level=2")
            return project_level2(scenario_id, variant_id, expand=expand, db=db)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    raise HTTPException(status_code=400, detail=f"Unsupported level: {level}")

