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


@router.get("/calibration/coverage-summary")
def coverage_summary(db: Session = Depends(get_db)):
    """Per-scenario count of variants with simulation / real / synthetic measurement / current prediction (Home)."""
    return cal.coverage_summary(db)


@router.get("/calibration/coverage")
def coverage(scenario_id: str, db: Session = Depends(get_db)):
    """Per-variant evidence coverage: simulation / real + synthetic measurement counts and current prediction."""
    return cal.coverage(db, scenario_id)


@router.get("/calibration/ip-bandwidth")
def ip_bandwidth(scenario_id: str, variant_id: str, measurement_id: str | None = None, db: Session = Depends(get_db)):
    """Per-IP read / write bandwidth: newest simulation (DMA ports summed per IP) vs measured IP bandwidth."""
    return cal.ip_bandwidth(db, scenario_id, variant_id, measurement_id)


@router.get("/calibration/clock-residency")
def clock_residency(scenario_id: str | None = None, db: Session = Depends(get_db)):
    """Measurements with clock-domain residency (CPU cluster · DSU · GPU): per-domain mean, high-OPP share, notes."""
    return cal.clock_residency_rows(db, scenario_id)


@router.get("/calibration/measurements/{measurement_id}")
def measurement(measurement_id: str, db: Session = Depends(get_db)):
    """Measured rails grouped as CPU / IP / BW / other and compared with each prediction; clock residency."""
    return cal.measurement_detail_view(db, measurement_id)


@router.get("/library/sw-timing")
def sw_timing(scenario_id: str | None = None, db: Session = Depends(get_db)):
    """SW task timing assumptions per scenario (range across variants) and measured task timing."""
    return lib.sw_timing(db, scenario_id=scenario_id)


# ------------------------------------------------------------------- S5: power coefficient fit
from scenario_db.api.auth import ApiPrincipal, require_roles  # noqa: E402
from scenario_db.api.schemas.power_fit import PowerFitRequest, PowerParamsCreateRequest  # noqa: E402


@router.post("/calibration/power-fit")
def power_fit(request: PowerFitRequest, db: Session = Depends(get_db),
              _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin"))):
    """Per category (CPU / IP / BW) factor that best maps predictions onto the measurements (proposal only)."""
    from scenario_db.api.resource_limits import admission_slot
    from scenario_db.api.services.power_fit import fit_proposal
    from scenario_db.config import get_settings

    with admission_slot("simulation", get_settings().simulation_max_concurrent_runs):
        return fit_proposal(db, request)


@router.post("/calibration/power-params")
def create_power_params(request: PowerParamsCreateRequest, db: Session = Depends(get_db),
                        principal: ApiPrincipal = Depends(require_roles("writer", "admin"))):
    """Publish the accepted factors as a new draft power_model_params version (base is never modified)."""
    from scenario_db.api.services.power_fit import create_calibrated_params

    return create_calibrated_params(db, request, principal.subject)


@router.get("/calibration/power-params")
def list_power_params(soc_ref: str | None = None, db: Session = Depends(get_db)):
    """power_model_params versions (id@version, status, calibration lineage)."""
    from scenario_db.db.models.capability import PowerModelParams as Row

    q = db.query(Row)
    if soc_ref:
        q = q.filter(Row.soc_ref == soc_ref)
    return [{"id": r.id, "version": r.version, "ref": f"{r.id}@{r.version}", "soc_ref": r.soc_ref, "status": r.status,
             "description": r.description, "calibrated": bool(((r.params or {}).get("calibration") or {}).get("fit")),
             "ip_power_scale": ((r.params or {}).get("calibration") or {}).get("ip_power_scale") or {}}
            for r in q.order_by(Row.soc_ref, Row.version).all()]
