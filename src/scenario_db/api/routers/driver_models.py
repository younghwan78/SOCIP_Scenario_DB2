from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session
from scenario_db.api.deps import get_db
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.models.common import BaseScenarioModel
from scenario_db.sim.driver_models import DriverInput, evaluate_graph

router = APIRouter(prefix="/driver-models", tags=["driver models"])


class Request(BaseScenarioModel):
    scenario_id: str
    variant_id: str
    overrides: dict[str, DriverInput] = Field(default_factory=dict, max_length=100)


def report(db, scenario_id, variant_id, overrides):
    try:
        graph = load_canonical_graph(db, scenario_id, variant_id)
        return evaluate_graph(graph, overrides)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
def get_report(scenario_id: str, variant_id: str, db: Session = Depends(get_db)):
    return report(db, scenario_id, variant_id, {})


@router.post("/explore")
def explore(request: Request, db: Session = Depends(get_db)):
    # Read-only calculation. No fixture, DB or legacy power total mutation.
    return report(db, request.scenario_id, request.variant_id, request.overrides)
