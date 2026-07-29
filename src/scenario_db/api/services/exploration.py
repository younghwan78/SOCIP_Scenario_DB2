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
    ExplorationTemplateCompileRequest,
    ExplorationTemplateCompileResponse,
    ExplorationTemplatePreviewRequest,
    ExplorationTemplateSweepCompileRequest,
    ExplorationTemplateSweepPreviewRequest,
)
from scenario_db.db.models.capability import IpCatalog, SocPlatform
from scenario_db.db.models.definition import Project
from scenario_db.config import get_settings
from scenario_db.sim.exploration import (
    ExplorationRecipe,
    ExplorationSweep,
    compile_exploration_recipe,
    compile_exploration_sweep,
)
from scenario_db.sim.chain_templates import compile_chain_template, compile_chain_template_sweep
from scenario_db.sim.exploration_runner import run_chain_template_preview, run_chain_template_sweep_preview, run_exploration_sweep_preview

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE_ROOT = _REPO_ROOT / "demo" / "exploration_fixtures"
ExampleKind = Literal["recipe", "sweep", "template", "template_sweep"]
_EXAMPLE_DIRS: dict[ExampleKind, str] = {
    "recipe": "recipes",
    "sweep": "sweeps",
    "template": "templates",
    "template_sweep": "template_sweeps",
}


def list_exploration_examples() -> ExplorationExampleListResponse:
    items = [_example_summary(path, kind) for kind, path in _iter_example_paths()]
    return ExplorationExampleListResponse(items=items, total=len(items))


def get_exploration_example(example_id: str) -> ExplorationExampleResponse:
    kind, stem = _parse_example_id(example_id)
    path = _example_path(kind, stem)
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


def compile_recipe_request(db: Session | None, request: ExplorationRecipeCompileRequest) -> ExplorationRecipeCompileResponse:
    recipe = ExplorationRecipe.model_validate(_payload_from_request(request.source_yaml, request.recipe, "recipe"))
    result = compile_exploration_recipe(recipe)
    _apply_compile_context_warnings(result, db, request.db_project_ref)
    return _recipe_compile_response(result)


def compile_sweep_request(
    db: Session | None,
    request: ExplorationSweepCompileRequest,
    *,
    max_cases: int | None = None,
) -> ExplorationSweepCompileResponse:
    sweep = ExplorationSweep.model_validate(_payload_from_request(request.source_yaml, request.sweep, "sweep"))
    result = compile_exploration_sweep(
        sweep,
        max_cases=max_cases or get_settings().exploration_max_cases,
    )
    _apply_compile_context_warnings(result, db, request.db_project_ref)
    return _sweep_compile_response(result)


def compile_template_request(db: Session | None, request: ExplorationTemplateCompileRequest) -> ExplorationTemplateCompileResponse:
    result = compile_chain_template(_payload_from_request(request.source_yaml, request.template, "template"))
    _apply_compile_context_warnings(result, db, request.db_project_ref)
    return _template_compile_response(result)


def compile_template_sweep_request(
    db: Session | None,
    request: ExplorationTemplateSweepCompileRequest,
    *,
    max_cases: int | None = None,
) -> ExplorationSweepCompileResponse:
    result = compile_chain_template_sweep(
        _payload_from_request(request.source_yaml, request.sweep, "template_sweep"),
        max_cases=max_cases or get_settings().exploration_max_cases,
    )
    _apply_compile_context_warnings(result, db, request.db_project_ref)
    return _sweep_compile_response(result)


def preview_sweep_request(
    db: Session,
    request: ExplorationSweepPreviewRequest,
    *,
    max_cases: int | None = None,
) -> ExplorationSweepPreviewResponse:
    sweep = ExplorationSweep.model_validate(_payload_from_request(request.source_yaml, request.sweep, "sweep"))
    project = _load_context_project(db, request.db_project_ref or sweep.base_recipe.project_ref)
    soc = _load_context_soc(db, project, _soc_ref_from_sweep(sweep))
    preview = run_exploration_sweep_preview(
        sweep,
        ip_catalog=_load_ip_catalog(db, project=project, soc=soc),
        project=project,
        soc=soc,
        config=request.config,
        dvfs_tables=request.dvfs_tables,
        include_results=request.include_results,
        max_cases=max_cases or get_settings().exploration_max_cases,
    )
    _apply_preview_context_warnings(preview, db, request.db_project_ref)
    return _preview_response(preview)


def preview_template_sweep_request(
    db: Session,
    request: ExplorationTemplateSweepPreviewRequest,
    *,
    max_cases: int | None = None,
) -> ExplorationSweepPreviewResponse:
    sweep = _payload_from_request(request.source_yaml, request.sweep, "template_sweep")
    base_template = _base_template_payload(sweep)
    project = _load_context_project(db, request.db_project_ref or base_template.get("project_ref"))
    soc = _load_context_soc(db, project, _soc_ref_from_template_payload(base_template))
    preview = run_chain_template_sweep_preview(
        sweep,
        ip_catalog=_load_ip_catalog(db, project=project, soc=soc),
        project=project,
        soc=soc,
        config=request.config,
        dvfs_tables=request.dvfs_tables,
        include_results=request.include_results,
        max_cases=max_cases or get_settings().exploration_max_cases,
    )
    _apply_preview_context_warnings(preview, db, request.db_project_ref)
    return _preview_response(preview)


