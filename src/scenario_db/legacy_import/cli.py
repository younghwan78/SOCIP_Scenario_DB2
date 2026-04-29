from __future__ import annotations

import argparse
import json
from pathlib import Path

from scenario_db.legacy_import.emit_canonical_yaml import emit_catalog, emit_hw_catalog
from scenario_db.legacy_import.normalize_display import convert_display_catalog, load_legacy_display
from scenario_db.legacy_import.normalize_hw import convert_hw_catalog, load_legacy_hw
from scenario_db.legacy_import.normalize_scenario import convert_scenario_usecase, load_legacy_scenario
from scenario_db.legacy_import.normalize_sensor import convert_sensor_catalog, load_legacy_sensor
from scenario_db.legacy_import.report import ImportReport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert legacy simulation YAML into canonical ScenarioDB YAML.",
    )
    parser.add_argument("--hw", type=Path, help="Legacy projectA_hw.yaml path.")
    parser.add_argument("--sensor", type=Path, help="Legacy sensor_config.yaml path.")
    parser.add_argument("--display", type=Path, help="Optional display sidecar YAML path.")
    parser.add_argument("--scenario", type=Path, help="Legacy scenario_config/*.yaml path.")
    parser.add_argument("--out", type=Path, required=True, help="Generated canonical YAML output directory.")
    parser.add_argument("--project", default="proj-legacy", help="Project ref used for generated IDs.")
    parser.add_argument("--project-name", default="Legacy Imported Project", help="Project display name for generated project YAML.")
    parser.add_argument("--soc", default="soc-legacy", help="SoC ref used by generated project YAML.")
    parser.add_argument("--schema-version", default="2.2", help="Canonical ScenarioDB schema version.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when conversion reports errors.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ImportReport()

    if not any((args.hw, args.sensor, args.display, args.scenario)):
        report.error(
            "legacy_import_no_input",
            "At least one input must be provided: --hw, --sensor, --display, or --scenario.",
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
        report.info("display_catalog_emitted", f"Emitted {len(emitted)} display catalog YAML files.", str(args.out))

    if args.scenario and not args.scenario.exists():
        report.error("scenario_file_not_found", f"Scenario config not found: {args.scenario}", str(args.scenario))
    elif args.scenario:
        project_doc = {
            "id": args.project,
            "schema_version": args.schema_version,
            "kind": "project",
            "metadata": {
                "name": args.project_name,
                "soc_ref": args.soc,
            },
        }
        emit_catalog(args.out, [project_doc], "02_definition")
        report.increment("project")
        raw = load_legacy_scenario(args.scenario, report)
        doc = convert_scenario_usecase(
            raw,
            project_ref=args.project,
            schema_version=args.schema_version,
            report=report,
            source=str(args.scenario),
        )
        emitted = emit_catalog(args.out, [doc], "02_definition") if doc else []
        report.info("scenario_usecase_emitted", f"Emitted {len(emitted)} scenario usecase YAML files.", str(args.out))

    report_path = args.out / "import_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2))
    return 1 if args.strict and not report.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
