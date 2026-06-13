"""CLI: run a projection recipe to produce projected V evidence YAML.

Example:

    uv run python -m scenario_db.projection.cli \
      --recipe demo/projection/uhd30-vdis-u-to-v.yaml \
      --out generated/projection --strict
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from scenario_db.legacy_import.read_legacy import read_yaml, write_yaml
from scenario_db.legacy_import.report import ImportReport
from scenario_db.projection.calibrate import compute_calibration
from scenario_db.projection.models import ProjectionRecipe
from scenario_db.projection.project import assemble_projection
from scenario_db.projection.verify import compute_projection_error
from scenario_db.models.evidence.simulation import SimulationEvidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project a target project's simulation using another project's calibration.",
    )
    parser.add_argument("--recipe", type=Path, required=True, help="projection.recipe YAML.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for generated YAML.")
    parser.add_argument(
        "--verify",
        type=Path,
        help="Optional V measurement evidence YAML; emit a projected-vs-measured error report.",
    )
    parser.add_argument("--strict", action="store_true", help="Return non-zero when conversion reports errors.")
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="With --strict, return non-zero when conversion reports warnings.",
    )
    parser.add_argument(
        "--skip-generated-validation",
        action="store_true",
        help="Do not validate generated YAML against the SimulationEvidence model.",
    )
    return parser


def _resolve(base_dir: Path, ref: str) -> Path:
    path = Path(ref)
    return path if path.is_absolute() else base_dir / path


def _load_source(base_dir: Path, ref: str, code: str, report: ImportReport) -> dict | None:
    path = _resolve(base_dir, ref)
    if not path.exists():
        report.error(code, f"Projection source not found: {path}", str(path))
        return None
    try:
        raw = read_yaml(path)
    except Exception as exc:  # noqa: BLE001 - defensive
        report.error(code, f"Cannot read source: {exc}", str(path))
        return None
    if not isinstance(raw, dict):
        report.error(code, "Projection source must be a YAML object.", str(path))
        return None
    return raw


def run_projection(args: argparse.Namespace, report: ImportReport) -> dict | None:
    if not args.recipe.exists():
        report.error("recipe_not_found", f"Recipe not found: {args.recipe}", str(args.recipe))
        return None
    try:
        raw_recipe = read_yaml(args.recipe)
        recipe = ProjectionRecipe.model_validate(raw_recipe)
    except ValidationError as exc:
        report.error("recipe_invalid", _fmt(exc), str(args.recipe))
        return None
    except Exception as exc:  # noqa: BLE001
        report.error("recipe_unreadable", f"Cannot read recipe: {exc}", str(args.recipe))
        return None

    base = args.recipe.parent
    u_meas = _load_source(base, recipe.sources.u_measurement, "u_measurement_error", report)
    u_sim = _load_source(base, recipe.sources.u_simulation, "u_simulation_error", report)
    v_sim = _load_source(base, recipe.sources.v_simulation, "v_simulation_error", report)
    if not report.ok:
        return None

    cal = compute_calibration(u_sim, u_meas)
    if cal.total_power_factor is None and not cal.rail_factors:
        report.warning(
            "calibration_empty",
            "No overlapping metrics between U sim and U measurement; projection is unscaled.",
        )
    else:
        report.info(
            "calibration_computed",
            f"total_power_factor={cal.total_power_factor}, rails={len(cal.rail_factors)}.",
        )

    if not recipe.cluster_scaling and (u_meas.get("sw_task_timing")):
        report.warning(
            "no_cluster_scaling",
            "U measurement has sw_task_timing but recipe has no cluster_scaling; "
            "SW timing is projected unscaled (time_scale=1.0).",
        )

    doc = assemble_projection(recipe, u_meas, u_sim, v_sim, cal)

    if not args.skip_generated_validation:
        try:
            SimulationEvidence.model_validate(doc)
            report.increment("validated_yaml")
        except ValidationError as exc:
            report.error("generated_yaml_schema_invalid", _fmt(exc), doc.get("id"))
            return None

    if args.verify is not None:
        v_meas = _load_source(Path("."), str(args.verify), "verify_source_error", report)
        if v_meas is not None:
            error_report = compute_projection_error(doc, v_meas)
            report.info(
                "projection_verified",
                f"mean_abs_pct_error={error_report['summary'].get('mean_abs_pct_error')}, "
                f"worst={error_report['summary'].get('worst_metric')}.",
            )
            doc.setdefault("calculation_trace", {})["projection"]["error_report"] = error_report

    return doc


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ImportReport()

    doc = run_projection(args, report)
    if doc is not None:
        out_path = args.out / "03_evidence" / f"{doc['id']}.yaml"
        write_yaml(out_path, doc)
        report.increment("evidence_projection")
        report.info("projection_emitted", f"Emitted projected evidence: {out_path}", str(out_path))

    report_path = args.out / "projection_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2))

    has_warning = any(m.level == "warning" for m in report.messages)
    return 1 if args.strict and (not report.ok or (args.fail_on_warning and has_warning)) else 0


def _fmt(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", ())) or "<root>"
    return f"Validation failed at {loc}: {first.get('msg', str(exc))}"


if __name__ == "__main__":
    raise SystemExit(main())