def preview_template_request(db: Session, request: ExplorationTemplatePreviewRequest) -> ExplorationSweepPreviewResponse:
    template = _payload_from_request(request.source_yaml, request.template, "template")
    project = _load_context_project(db, request.db_project_ref or template.get("project_ref"))
    soc = _load_context_soc(db, project, _soc_ref_from_template_payload(template))
    preview = run_chain_template_preview(
        template,
        ip_catalog=_load_ip_catalog(db, project=project, soc=soc),
        project=project,
        soc=soc,
        config=request.config,
        dvfs_tables=request.dvfs_tables,
        include_results=request.include_results,
    )
    _apply_preview_context_warnings(preview, db, request.db_project_ref)
    return _preview_response(preview)


def _recipe_compile_response(result: Any) -> ExplorationRecipeCompileResponse:
    return ExplorationRecipeCompileResponse(
        scenario=result.scenario,
        import_bundle=result.import_bundle,
        warnings=result.warnings,
        mapping_trace=result.mapping_trace,
    )


def _template_compile_response(result: Any) -> ExplorationTemplateCompileResponse:
    return ExplorationTemplateCompileResponse(
        scenario=result.scenario,
        import_bundle=result.import_bundle,
        warnings=result.warnings,
        mapping_trace=result.mapping_trace,
    )


def _sweep_compile_response(result: Any) -> ExplorationSweepCompileResponse:
    return ExplorationSweepCompileResponse(
        import_bundle=result.import_bundle,
        cases=result.cases,
        warnings=result.warnings,
    )


def _preview_response(preview: Any) -> ExplorationSweepPreviewResponse:
    return ExplorationSweepPreviewResponse(
        persisted=False,
        baseline_case_id=preview.baseline_case_id,
        cases=preview.cases,
        comparison=preview.comparison,
        warnings=preview.warnings,
        import_bundle=preview.import_bundle,
    )


def _iter_example_paths() -> list[tuple[ExampleKind, Path]]:
    items: list[tuple[ExampleKind, Path]] = []
    for kind, folder in _EXAMPLE_DIRS.items():
        items.extend((kind, path) for path in sorted((_FIXTURE_ROOT / folder).glob("*.yaml")))
    return items


def _example_path(kind: ExampleKind, stem: str) -> Path:
    return _FIXTURE_ROOT / _EXAMPLE_DIRS[kind] / f"{stem}.yaml"


def _example_summary(path: Path, kind: ExampleKind) -> ExplorationExampleSummary:
    payload = _load_yaml_text(path.read_text(encoding="utf-8"))
    fixture_id = str(payload.get("id") or path.stem)
    base_recipe = payload.get("base_recipe") if kind == "sweep" else payload.get("base_template") if kind == "template_sweep" else payload
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


def _parse_example_id(example_id: str) -> tuple[ExampleKind, str]:
    if ":" not in example_id:
        raise NoResultFound(f"Exploration example '{example_id}' not found")
    kind, stem = example_id.split(":", 1)
    if kind not in _EXAMPLE_DIRS or not stem:
        raise NoResultFound(f"Exploration example '{example_id}' not found")
    return kind, stem  # type: ignore[return-value]


def _base_template_payload(sweep: dict[str, Any]) -> dict[str, Any]:
    base_template = sweep.get("base_template")
    return base_template if isinstance(base_template, dict) else {}


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


def _load_ip_catalog(db: Session, *, project: Project | None = None, soc: SocPlatform | None = None) -> dict[str, IpCatalog]:
    rows = db.query(IpCatalog).all()
    scoped_refs = _context_ip_refs(project, soc)
    if scoped_refs:
        rows = [row for row in rows if row.id in scoped_refs]
    return {row.id: row for row in rows}


def _load_project(db: Session, project_ref: str | None) -> Project | None:
    if not project_ref:
        return None
    return db.query(Project).filter_by(id=project_ref).one_or_none()


def _load_soc(db: Session, soc_ref: str | None) -> SocPlatform | None:
    if not soc_ref:
        return None
    return db.query(SocPlatform).filter_by(id=soc_ref).one_or_none()


def _load_context_project(db: Session, project_ref: str | None) -> Project | None:
    return _load_project(db, project_ref)


def _load_context_soc(db: Session, project: Project | None, fallback_soc_ref: str | None = None) -> SocPlatform | None:
    return _load_soc(db, _soc_ref_from_project(project) or fallback_soc_ref)


def _soc_ref_from_project(project: Project | None) -> str | None:
    if project is None:
        return None
    metadata = project.metadata_ or {}
    globals_ = project.globals_ or {}
    soc_ref = metadata.get("soc_ref") or globals_.get("soc_ref")
    return str(soc_ref) if soc_ref else None


