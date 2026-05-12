from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.exploration import (
    ExplorationExampleListResponse,
    ExplorationExampleResponse,
    ExplorationRecipeCompileRequest,
    ExplorationRecipeCompileResponse,
    ExplorationSweepCompileRequest,
    ExplorationSweepCompileResponse,
    ExplorationSweepPreviewRequest,
    ExplorationSweepPreviewResponse,
)
from scenario_db.api.services.exploration import (
    compile_recipe_request,
    compile_sweep_request,
    get_exploration_example,
    list_exploration_examples,
    preview_sweep_request,
    validation_detail,
)

router = APIRouter(prefix="/exploration", tags=["exploration"])


@router.get("/examples", response_model=ExplorationExampleListResponse)
def list_examples():
    return list_exploration_examples()


@router.get("/examples/{example_id}", response_model=ExplorationExampleResponse)
def get_example(example_id: str):
    return get_exploration_example(example_id)


@router.post("/recipes/compile", response_model=ExplorationRecipeCompileResponse)
def compile_recipe(request: ExplorationRecipeCompileRequest):
    try:
        return compile_recipe_request(request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc


@router.post("/sweeps/compile", response_model=ExplorationSweepCompileResponse)
def compile_sweep(request: ExplorationSweepCompileRequest):
    try:
        return compile_sweep_request(request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc


@router.post("/sweeps/preview", response_model=ExplorationSweepPreviewResponse)
def preview_sweep(request: ExplorationSweepPreviewRequest, db: Session = Depends(get_db)):
    try:
        return preview_sweep_request(db, request)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc
