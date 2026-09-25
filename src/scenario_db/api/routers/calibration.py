from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.services import calibration as cal
from scenario_db.api.services import library as lib

router = APIRouter(tags=["calibration · library"])


@router.get("/calibration/measurements")
def measurements(scenario_id: str | None = None, db: Session = Depends(get_db)):
    """Measurement evidence with total-power error vs. current prediction and simulation evidence."""
    return cal.list_measurements(db, scenario_id=scenario_id)


@router.get("/calibration/coverage")
def coverage(scenario_id: str, db: Session = Depends(get_db)):
    """Per-variant evidence coverage: simulation / real + synthetic measurement counts and current prediction."""
    return cal.coverage(db, scenario_id)


@router.get("/calibration/measurements/{measurement_id}")
def measurement(measurement_id: str, db: Session = Depends(get_db)):
    """Measured rails grouped as CPU / IP / BW / other and compared with each prediction."""
    return cal.measurement_detail(db, measurement_id)


@router.get("/library/sw-timing")
def sw_timing(scenario_id: str | None = None, db: Session = Depends(get_db)):
    """SW task timing assumptions per scenario (range across variants) and measured task timing."""
    return lib.sw_timing(db, scenario_id=scenario_id)
