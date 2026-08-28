from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.auth import require_roles
from scenario_db.api.resource_limits import (
    admission_slot,
    enforce_request_size,
    enforce_timeline_frame_limit,
)
from scenario_db.api.schemas.exploration import (
    ExplorationExampleListResponse,
    ExplorationExampleResponse,
    ExplorationRecipeCompileRequest,
    ExplorationRecipeCompileResponse,
    ExplorationSweepCompileRequest,
    ExplorationSweepCompileResponse,
    ExplorationSweepPreviewRequest,
    ExplorationSweepPreviewResponse,
    ExplorationTemplateCompileRequest,
    ExplorationTemplateCompileResponse,
    ExplorationTemplatePreviewRequest,
    ExplorationTemplateSweepCompileRequest,
    ExplorationTemplateSweepPreviewRequest,
)
from scenario_db.api.services.exploration import (
    compile_recipe_request,
    compile_sweep_request,
    compile_template_request,
    compile_template_sweep_request,
    get_exploration_example,
    list_exploration_examples,
    preview_sweep_request,
    preview_template_request,
    preview_template_sweep_request,
    validation_detail,
)
from scenario_db.config import get_settings

router = APIRouter(prefix="/exploration", tags=["exploration"])


@router.get("/examples", response_model=ExplorationExampleListResponse)
def list_examples():
    return list_exploration_examples()


@router.get("/examples/{example_id}", response_model=ExplorationExampleResponse)
def get_example(example_id: str):
    return get_exploration_example(example_id)


@router.post(
    "/recipes/compile",
    response_model=ExplorationRecipeCompileResponse,
    dependencies=[Depends(require_roles("analyst", "writer", "admin"))],
)
def compile_recipe(request: ExplorationRecipeCompileRequest, db: Session = Depends(get_db)):
    try:
        settings = get_settings()
        enforce_request_size(request, settings.exploration_max_request_bytes)
        with admission_slot("exploration", settings.exploration_max_concurrent_requests):
            return compile_recipe_request(db, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc


@router.post(
    "/sweeps/compile",
    response_model=ExplorationSweepCompileResponse,
    dependencies=[Depends(require_roles("analyst", "writer", "admin"))],
)
def compile_sweep(request: ExplorationSweepCompileRequest, db: Session = Depends(get_db)):
    try:
        settings = get_settings()
        enforce_request_size(request, settings.exploration_max_request_bytes)
        with admission_slot("exploration", settings.exploration_max_concurrent_requests):
            return compile_sweep_request(db, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc


@router.post(
    "/templates/compile",
    response_model=ExplorationTemplateCompileResponse,
    dependencies=[Depends(require_roles("analyst", "writer", "admin"))],
)
def compile_template(request: ExplorationTemplateCompileRequest, db: Session = Depends(get_db)):
    try:
        settings = get_settings()
        enforce_request_size(request, settings.exploration_max_request_bytes)
        with admission_slot("exploration", settings.exploration_max_concurrent_requests):
            return compile_template_request(db, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc


@router.post(
    "/template-sweeps/compile",
    response_model=ExplorationSweepCompileResponse,
    dependencies=[Depends(require_roles("analyst", "writer", "admin"))],
)
def compile_template_sweep(request: ExplorationTemplateSweepCompileRequest, db: Session = Depends(get_db)):
    try:
        settings = get_settings()
        enforce_request_size(request, settings.exploration_max_request_bytes)
        with admission_slot("exploration", settings.exploration_max_concurrent_requests):
            return compile_template_sweep_request(db, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc


@router.post(
    "/sweeps/preview",
    response_model=ExplorationSweepPreviewResponse,
    dependencies=[Depends(require_roles("analyst", "writer", "admin"))],
)
def preview_sweep(request: ExplorationSweepPreviewRequest, db: Session = Depends(get_db)):
    try:
        settings = get_settings()
        enforce_request_size(request, settings.exploration_max_request_bytes)
        enforce_timeline_frame_limit(
            request.config.timeline_frame_count,
            settings.simulation_max_timeline_frames,
        )
        with admission_slot("exploration", settings.exploration_max_concurrent_requests):
            return preview_sweep_request(db, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc


@router.post(
    "/templates/preview",
    response_model=ExplorationSweepPreviewResponse,
    dependencies=[Depends(require_roles("analyst", "writer", "admin"))],
)
def preview_template(request: ExplorationTemplatePreviewRequest, db: Session = Depends(get_db)):
    try:
        settings = get_settings()
        enforce_request_size(request, settings.exploration_max_request_bytes)
        enforce_timeline_frame_limit(
            request.config.timeline_frame_count,
            settings.simulation_max_timeline_frames,
        )
        with admission_slot("exploration", settings.exploration_max_concurrent_requests):
            return preview_template_request(db, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc


@router.post(
    "/template-sweeps/preview",
    response_model=ExplorationSweepPreviewResponse,
    dependencies=[Depends(require_roles("analyst", "writer", "admin"))],
)
def preview_template_sweep(request: ExplorationTemplateSweepPreviewRequest, db: Session = Depends(get_db)):
    try:
        settings = get_settings()
        enforce_request_size(request, settings.exploration_max_request_bytes)
        enforce_timeline_frame_limit(
            request.config.timeline_frame_count,
            settings.simulation_max_timeline_frames,
        )
        with admission_slot("exploration", settings.exploration_max_concurrent_requests):
            return preview_template_sweep_request(db, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc
