"""Sensor catalog browsing and reusable CIS readout calculations."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy.orm import Session
from scenario_db.api.auth import require_roles
from scenario_db.api.deps import get_db
from scenario_db.db.models.definition import Project
from scenario_db.db.models.sensor import SensorCatalog, SensorTimingProfile, SensorBoardLineup, ProjectSensorSelection
from scenario_db.models.common import BaseScenarioModel
from scenario_db.models.sensor import SensorTiming
from scenario_db.sim.sensor_timing import calculate_sensor_timing, catalog_mode_timing

from scenario_db.sim.sensor_transport import calculate_sensor_transport

router = APIRouter(prefix="/sensors", tags=["sensors"])


def row_or_404(db, cls, key):
    row = db.get(cls, key)
    if row is None: raise HTTPException(404, "Sensor resource not found")
    return row

@router.get("/catalogs")
def catalogs(board: str | None = None, sensor_name: str | None = None,
             limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
             db: Session = Depends(get_db)):
    q = db.query(SensorCatalog)
    if board: q = q.filter_by(board=board)
    if sensor_name: q = q.filter_by(sensor_name=sensor_name)
    return {"total": q.count(), "items": [{"id": r.id, "board": r.board, "sensor_name": r.sensor_name,
        "mode_count": r.document["mode_count"], "sha256": r.yaml_sha256}
        for r in q.order_by(SensorCatalog.id).offset(offset).limit(limit)]}

@router.get("/catalogs/{catalog_id}")
def catalog(catalog_id: str, db: Session = Depends(get_db)):
    r = row_or_404(db, SensorCatalog, catalog_id)
    return {"document": r.document, "sha256": r.yaml_sha256}

@router.get("/catalogs/{catalog_id}/modes/{mode_label}/timing")
def mode_timing(catalog_id: str, mode_label: str, db: Session = Depends(get_db)):
    r = row_or_404(db, SensorCatalog, catalog_id)
    mode = r.document["modes"].get(mode_label)
    if mode is None: raise HTTPException(404, "Unknown full mode label")
    return {"catalog_id": r.id, "mode_label": mode_label, **catalog_mode_timing(mode)}

@router.get("/catalogs/{catalog_id}/modes/{mode_label}/transport")
def mode_transport(catalog_id: str, mode_label: str, db: Session = Depends(get_db)):
    row = row_or_404(db, SensorCatalog, catalog_id)
    mode = row.document["modes"].get(mode_label)
    if mode is None:
        raise HTTPException(404, "Unknown full mode label")
    return {"catalog_id": row.id, "board": row.board, "mode_label": mode_label,
            "catalog_sha256": row.yaml_sha256,
            "inputs": {"mode": mode, "csis_wiring": row.document["csis_wiring"]},
            **calculate_sensor_transport(mode, row.document["csis_wiring"])}


@router.get("/timing-profiles")
def timing_profiles(sensor_name: str | None = None, db: Session = Depends(get_db)):
    q = db.query(SensorTimingProfile)
    if sensor_name: q = q.filter_by(sensor_name=sensor_name)
    return {"items": [{"id": r.id, "sensor_name": r.sensor_name,
        "revision": r.document["revision"], "modes": list(r.document["modes"]), "sha256": r.yaml_sha256}
        for r in q.order_by(SensorTimingProfile.id)]}

@router.get("/timing-profiles/{profile_id}/modes/{mode_label}")
def profile_timing(profile_id: str, mode_label: str, db: Session = Depends(get_db)):
    r = row_or_404(db, SensorTimingProfile, profile_id)
    mode = r.document["modes"].get(mode_label)
    if mode is None: raise HTTPException(404, "Unknown CIS mode label")
    mode = {**mode, "source": {**mode["source"], "timing_profile_id": r.id, "timing_profile_sha256": r.yaml_sha256, "mode_label": mode_label, "revision": r.document["revision"]}}
    return {"profile_id": r.id, "revision": r.document["revision"], "sha256": r.yaml_sha256,
        "mode_label": mode_label, "inputs": mode, **calculate_sensor_timing(mode)}

@router.post("/timing/calculate")
def calculate(request: SensorTiming):
    # Read-only exploration: no mutation of the source timing profile.
    return calculate_sensor_timing(request.model_dump())

@router.get("/lineups")
def lineups(db: Session = Depends(get_db)):
    return {"items": [r.document for r in db.query(SensorBoardLineup).order_by(SensorBoardLineup.id)]}

class Selection(BaseScenarioModel):
    project_ref: str
    slot: str = Field(min_length=1)
    catalog_ref: str
    lineup_ref: str
    board_config: str

@router.post("/selections", dependencies=[Depends(require_roles("writer", "admin"))])
def select_sensor(request: Selection, db: Session = Depends(get_db)):
    row_or_404(db, Project, request.project_ref)
    cat = row_or_404(db, SensorCatalog, request.catalog_ref)
    lineup = row_or_404(db, SensorBoardLineup, request.lineup_ref)
    board = lineup.document["boards"].get(cat.board, {})
    config = next((c for c in board.get("configs", []) if c["config"] == request.board_config), None)
    installed = config.get("lineup", {}).get(request.slot, []) if config else []
    installed = installed if isinstance(installed, list) else [installed]
    if cat.sensor_name not in installed:
        raise HTTPException(422, "Sensor is not installed in this source board/config/slot; orphan catalogs cannot be selected")
    key = (request.project_ref, request.slot)
    row = db.get(ProjectSensorSelection, key) or ProjectSensorSelection(project_ref=request.project_ref, slot=request.slot)
    for field in ("catalog_ref", "lineup_ref", "board_config"): setattr(row, field, getattr(request, field))
    db.add(row); db.commit()
    return request.model_dump()

@router.get("/selections")
def selections(project_ref: str, db: Session = Depends(get_db)):
    return {"items": [{k: getattr(r, k) for k in Selection.model_fields}
        for r in db.query(ProjectSensorSelection).filter_by(project_ref=project_ref).order_by(ProjectSensorSelection.slot)]}


class PrepareProjection(BaseScenarioModel):
    scenario_id: str
    variant_id: str
    node_id: str
    catalog_ref: str
    mode_label: str
    lineup_ref: str
    board_config: str
    slot: str


@router.post("/projection/prepare")
def prepare_projection(request: PrepareProjection, db: Session = Depends(get_db)):
    from scenario_db.db.repositories.scenario_graph import load_canonical_graph
    from scenario_db.sim.sensor_projection import resolve_sensor_modes
    from scenario_db.sim.adapter import build_simulation_inputs
    from scenario_db.sim.models import SimulationRunConfig
    cat = row_or_404(db, SensorCatalog, request.catalog_ref)
    lineup = row_or_404(db, SensorBoardLineup, request.lineup_ref)
    binding = {k: getattr(request, k) for k in (
        "catalog_ref", "mode_label", "lineup_ref", "board_config", "slot")}
    binding.update(catalog_sha256=cat.yaml_sha256, lineup_sha256=lineup.yaml_sha256)
    config = SimulationRunConfig(sensor_modes={request.node_id: binding})
    try:
        graph = load_canonical_graph(db, request.scenario_id, request.variant_id)
        resolved = resolve_sensor_modes(db, graph, config)
        inputs = build_simulation_inputs(resolved, config)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"scenario_id": request.scenario_id, "variant_id": request.variant_id,
            "config": {"sensor_modes": {request.node_id: binding}},
            "external_devices": inputs.external_devices, "warnings": inputs.warnings}
