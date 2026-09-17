"""Curated camera import and verified cross-SoC timing selection."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scenario_db.api.auth import require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.services.timing_profiles import measurement_from_row
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.meas_import.camera import (
    parse_markdown,
    assemble_camera,
    bind_graph,
    canonical_hash,
    commit_camera,
)
from scenario_db.models.common import BaseScenarioModel
from scenario_db.models.evidence.measurement import MeasurementEvidence
from scenario_db.sim.sw_projection import SwProjectionSelection, build_projection

router = APIRouter(prefix="/profiling", tags=["camera profiling"])


class CameraImportRequest(BaseScenarioModel):
    markdown: str = Field(max_length=1_000_000)
    expected_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CameraEvidenceRequest(BaseScenarioModel):
    evidence: MeasurementEvidence
    expected_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def prepare_import(db, request):
    if len(request.model_dump_json().encode("utf-8")) > 1_100_000:
        raise ValueError("camera import request exceeds size limit")
    if isinstance(request, CameraImportRequest):
        bundle = parse_markdown(request.markdown)
        evidence = assemble_camera(bundle)
        warnings = (
            [
                "Trace is not read by this endpoint. Use the local camera CLI for a bounded trace preview."
            ]
            if bundle.semantic_trace
            else []
        )
    else:
        evidence = request.evidence.model_copy(deep=True)
        warnings = []
        if not evidence.pipeline_model:
            raise ValueError("camera evidence requires pipeline_model")
        if len(evidence.timeline_events) > 2000:
            raise ValueError("timeline preview exceeds 2000 events")
    bind_graph(evidence, load_canonical_graph(db, evidence.scenario_ref, evidence.variant_ref))
    return evidence, warnings


@router.post("/import/preview", dependencies=[Depends(require_roles("analyst", "writer", "admin"))])
def preview(request: CameraImportRequest | CameraEvidenceRequest, db: Session = Depends(get_db)):
    try:
        evidence, warnings = prepare_import(db, request)
        measured = {t.task for t in evidence.sw_task_timing}
        missing = [
            t.task_id
            for t in evidence.pipeline_model.tasks
            if t.kind == "sw"
            and t.task_id in evidence.pipeline_model.execution_path.enabled_task_ids
            and t.task_id not in measured
        ]
        return dict(
            evidence=evidence.model_dump(mode="json"),
            sha256=canonical_hash(evidence),
            persisted=False,
            warnings=warnings,
            missing_sw_statistics=missing,
            hw_usage="validation_only",
        )
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/import/commit", dependencies=[Depends(require_roles("writer", "admin"))])
def commit(request: CameraImportRequest | CameraEvidenceRequest, db: Session = Depends(get_db)):
    try:
        if request.expected_hash is None:
            raise ValueError("preview hash required")
        evidence, _ = prepare_import(db, request)
        result = commit_camera(db, evidence, request.expected_hash)
        db.commit()
        return result
    except (ValueError, LookupError) as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409, "evidence conflict or unregistered reference; preview again"
        ) from exc


@router.post(
    "/sw-projection/prepare", dependencies=[Depends(require_roles("analyst", "writer", "admin"))]
)
def prepare_projection(request: SwProjectionSelection, db: Session = Depends(get_db)):
    try:
        source = db.get(Evidence, request.source_evidence_ref)
        if source is None or source.kind != "evidence.measurement":
            raise ValueError("source measurement not found")
        graph = load_canonical_graph(db, request.target_scenario_ref, request.target_variant_ref)
        return build_projection(measurement_from_row(source), source.yaml_sha256, graph, request)
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/stage-comparison")
def stage_comparison(measurement_id: str, prediction_id: str, db: Session = Depends(get_db)):
    from scenario_db.api.schemas.evidence import EvidenceResponse
    from scenario_db.comparison.camera import compare_camera_stages

    measurement, prediction = db.get(Evidence, measurement_id), db.get(Evidence, prediction_id)
    if measurement is None or prediction is None:
        raise HTTPException(404, "evidence not found")
    try:
        return compare_camera_stages(
            EvidenceResponse.model_validate(measurement).model_dump(mode="json"),
            EvidenceResponse.model_validate(prediction).model_dump(mode="json"),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
