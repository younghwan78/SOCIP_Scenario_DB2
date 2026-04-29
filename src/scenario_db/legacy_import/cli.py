from __future__ import annotations

import argparse
import json
from pathlib import Path

from scenario_db.legacy_import.emit_canonical_yaml import emit_catalog, emit_hw_catalog
from scenario_db.legacy_import.normalize_display import convert_display_catalog, load_legacy_display
from scenario_db.legacy_import.normalize_hw import convert_hw_catalog, load_legacy_hw
from scenario_db.legacy_import.normalize_scenario import (
    convert_scenario_group_usecase,
    convert_scenario_usecase,
    load_legacy_scenario,
)
from scenario_db.legacy_import.normalize_sensor import convert_sensor_catalog, load_legacy_sensor
from scenario_db.legacy_import.read_legacy import read_yaml
from scenario_db.legacy_import.report import ImportReport
from scenario_db.legacy_import.validate_generated import validate_generated_yaml


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert legacy simulation YAML into canonical ScenarioDB YAML.",
    )
    parser.add_argument("--hw", type=Path, help="Legacy projectA_hw.yaml path.")
    parser.add_argument("--sensor", type=Path, help="Legacy sensor_config.yaml path.")
    parser.add_argument("--display", type=Path, help="Optional display sidecar YAML path.")
    parser.add_argument("--scenario", type=Path, help="Legacy scenario_config/*.yaml path.")
    parser.add_argument("--scenario-dir", type=Path, help="Legacy scenario_config directory to import as independent usecases.")
    parser.add_argument(
        "--scenario-group",
        type=Path,
        nargs="+",
        help="Legacy scenario YAML paths to group into one canonical scenario with multiple variants.",
    )
    parser.add_argument("--group-id", default="uc-camera-recording", help="Usecase ID for --scenario-group output.")
    parser.add_argument("--group-name", default="Camera Recording", help="Usecase display name for --scenario-group output.")
    parser.add_argument("--grouping-policy", type=Path, help="Optional YAML policy for scenario grouping guardrails.")
    parser.add_argument("--out", type=Path, required=True, help="Generated canonical YAML output directory.")
    parser.add_argument("--project", default="proj-legacy", help="Project ref used for generated IDs.")
    parser.add_argument("--project-name", default="Legacy Imported Project", help="Project display name for generated project YAML.")
    parser.add_argument("--soc", default="soc-legacy", help="SoC ref used by generated project YAML.")
    parser.add_argument("--schema-version", default="2.2", help="Canonical ScenarioDB schema version.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when conversion reports errors.")
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="With --strict, return non-zero when conversion reports warnings.",
    )
    parser.add_argument(
        "--skip-generated-validation",
        action="store_true",
        help="Do not validate generated canonical YAML against ScenarioDB models.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ImportReport()
    emitted_paths: list[Path] = []

    if not any((args.hw, args.sensor, args.display, args.scenario, args.scenario_dir, args.scenario_group)):
        report.error(
            "legacy_import_no_input",
            "At least one input must be provided: --hw, --sensor, --display, --scenario, --scenario-dir, or --scenario-group.",
        )

    if args.hw and not args.hw.exists():
        report.error("hw_file_not_found", f"HW config not found: {args.hw}", str(args.hw))
    elif args.hw:
        blocks = load_legacy_hw(args.hw, report)
        docs = convert_hw_catalog(
            blocks,
            project_ref=args.project,
            schema_version=args.schema_version,
            report=report,
        )
        emitted = emit_hw_catalog(args.out, docs)
        emitted_paths.extend(emitted)
        report.info("hw_catalog_emitted", f"Emitted {len(emitted)} HW catalog YAML files.", str(args.out))

    if args.sensor and not args.sensor.exists():
        report.error("sensor_file_not_found", f"Sensor config not found: {args.sensor}", str(args.sensor))
    elif args.sensor:
        sensors = load_legacy_sensor(args.sensor, report)
        docs = convert_sensor_catalog(
            sensors,
            project_ref=args.project,
            schema_version=args.schema_version,
            report=report,
        )
        emitted = emit_catalog(args.out, docs, "00_hw")
        emitted_paths.extend(emitted)
        report.info("sensor_catalog_emitted", f"Emitted {len(emitted)} sensor catalog YAML files.", str(args.out))

    if args.display and not args.display.exists():
        report.error("display_file_not_found", f"Display config not found: {args.display}", str(args.display))
    elif args.display:
        displays = load_legacy_display(args.display, report)
        docs = convert_display_catalog(
            displays,
            project_ref=args.project,
            schema_version=args.schema_version,
            report=report,
        )
        emitted = emit_catalog(args.out, docs, "00_hw")
        emitted_paths.extend(emitted)
        report.info("display_catalog_emitted", f"Emitted {len(emitted)} display catalog YAML files.", str(args.out))

    if args.scenario and not args.scenario.exists():
        report.error("scenario_file_not_found", f"Scenario config not found: {args.scenario}", str(args.scenario))
    elif args.scenario:
        emitted_paths.extend(_emit_project_stub(args, report))
        raw = load_legacy_scenario(args.scenario, report)
        doc = convert_scenario_usecase(
            raw,
            project_ref=args.project,
            schema_version=args.schema_version,
            report=report,
            source=str(args.scenario),
        )
        emitted = emit_catalog(args.out, [doc], "02_definition") if doc else []
        emitted_paths.extend(emitted)
        report.info("scenario_usecase_emitted", f"Emitted {len(emitted)} scenario usecase YAML files.", str(args.out))

    if args.scenario_dir and not args.scenario_dir.is_dir():
        report.error("scenario_dir_not_found", f"Scenario directory not found: {args.scenario_dir}", str(args.scenario_dir))
    elif args.scenario_dir:
        emitted_paths.extend(_emit_project_stub(args, report))
        emitted = _convert_scenario_dir(args, report)
        emitted_paths.extend(emitted)
        report.info("scenario_dir_emitted", f"Emitted {len(emitted)} scenario usecase YAML files.", str(args.out))

    if args.scenario_group:
        emitted_paths.extend(_emit_project_stub(args, report))
        grouping_policy = _load_grouping_policy(args.grouping_policy, report)
        scenarios = []
        for path in args.scenario_group:
            if not path.exists():
                report.error("scenario_file_not_found", f"Scenario config not found: {path}", str(path))
                continue
            scenarios.append((str(path), load_legacy_scenario(path, report)))
        doc = convert_scenario_group_usecase(
            scenarios,
            project_ref=args.project,
            schema_version=args.schema_version,
            report=report,
            group_id=args.group_id,
            group_name=args.group_name,
            grouping_policy=grouping_policy,
        )
        emitted = emit_catalog(args.out, [doc], "02_definition") if doc else []
        emitted_paths.extend(emitted)
        report.info("scenario_group_usecase_emitted", f"Emitted {len(emitted)} scenario group YAML files.", str(args.out))

    if emitted_paths and not args.skip_generated_validation:
        validate_generated_yaml(emitted_paths, report)

    report_path = args.out / "import_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2))
    has_warning = any(message.level == "warning" for message in report.messages)
    return 1 if args.strict and (not report.ok or (args.fail_on_warning and has_warning)) else 0


def _emit_project_stub(args: argparse.Namespace, report: ImportReport) -> list[Path]:
    project_doc = {
        "id": args.project,
        "schema_version": args.schema_version,
        "kind": "project",
        "metadata": {
            "name": args.project_name,
            "soc_ref": args.soc,
        },
    }
    emitted = emit_catalog(args.out, [project_doc], "02_definition")
    report.increment("project")
    return emitted


def _convert_scenario_dir(args: argparse.Namespace, report: ImportReport) -> list[Path]:
    emitted_paths: list[Path] = []
    scenario_paths = sorted(args.scenario_dir.glob("*.yaml"))
    if not scenario_paths:
        report.warning("scenario_dir_empty", "Scenario directory contains no *.yaml files.", str(args.scenario_dir))
        return emitted_paths

    for path in scenario_paths:
        raw = load_legacy_scenario(path, report)
        if not _looks_like_legacy_scenario(raw):
            report.warning(
                "scenario_file_skipped_unsupported",
                "Skipping YAML file that does not look like a legacy scenario definition.",
                str(path),
            )
            continue
        doc = convert_scenario_usecase(
            raw,
            project_ref=args.project,
            schema_version=args.schema_version,
            report=report,
            source=str(path),
        )
        emitted_paths.extend(emit_catalog(args.out, [doc], "02_definition") if doc else [])
    return emitted_paths


def _looks_like_legacy_scenario(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    return isinstance(raw.get("name"), str) and isinstance(raw.get("ip_blocks"), list)


def _load_grouping_policy(path: Path | None, report: ImportReport) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        report.error("grouping_policy_file_not_found", f"Grouping policy not found: {path}", str(path))
        return None
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        report.error("grouping_policy_not_object", "Grouping policy must be a YAML object.", str(path))
        return None
    return raw


if __name__ == "__main__":
    raise SystemExit(main())
