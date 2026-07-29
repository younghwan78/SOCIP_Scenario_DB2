from __future__ import annotations

import hashlib
import io
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
from datetime import datetime, timezone

from scenario_db.reporting.charts import generate_bw_chart_html, generate_timing_chart_html
from scenario_db.reporting.filenames import artifact_filenames, build_report_prefix
from scenario_db.reporting.html_report import generate_simulation_report_html
from scenario_db.reporting.models import (
    ArtifactKind,
    GeneratedReportBundle,
    ReportContext,
    WrittenArtifact,
    WrittenReportBundle,
)


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
    storage_root: str | Path | None = None,
    overwrite: bool = True,
) -> WrittenReportBundle:
    output_path = Path(output_dir).resolve()
    root_path = Path(storage_root).resolve() if storage_root is not None else output_path
    output_path.mkdir(parents=True, exist_ok=True)
    bundle = generate_report_bundle(evidence, context=context)
    names = artifact_filenames(bundle.prefix)
    created_at = datetime.now(timezone.utc).isoformat()
    generation_id = uuid4().hex
    prefix_dir = output_path / bundle.prefix
    if not overwrite and prefix_dir.exists() and any(prefix_dir.iterdir()):
        raise FileExistsError(f"Report artifact already exists: {prefix_dir}")
    prefix_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = output_path / f".scenariodb-staging-{generation_id}"
    generation_dir = prefix_dir / generation_id

    files: list[tuple[ArtifactKind, str, str | None]] = [
        ("timing_chart", names.timing_chart, bundle.timing_chart_html),
        ("bw_chart", names.bw_chart, bundle.bw_chart_html),
        ("simulation_report", names.simulation_report, bundle.simulation_report_html),
    ]
    artifacts: list[WrittenArtifact] = []
    try:
        staging_dir.mkdir()
        for artifact_type, filename, html in files:
            data = (html or "").encode("utf-8")
            staged_path = staging_dir / filename
            _durable_write(staged_path, data)
            final_path = generation_dir / filename
            artifacts.append(
                WrittenArtifact(
                    artifact_id=f"{generation_id}:{artifact_type}",
                    type=artifact_type,
                    storage="local_file",
                    path=final_path,
                    relative_path=_relative_storage_path(final_path, root_path),
                    sha256=hashlib.sha256(data).hexdigest(),
                    bytes=len(data),
                    created_at=created_at,
                    prefix=bundle.prefix,
                )
            )
        staging_dir.replace(generation_dir)
    except Exception:
        _remove_tree(staging_dir)
        _remove_tree(generation_dir)
        try:
            prefix_dir.rmdir()
        except OSError:
            pass
        raise
    return WrittenReportBundle(
        prefix=bundle.prefix,
        output_dir=generation_dir,
        relative_output_dir=_relative_storage_path(generation_dir, root_path),
        generation_id=generation_id,
        artifacts=artifacts,
    )


def cleanup_report_bundle(bundle: WrittenReportBundle) -> None:
    """Remove only the unique generation created by one export attempt."""

    generation_dir = bundle.output_dir.resolve()
    if generation_dir.name != bundle.generation_id:
        raise ValueError("Refusing to clean an artifact directory outside its generation")
    _remove_tree(generation_dir)
    prefix_dir = generation_dir.parent
    try:
        prefix_dir.rmdir()
    except OSError:
        pass


def cleanup_artifact_generations(
    report_root: str | Path,
    artifact_records: list[dict[str, Any]],
    *,
    replacement_types: set[str] | None = None,
) -> None:
    """Remove superseded generation directories with strict metadata checks."""

    root = Path(report_root).expanduser().resolve()
    generation_dirs: set[Path] = set()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in artifact_records:
        artifact_id = record.get("artifact_id")
        if isinstance(artifact_id, str) and ":" in artifact_id:
            grouped.setdefault(artifact_id.split(":", 1)[0], []).append(record)
    for generation_id, records in grouped.items():
        if replacement_types is not None and any(
            str(record.get("type")) not in replacement_types
            for record in records
        ):
            continue
        for record in records:
            _collect_generation_dir(root, generation_id, record, generation_dirs)
    for generation_dir in generation_dirs:
        _remove_tree(generation_dir)
        try:
            generation_dir.parent.rmdir()
        except OSError:
            pass


def _collect_generation_dir(
    root: Path,
    generation_id: str,
    record: dict[str, Any],
    generation_dirs: set[Path],
) -> None:
    artifact_id = record.get("artifact_id")
    if not isinstance(artifact_id, str) or artifact_id.split(":", 1)[0] != generation_id:
        return
    relative_path = record.get("path")
    if not isinstance(relative_path, str) or not relative_path:
        return
    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.parent.name != generation_id:
        return
    generation_dir = (root / candidate.parent).resolve()
    try:
        generation_dir.relative_to(root)
    except ValueError:
        return
    generation_dirs.add(generation_dir)


def build_report_zip_bytes(evidence: dict[str, Any], *, context: ReportContext) -> tuple[bytes, str]:
    bundle = generate_report_bundle(evidence, context=context)
    names = artifact_filenames(bundle.prefix)
    buffer = io.BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(names.timing_chart, bundle.timing_chart_html or "")
        archive.writestr(names.bw_chart, bundle.bw_chart_html or "")
        archive.writestr(names.simulation_report, bundle.simulation_report_html)
    return buffer.getvalue(), f"{bundle.prefix}_html_report_bundle.zip"


def resolve_report_output_dir(
    requested_output_dir: str | Path | None,
    *,
    base_dir: str | Path,
    allow_custom_dir: bool = False,
) -> Path:
    base = Path(base_dir).expanduser().resolve()
    if requested_output_dir is None or requested_output_dir == "":
        return base
    requested = Path(requested_output_dir).expanduser()
    target = requested.resolve() if requested.is_absolute() else (base / requested).resolve()
    if allow_custom_dir or _is_relative_to(target, base):
        return target
    raise ValueError(f"output_dir is outside report_dir: {target}")


def artifact_metadata(bundle: WrittenReportBundle) -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": artifact.artifact_id,
            "type": artifact.type,
            "storage": artifact.storage,
            "path": artifact.relative_path,
            "sha256": artifact.sha256,
            "bytes": artifact.bytes,
            "mime": artifact.mime,
            "created_at": artifact.created_at,
            "prefix": artifact.prefix,
            "generator": artifact.generator,
        }
        for artifact in bundle.artifacts
    ]


def _durable_write(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _relative_storage_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # Custom output roots are opt-in. Keep the identifier machine-neutral,
        # rooted at the requested custom directory rather than leaking it.
        return path.name if path.is_file() else f"{path.parent.name}/{path.name}"


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False
