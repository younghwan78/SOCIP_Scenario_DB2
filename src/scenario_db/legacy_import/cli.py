from __future__ import annotations

import argparse
import json
from pathlib import Path

from scenario_db.legacy_import.emit_canonical_yaml import emit_hw_catalog
from scenario_db.legacy_import.normalize_hw import convert_hw_catalog, load_legacy_hw
from scenario_db.legacy_import.report import ImportReport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert legacy simulation YAML into canonical ScenarioDB YAML.",
    )
    parser.add_argument("--hw", type=Path, required=True, help="Legacy projectA_hw.yaml path.")
    parser.add_argument("--out", type=Path, required=True, help="Generated canonical YAML output directory.")
    parser.add_argument("--project", default="proj-legacy", help="Project ref used for generated IDs.")
    parser.add_argument("--schema-version", default="2.2", help="Canonical ScenarioDB schema version.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when conversion reports errors.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ImportReport()

    if not args.hw.exists():
        report.error("hw_file_not_found", f"HW config not found: {args.hw}", str(args.hw))
    else:
        blocks = load_legacy_hw(args.hw, report)
        docs = convert_hw_catalog(
            blocks,
            project_ref=args.project,
            schema_version=args.schema_version,
            report=report,
        )
        emitted = emit_hw_catalog(args.out, docs)
        report.info("hw_catalog_emitted", f"Emitted {len(emitted)} HW catalog YAML files.", str(args.out))

    report_path = args.out / "import_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2))
    return 1 if args.strict and not report.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