def _context_ip_refs(project: Project | None, soc: SocPlatform | None) -> set[str]:
    refs: set[str] = set()
    if soc is not None:
        for item in soc.ips or []:
            if isinstance(item, dict) and item.get("ref"):
                refs.add(str(item["ref"]))
            elif getattr(item, "ref", None):
                refs.add(str(item.ref))
    if project is not None:
        metadata = project.metadata_ or {}
        for key in ("sensor_module_ref", "display_module_ref"):
            if metadata.get(key):
                refs.add(str(metadata[key]))
    return refs


def _apply_compile_context_warnings(result: Any, db: Session | None, db_project_ref: str | None) -> None:
    if db is None or not db_project_ref:
        return
    project = _load_project(db, db_project_ref)
    context_warnings: list[str] = []
    if project is None:
        context_warnings.append(
            f"Selected DB project '{db_project_ref}' was not found; IP catalog validation was skipped."
        )
        _append_result_warnings(result, context_warnings)
        return
    soc = _load_context_soc(db, project)
    ip_catalog = _load_ip_catalog(db, project=project, soc=soc)
    warnings = [
        *_project_mismatch_warnings(result.import_bundle, db_project_ref),
        *_missing_ip_warnings(result.import_bundle, ip_catalog, context=f"db_project_ref={db_project_ref}"),
    ]
    _append_result_warnings(result, warnings)


def _apply_preview_context_warnings(preview: Any, db: Session | None, db_project_ref: str | None) -> None:
    if db is None or not db_project_ref:
        return
    project = _load_project(db, db_project_ref)
    if project is None:
        _append_preview_warnings(
            preview,
            [f"Selected DB project '{db_project_ref}' was not found; IP catalog validation was skipped."],
        )
        return
    _append_preview_warnings(preview, _project_mismatch_warnings(preview.import_bundle, db_project_ref))


def _project_mismatch_warnings(import_bundle: dict[str, Any], db_project_ref: str) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for doc in import_bundle.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        project_ref = doc.get("project_ref")
        if project_ref and project_ref != db_project_ref and str(project_ref) not in seen:
            seen.add(str(project_ref))
            warnings.append(
                f"YAML project_ref '{project_ref}' differs from selected DB project '{db_project_ref}'; "
                "IP catalog validation uses the selected DB project."
            )
    return warnings


def _missing_ip_warnings(import_bundle: dict[str, Any], ip_catalog: dict[str, IpCatalog], *, context: str) -> list[str]:
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for doc in import_bundle.get("documents") or []:
        if not isinstance(doc, dict):
            continue
        pipeline = doc.get("pipeline") if isinstance(doc.get("pipeline"), dict) else {}
        for node in pipeline.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "")
            ip_ref = str(node.get("ip_ref") or "")
            if not node_id or not ip_ref or ip_ref in ip_catalog:
                continue
            key = (node_id, ip_ref)
            if key in seen:
                continue
            seen.add(key)
            warnings.append(
                f"{node_id} references ip_ref '{ip_ref}' that is not present in the selected DB catalog ({context}); "
                "simulation workload, power, and timing for this node will be skipped or zero."
            )
    return warnings


def _append_result_warnings(result: Any, warnings: list[str]) -> None:
    new_warnings = [warning for warning in warnings if warning and warning not in result.warnings]
    if not new_warnings:
        return
    result.warnings.extend(new_warnings)
    _append_import_report_warnings(result.import_bundle, new_warnings)


def _append_preview_warnings(preview: Any, warnings: list[str]) -> None:
    new_warnings = [warning for warning in warnings if warning and warning not in preview.warnings]
    if not new_warnings:
        return
    preview.warnings.extend(new_warnings)
    _append_import_report_warnings(preview.import_bundle, new_warnings)


def _append_import_report_warnings(import_bundle: dict[str, Any], warnings: list[str]) -> None:
    if not warnings:
        return
    report = import_bundle.setdefault("import_report", {})
    report["ok"] = False
    messages = report.setdefault("messages", [])
    messages.extend(
        {"level": "warning", "code": "exploration_db_catalog_warning", "message": warning}
        for warning in warnings
    )


def _soc_ref_from_sweep(sweep: ExplorationSweep) -> str | None:
    recipe = sweep.base_recipe
    if recipe.soc_ref:
        return recipe.soc_ref
    if recipe.mapping_profile and recipe.mapping_profile.target_soc_ref:
        return recipe.mapping_profile.target_soc_ref
    return None


def _soc_ref_from_template_payload(template: dict[str, Any]) -> str | None:
    soc_ref = template.get("soc_ref")
    if not soc_ref and isinstance(template.get("mapping_profile"), dict):
        soc_ref = template["mapping_profile"].get("target_soc_ref")
    return soc_ref if isinstance(soc_ref, str) else None


def _repo_relative_path(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def validation_detail(exc: ValidationError | ValueError) -> list[dict[str, Any]] | str:
    if isinstance(exc, ValidationError):
        return exc.errors()
    return str(exc)
