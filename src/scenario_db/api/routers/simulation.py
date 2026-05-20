from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.common import PagedResponse
from scenario_db.api.schemas.evidence import EvidenceResponse
from scenario_db.api.schemas.simulation import (
    SimulateRequest,
    SimulateRunResponse,
    SimulationArtifactExportRequest,
    SimulationArtifactExportResponse,
    SimulationReadinessResponse,
)
from scenario_db.config import get_settings
from scenario_db.db.repositories.evidence import (
    delete_simulation_evidence,
    get_evidence,
    list_simulation_results,
    update_simulation_artifacts,
)
from scenario_db.db.models.evidence import Evidence
from scenario_db.reporting.exporter import artifact_metadata, build_report_context, write_report_bundle
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


@router.post("/results/{evidence_id}/artifacts/export", response_model=SimulationArtifactExportResponse)
def export_result_artifacts(
    evidence_id: str,
    request: SimulationArtifactExportRequest | None = None,
    db: Session = Depends(get_db),
):
    request = request or SimulationArtifactExportRequest()
    row = get_evidence(db, evidence_id)
    if row is None or row.kind != "evidence.simulation":
        raise NoResultFound(f"Simulation evidence '{evidence_id}' not found")
    evidence = _simulation_evidence_dict(row)
    output_dir = Path(request.output_dir or get_settings().report_dir)
    context = build_report_context(
        evidence,
        scenario_name=request.scenario_name,
        variant_name=request.variant_name,
        project_ref=request.project_ref,
        soc_ref=request.soc_ref,
    )
    written = write_report_bundle(evidence, context=context, output_dir=output_dir, overwrite=request.overwrite)
    metadata = artifact_metadata(written)
    updated = update_simulation_artifacts(db, evidence_id, metadata)
    if updated is None:
        raise NoResultFound(f"Simulation evidence '{evidence_id}' not found")
    db.commit()
    return {
        "evidence_id": evidence_id,
        "prefix": written.prefix,
        "output_dir": str(written.output_dir),
        "artifacts": [
            {
                "type": artifact.type,
                "storage": artifact.storage,
                "path": str(artifact.path),
                "sha256": artifact.sha256,
                "bytes": artifact.bytes,
            }
            for artifact in written.artifacts
        ],
    }


@router.delete("/results/{evidence_id}", status_code=204)
def delete_result(evidence_id: str, db: Session = Depends(get_db)):
    deleted = delete_simulation_evidence(db, evidence_id)
    if not deleted:
        raise NoResultFound(f"Simulation evidence '{evidence_id}' not found")
    db.commit()
    return Response(status_code=204)


def _simulation_evidence_dict(row: Evidence) -> dict:
    return {
        "id": row.id,
        "schema_version": row.schema_version,
        "kind": row.kind,
        "scenario_ref": row.scenario_ref,
        "variant_ref": row.variant_ref,
        "sw_baseline_ref": getattr(row, "sw_baseline_ref", None),
        "execution_context": getattr(row, "execution_context", None) or {},
        "sweep_context": getattr(row, "sweep_context", None),
        "resolution_result": getattr(row, "resolution_result", None),
        "overall_feasibility": getattr(row, "overall_feasibility", None),
        "aggregation": getattr(row, "aggregation", None) or {},
        "kpi": getattr(row, "kpi", None) or {},
        "run_info": getattr(row, "run_info", None) or {},
        "ip_breakdown": getattr(row, "ip_breakdown", None) or [],
        "dma_breakdown": getattr(row, "dma_breakdown", None) or [],
        "timing_breakdown": getattr(row, "timing_breakdown", None) or [],
        "dvfs_breakdown": getattr(row, "dvfs_breakdown", None) or [],
        "timeline_events": getattr(row, "timeline_events", None) or [],
        "external_devices": getattr(row, "external_devices", None) or [],
        "topology_order": getattr(row, "topology_order", None) or [],
        "vdd_power": getattr(row, "vdd_power", None) or {},
        "calculation_trace": getattr(row, "calculation_trace", None),
        "params_hash": getattr(row, "params_hash", None),
        "artifacts": getattr(row, "artifacts", None) or [],
        "sw_version_hint": getattr(row, "sw_version_hint", None),
    }
