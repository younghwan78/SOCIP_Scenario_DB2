from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.auth import MutationPrincipal, require_mutation_principal
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
from scenario_db.reporting.exporter import (
    artifact_metadata,
    build_report_context,
    build_report_zip_bytes,
    resolve_report_output_dir,
    write_report_bundle,
)
from scenario_db.sim.service import check_simulation_readiness_request, run_simulation_request

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("/run", response_model=SimulateRunResponse)
def run_simulation(
    request: SimulateRequest,
    db: Session = Depends(get_db),
    _principal: MutationPrincipal = Depends(require_mutation_principal),
):
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
    _principal: MutationPrincipal = Depends(require_mutation_principal),
):
    request = request or SimulationArtifactExportRequest()
    row = get_evidence(db, evidence_id)
    if row is None or row.kind != "evidence.simulation":
        raise NoResultFound(f"Simulation evidence '{evidence_id}' not found")
    evidence = _simulation_evidence_dict(row)
    settings = get_settings()
    try:
        output_dir = resolve_report_output_dir(
            request.output_dir,
            base_dir=settings.report_dir,
            allow_custom_dir=settings.allow_custom_report_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    context = build_report_context(
        evidence,
        scenario_name=request.scenario_name,
        variant_name=request.variant_name,
        project_ref=request.project_ref,
        soc_ref=request.soc_ref,
    )
    try:
        written = write_report_bundle(evidence, context=context, output_dir=output_dir, overwrite=request.overwrite)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Report artifact export failed: {exc}") from exc
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
                "mime": artifact.mime,
                "created_at": artifact.created_at,
                "prefix": artifact.prefix,
                "generator": artifact.generator,
            }
            for artifact in written.artifacts
        ],
    }


@router.get("/results/{evidence_id}/artifacts/download.zip")
def download_result_artifacts_zip(
    evidence_id: str,
    project_ref: str | None = Query(None),
    scenario_name: str | None = Query(None),
    variant_name: str | None = Query(None),
    soc_ref: str | None = Query(None),
    db: Session = Depends(get_db),
):
    row = get_evidence(db, evidence_id)
    if row is None or row.kind != "evidence.simulation":
        raise NoResultFound(f"Simulation evidence '{evidence_id}' not found")
    evidence = _simulation_evidence_dict(row)
    context = build_report_context(
        evidence,
        scenario_name=scenario_name,
        variant_name=variant_name,
        project_ref=project_ref,
        soc_ref=soc_ref,
    )
    zip_bytes, filename = build_report_zip_bytes(evidence, context=context)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/results/{evidence_id}", status_code=204)
def delete_result(
    evidence_id: str,
    db: Session = Depends(get_db),
    _principal: MutationPrincipal = Depends(require_mutation_principal),
):
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
