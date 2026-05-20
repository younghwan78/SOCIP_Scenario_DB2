from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from scenario_db.reporting.charts import generate_bw_chart_html, generate_timing_chart_html
from scenario_db.reporting.filenames import artifact_filenames, build_report_prefix
from scenario_db.reporting.html_report import generate_simulation_report_html
from scenario_db.reporting.models import GeneratedReportBundle, ReportContext, WrittenArtifact, WrittenReportBundle


def build_report_context(
    evidence: dict[str, Any],
    *,
    scenario_name: str | None = None,
    variant_name: str | None = None,
    project_ref: str | None = None,
    soc_ref: str | None = None,
) -> ReportContext:
    return ReportContext(
        evidence_id=str(evidence.get("id") or "simulation-evidence"),
        scenario_ref=str(evidence.get("scenario_ref") or ""),
        variant_ref=str(evidence.get("variant_ref") or ""),
        project_ref=project_ref or _optional_text(evidence.get("project_ref")),
        scenario_name=scenario_name,
        variant_name=variant_name,
        soc_ref=soc_ref,
    )


def generate_report_bundle(evidence: dict[str, Any], *, context: ReportContext) -> GeneratedReportBundle:
    prefix = build_report_prefix(context)
    names = artifact_filenames(prefix)
    title = context.variant_name or context.variant_ref or context.evidence_id
    timing_html = generate_timing_chart_html(evidence, title=title)
    bw_html = generate_bw_chart_html(evidence, title=f"{title} - Bandwidth Timeline")
    report_html = generate_simulation_report_html(
        evidence,
        context=context,
        timing_chart_file=names.timing_chart,
        bw_chart_file=names.bw_chart,
    )
    return GeneratedReportBundle(
        prefix=prefix,
        timing_chart_html=timing_html,
        bw_chart_html=bw_html,
        simulation_report_html=report_html,
    )


def write_report_bundle(
    evidence: dict[str, Any],
    *,
    context: ReportContext,
    output_dir: str | Path,
    overwrite: bool = True,
) -> WrittenReportBundle:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    bundle = generate_report_bundle(evidence, context=context)
    names = artifact_filenames(bundle.prefix)

    files = [
        ("timing_chart", output_path / names.timing_chart, bundle.timing_chart_html),
        ("bw_chart", output_path / names.bw_chart, bundle.bw_chart_html),
        ("simulation_report", output_path / names.simulation_report, bundle.simulation_report_html),
    ]
    if not overwrite:
        existing = [path for _, path, _ in files if path.exists()]
        if existing:
            raise FileExistsError(f"Report artifact already exists: {existing[0]}")

    artifacts = []
    for artifact_type, path, html in files:
        text = html or ""
        data = text.encode("utf-8")
        path.write_bytes(data)
        artifacts.append(
            WrittenArtifact(
                type=artifact_type,
                storage="local_file",
                path=path.resolve(),
                sha256=hashlib.sha256(data).hexdigest(),
                bytes=len(data),
            )
        )
    return WrittenReportBundle(prefix=bundle.prefix, output_dir=output_path.resolve(), artifacts=artifacts)


def artifact_metadata(bundle: WrittenReportBundle) -> list[dict[str, str]]:
    return [
        {
            "type": artifact.type,
            "storage": artifact.storage,
            "path": str(artifact.path),
            "sha256": artifact.sha256,
        }
        for artifact in bundle.artifacts
    ]


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
