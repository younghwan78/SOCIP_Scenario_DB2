from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.common import PagedResponse
from scenario_db.api.schemas.evidence import EvidenceResponse
from scenario_db.api.schemas.simulation import SimulateRequest, SimulateRunResponse
from scenario_db.db.repositories.evidence import (
    get_evidence,
    list_simulation_results,
)
from scenario_db.sim.service import run_simulation_request

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("/run", response_model=SimulateRunResponse)
def run_simulation(request: SimulateRequest, db: Session = Depends(get_db)):
    return run_simulation_request(db, request)


@router.get("/results", response_model=PagedResponse[EvidenceResponse])
def list_results(
    scenario_ref: str | None = Query(None),
    variant_ref: str | None = Query(None),
    latest: bool = Query(False),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows, total = list_simulation_results(
        db,
        scenario_ref=scenario_ref,
        variant_ref=variant_ref,
        latest=latest,
        limit=limit,
        offset=offset,
    )
    return PagedResponse.from_items(rows, total=total, limit=limit, offset=offset)


@router.get("/results/{evidence_id}", response_model=EvidenceResponse)
def get_result(evidence_id: str, db: Session = Depends(get_db)):
    row = get_evidence(db, evidence_id)
    if row is None or row.kind != "evidence.simulation":
        raise NoResultFound(f"Simulation evidence '{evidence_id}' not found")
    return row
