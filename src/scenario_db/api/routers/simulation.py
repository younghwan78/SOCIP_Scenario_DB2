from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.common import PagedResponse
from scenario_db.api.schemas.evidence import EvidenceResponse
from scenario_db.api.schemas.simulation import SimulateRequest, SimulateRunResponse, SimulationReadinessResponse
from scenario_db.db.repositories.evidence import (
    delete_simulation_evidence,
    get_evidence,
    list_simulation_results,
)
from scenario_db.sim.service import check_simulation_readiness_request, run_simulation_request

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("/run", response_model=SimulateRunResponse)
def run_simulation(request: SimulateRequest, db: Session = Depends(get_db)):
    return run_simulation_request(db, request)


@router.get("/readiness", response_model=SimulationReadinessResponse)
def readiness(
    scenario_id: str = Query(...),
    variant_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return check_simulation_readiness_request(db, scenario_id, variant_id)


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


@router.delete("/results/{evidence_id}", status_code=204)
def delete_result(evidence_id: str, db: Session = Depends(get_db)):
    deleted = delete_simulation_evidence(db, evidence_id)
    if not deleted:
        raise NoResultFound(f"Simulation evidence '{evidence_id}' not found")
    db.commit()
    return Response(status_code=204)
