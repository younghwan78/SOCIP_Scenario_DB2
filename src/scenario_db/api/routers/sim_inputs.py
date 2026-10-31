from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.services import sim_inputs as service

router = APIRouter(tags=["sim inputs"])


@router.get("/scenarios/{scenario_id}/variants/{variant_id}/sim-inputs")
def get_sim_inputs(scenario_id: str, variant_id: str, db: Session = Depends(get_db)):
    """Per-node cadence, execution time and load term the simulation uses (Pipeline 'Sim 입력' lens)."""
    return service.sim_inputs(db, scenario_id, variant_id)
