from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from scenario_db.api.schemas.exploration import (
    ExplorationExampleListResponse,
    ExplorationExampleResponse,
    ExplorationExampleSummary,
    ExplorationRecipeCompileRequest,
    ExplorationRecipeCompileResponse,
    ExplorationSweepCompileRequest,
    ExplorationSweepCompileResponse,
    ExplorationSweepPreviewRequest,
    ExplorationSweepPreviewResponse,
)
from scenario_db.db.models.capability import IpCatalog, SocPlatform
from scenario_db.db.models.definition import Project
from scenario_db.sim.exploration import (
    ExplorationRecipe,
    ExplorationSweep,
    compile_exploration_recipe,
    compile_exploration_sweep,
)
from scenario_db.sim.exploration_runner import run_exploration_sweep_preview

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE_ROOT = _REPO_ROOT / "demo" / "exploration_fixtures"


def list_exploration_examples() -> ExplorationExampleListResponse:
    items = [_example_summary(path, "recipe") for path in sorted((_FIXTURE_ROOT / "recipes").glob("*.yaml"))]
    items.extend(_example_summary(path, "sweep") for path in sorted((_FIXTURE_ROOT / "sweeps").glob("*.yaml")))
    return ExplorationExampleListResponse(items=items, total=len(items))


def get_exploration_example(example_id: str) -> ExplorationExampleResponse:
    kind, stem = _parse_example_id(example_id)
    path = _FIXTURE_ROOT / f"{kind}s" / f"{stem}.yaml"
    if not path.exists():
        raise NoResultFound(f"Exploration example '{example_id}' not found")
    yaml_text = path.read_text(encoding="utf-8")
    payload = _load_yaml_text(yaml_text)
    summary = _example_summary(path, kind)
    return ExplorationExampleResponse(
        **summary.model_dump(),
        yaml_text=yaml_text,
        payload=payload,
    )


def compile_recipe_request(request: ExplorationRecipeCompileRequest) -> ExplorationRecipeCompileResponse:
    recipe = ExplorationRecipe.model_validate(_payload_from_request(request.source_yaml, request.recipe, "recipe"))
    result = compile_exploration_recipe(recipe)
    return ExplorationRecipeCompileResponse(
        scenario=result.scenario,
        import_bundle=result.import_bundle,
        warnings=result.warnings,
        mapping_trace=result.mapping_trace,
    )


def compile_sweep_request(request: ExplorationSweepCompileRequest) -> ExplorationSweepCompileResponse:
    sweep = ExplorationSweep.model_validate(_payload_from_request(request.source_yaml, request.sweep, "sweep"))
    result = compile_exploration_sweep(sweep)
    return ExplorationSweepCompileResponse(
        import_bundle=result.import_bundle,
        cases=result.cases,
        warnings=result.warnings,
    )


def preview_sweep_request(db: Session, request: ExplorationSweepPreviewRequest) -> ExplorationSweepPreviewResponse:
    sweep = ExplorationSweep.model_validate(_payload_from_request(request.source_yaml, request.sweep, "sweep"))
    preview = run_exploration_sweep_preview(
        sweep,
        ip_catalog=_load_ip_catalog(db),
        project=_load_project(db, sweep.base_recipe.project_ref),
        soc=_load_soc(db, _soc_ref_from_sweep(sweep)),
        config=request.config,
        dvfs_tables=request.dvfs_tables,
        include_results=request.include_results,
    )
    return ExplorationSweepPreviewResponse(
        persisted=False,
        baseline_case_id=preview.baseline_case_id,
        cases=preview.cases,
        comparison=preview.comparison,
        import_bundle=preview.import_bundle,
    )


def _example_summary(path: Path, kind: Literal["recipe", "sweep"]) -> ExplorationExampleSummary:
    payload = _load_yaml_text(path.read_text(encoding="utf-8"))
    fixture_id = str(payload.get("id") or path.stem)
    base_recipe = payload.get("base_recipe") if kind == "sweep" else payload
    title = str(base_recipe.get("name") or payload.get("name") or fixture_id)
    category = base_recipe.get("category") or payload.get("category") or []
    tags = base_recipe.get("tags") or payload.get("tags") or category
    return ExplorationExampleSummary(
        id=f"{kind}:{path.stem}",
        type=kind,
        title=title,
        fixture_id=fixture_id,
        path=_repo_relative_path(path),
        scenario_id=base_recipe.get("scenario_id"),
        variant_id=base_recipe.get("variant_id"),
        tags=[str(item) for item in tags],
    )


def _parse_example_id(example_id: str) -> tuple[Literal["recipe", "sweep"], str]:
    if ":" not in example_id:
        raise NoResultFound(f"Exploration example '{example_id}' not found")
    kind, stem = example_id.split(":", 1)
    if kind not in {"recipe", "sweep"} or not stem:
        raise NoResultFound(f"Exploration example '{example_id}' not found")
    return kind, stem  # type: ignore[return-value]


def _payload_from_request(source_yaml: str | None, payload: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if source_yaml is not None:
        return _load_yaml_text(source_yaml)
    if payload is None:
        raise ValueError(f"{label} or source_yaml is required")
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _load_yaml_text(source_yaml: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(source_yaml)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("YAML payload must be a mapping")
    return payload


def _load_ip_catalog(db: Session) -> dict[str, IpCatalog]:
    return {row.id: row for row in db.query(IpCatalog).all()}


def _load_project(db: Session, project_ref: str | None) -> Project | None:
    if not project_ref:
        return None
    return db.query(Project).filter_by(id=project_ref).one_or_none()


def _load_soc(db: Session, soc_ref: str | None) -> SocPlatform | None:
    if not soc_ref:
        return None
    return db.query(SocPlatform).filter_by(id=soc_ref).one_or_none()


def _soc_ref_from_sweep(sweep: ExplorationSweep) -> str | None:
    recipe = sweep.base_recipe
    if recipe.soc_ref:
        return recipe.soc_ref
    if recipe.mapping_profile and recipe.mapping_profile.target_soc_ref:
        return recipe.mapping_profile.target_soc_ref
    return None


def _repo_relative_path(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def validation_detail(exc: ValidationError | ValueError) -> list[dict[str, Any]] | str:
    if isinstance(exc, ValidationError):
        return exc.errors()
    return str(exc)
