"""CLI: convert a measurement capture (meta.yaml + power CSV + perfetto trace)
into canonical ``evidence.measurement`` YAML.

Example:

    uv run python -m scenario_db.meas_import.cli \
      --meta demo/measurements/uhd30-vdis/meta.yaml \
      --out generated/measurements \
      --strict
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from scenario_db.legacy_import.read_legacy import read_yaml, write_yaml
from scenario_db.legacy_import.report import ImportReport
from scenario_db.meas_import.assemble import assemble_evidence
from scenario_db.meas_import.bench_adapter import bench_files_to_rail_long, collect_bench_files
from scenario_db.meas_import.meta import MeasurementImportMeta
from scenario_db.meas_import.perfetto_digest import PerfettoDigest, PerfettoTraceProcessor, extract_digest
from scenario_db.meas_import.power_csv import (
    PowerCsvError,
    PowerDigest,
    aggregate_power,
    aggregate_power_rail_long,
)
from scenario_db.models.evidence.measurement import MeasurementEvidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a measurement capture into canonical evidence.measurement YAML.",
    )
    parser.add_argument("--meta", type=Path, required=True, help="meta.yaml describing the capture.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for generated YAML.")
    parser.add_argument(
        "--bench-in",
        type=Path,
        nargs="+",
        default=None,
        help=(
            "Per-run wide bench export files (or a directory of them). They are "
            "converted to the rail_long CSV named by meta.power.csv before "
            "aggregation, making a raw bench capture a one-command import. "
            "Requires power.format=rail_long."
        ),
    )
    parser.add_argument(
        "--skip-perfetto",
        action="store_true",
        help="Skip perfetto trace digest even when meta has a 'perfetto' section (power-only import).",
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
        help="Do not validate generated YAML against the MeasurementEvidence model.",
    )
    return parser


def _resolve(base_dir: Path, ref: str) -> Path:
    path = Path(ref)
    return path if path.is_absolute() else base_dir / path


def run_import(args: argparse.Namespace, report: ImportReport) -> dict | None:
    if not args.meta.exists():
        report.error("meta_file_not_found", f"meta.yaml not found: {args.meta}", str(args.meta))
        return None

    try:
        raw_meta = read_yaml(args.meta)
    except Exception as exc:  # noqa: BLE001 - defensive for malformed yaml
        report.error("meta_unreadable", f"Cannot read meta.yaml: {exc}", str(args.meta))
        return None

    try:
        meta = MeasurementImportMeta.model_validate(raw_meta)
    except ValidationError as exc:
        report.error("meta_schema_invalid", _fmt_validation(exc), str(args.meta))
        return None

    base_dir = args.meta.parent

    power: PowerDigest | None = None
    if args.bench_in and meta.power is None:
        report.error(
            "bench_requires_power_section",
            "--bench-in was given but meta.yaml has no 'power' section.",
            str(args.meta),
        )
    if meta.power is not None and args.bench_in:
        if meta.power.format != "rail_long":
            report.error(
                "bench_requires_rail_long",
                "--bench-in requires power.format=rail_long "
                f"(meta declares '{meta.power.format}').",
                str(args.meta),
            )
        else:
            bench_paths: list[Path] = []
            for target in args.bench_in:
                bench_paths.extend(collect_bench_files(target))
            bench_files_to_rail_long(
                bench_paths,
                _resolve(base_dir, meta.power.csv),
                report=report,
            )
    if meta.power is not None and report.ok:
        csv_path = _resolve(base_dir, meta.power.csv)
        if not csv_path.exists():
            report.error("power_csv_not_found", f"Power CSV not found: {csv_path}", str(csv_path))
        else:
            try:
                cl = meta.provenance.confidence_level
                if meta.power.format == "rail_long":
                    power = aggregate_power_rail_long(csv_path, meta.power, confidence_level=cl)
                    unit = "runs"
                else:
                    power = aggregate_power(csv_path, meta.power, confidence_level=cl)
                    unit = "samples"
                report.info(
                    "power_aggregated",
                    f"Aggregated {power.sample_count} power {unit} across {len(power.rail_kpi)} rails.",
                    str(csv_path),
                )
                report.increment("power_rails", len(power.rail_kpi))
            except PowerCsvError as exc:
                report.error("power_csv_invalid", str(exc), str(csv_path))

    perfetto: PerfettoDigest | None = None
    if meta.perfetto is not None and not args.skip_perfetto:
        trace_path = _resolve(base_dir, meta.perfetto.trace)
        if not trace_path.exists():
            report.warning(
                "perfetto_trace_not_found",
                f"Perfetto trace not found; skipping trace digest: {trace_path}",
                str(trace_path),
            )
        else:
            try:
                tp = PerfettoTraceProcessor(str(trace_path))
                try:
                    perfetto = extract_digest(tp, meta.perfetto)
                finally:
                    tp.close()
                report.info(
                    "perfetto_extracted",
                    f"Extracted {len(perfetto.freq_residency)} cluster residency sets, "
                    f"{len(perfetto.sw_task_timing)} task timings.",
                    str(trace_path),
                )
            except RuntimeError as exc:
                report.warning("perfetto_unavailable", str(exc), str(trace_path))
    elif meta.perfetto is not None and args.skip_perfetto:
        report.info("perfetto_skipped", "Perfetto digest skipped by --skip-perfetto.")

    if not report.ok:
        return None

    doc = assemble_evidence(meta, power, perfetto, base_dir=base_dir, report=report)

    if not args.skip_generated_validation:
        try:
            MeasurementEvidence.model_validate(doc)
            report.increment("validated_yaml")
        except ValidationError as exc:
            report.error("generated_yaml_schema_invalid", _fmt_validation(exc), doc.get("id"))
            return None

    return doc


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ImportReport()

    doc = run_import(args, report)
    if doc is not None:
        out_path = args.out / "03_evidence" / f"{doc['id']}.yaml"
        write_yaml(out_path, doc)
        report.increment("evidence_measurement")
        report.info("evidence_emitted", f"Emitted measurement evidence: {out_path}", str(out_path))

    report_path = args.out / "meas_import_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(report.to_dict(), indent=2))

    has_warning = any(m.level == "warning" for m in report.messages)
    return 1 if args.strict and (not report.ok or (args.fail_on_warning and has_warning)) else 0


def _fmt_validation(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", ())) or "<root>"
    return f"Validation failed at {loc}: {first.get('msg', str(exc))}"


if __name__ == "__main__":
    raise SystemExit(main())
