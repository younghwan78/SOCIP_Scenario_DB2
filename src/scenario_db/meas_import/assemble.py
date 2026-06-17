"""Assemble meta + power digest + perfetto digest into canonical
``evidence.measurement`` YAML.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from scenario_db.legacy_import.report import ImportReport
from scenario_db.meas_import.meta import MeasurementImportMeta
from scenario_db.meas_import.perfetto_digest import PerfettoDigest
from scenario_db.meas_import.power_csv import PowerDigest

_SLUG_RE = re.compile(r"[^a-zA-Z0-9.]+")


def generate_evidence_id(meta: MeasurementImportMeta) -> str:
    timestamp = _timestamp_suffix(meta.measured_at)
    scenario = _slug(meta.scenario_ref)
    variant = _slug(meta.variant_ref)
    rev = _slug(meta.execution_context.silicon_rev)
    parts = ["meas", scenario, variant, rev, timestamp]
    return "-".join(p for p in parts if p)


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value).strip("-")


def _timestamp_suffix(value: str) -> str:
    has_time = "T" in value or " " in value
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return value[:10].replace("-", "")
    if not has_time:
        return dt.strftime("%Y%m%d")
    return dt.strftime("%Y%m%dT%H%M%S")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_artifacts(meta: MeasurementImportMeta, base_dir: Path, report: ImportReport) -> list[dict]:
    artifacts: list[dict] = []
    for spec in meta.artifacts:
        art: dict = {"type": spec.type, "storage": spec.storage, "path": spec.path}
        if spec.mime:
            art["mime"] = spec.mime
        source = spec.source or spec.path
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = base_dir / source_path
        if source_path.exists() and source_path.is_file():
            art["sha256"] = _sha256(source_path)
            art["bytes"] = source_path.stat().st_size
        else:
            report.warning(
                "artifact_source_missing",
                f"Artifact source not found; emitting pointer without sha256/bytes: {source_path}",
                str(source_path),
            )
        artifacts.append(art)
    return artifacts


def build_cpu_breakdown(power: PowerDigest | None, perfetto: PerfettoDigest | None) -> list[dict]:
    clusters: list[str] = []
    if power is not None:
        clusters.extend(power.cpu_cluster_power)
    if perfetto is not None:
        for c in perfetto.freq_residency:
            if c not in clusters:
                clusters.append(c)

    out: list[dict] = []
    for cluster in clusters:
        entry: dict = {"cluster": cluster}
        if power is not None and cluster in power.cpu_cluster_power:
            entry["power_mw"] = power.cpu_cluster_power[cluster]
        if perfetto is not None:
            if cluster in perfetto.cluster_avg_freq:
                entry["avg_freq_mhz"] = perfetto.cluster_avg_freq[cluster]
            if cluster in perfetto.freq_residency:
                entry["freq_residency"] = perfetto.freq_residency[cluster]
        out.append(entry)
    return out


def assemble_evidence(
    meta: MeasurementImportMeta,
    power: PowerDigest | None,
    perfetto: PerfettoDigest | None,
    *,
    base_dir: Path,
    report: ImportReport,
) -> dict:
    doc: dict = {
        "id": meta.id or generate_evidence_id(meta),
        "schema_version": meta.schema_version,
        "kind": "evidence.measurement",
        "scenario_ref": meta.scenario_ref,
        "variant_ref": meta.variant_ref,
        "project_ref": meta.project_ref,
        "measured_at": meta.measured_at,
        "execution_context": meta.execution_context.model_dump(exclude_none=True),
        "provenance": meta.provenance.model_dump(exclude_none=True),
        "aggregation": {"strategy": meta.aggregation_strategy},
    }

    # KPI: meta passthrough first, then power-derived total unless meta set it.
    kpi: dict = dict(meta.kpi)
    if power is not None and power.total_power_mw is not None and "total_power_mw" not in kpi:
        kpi["total_power_mw"] = power.total_power_mw
    if kpi:
        doc["kpi"] = kpi

    cpu_breakdown = build_cpu_breakdown(power, perfetto)
    if cpu_breakdown:
        doc["cpu_breakdown"] = cpu_breakdown

    if perfetto is not None and perfetto.sw_task_timing:
        doc["sw_task_timing"] = perfetto.sw_task_timing

    if power is not None and power.vdd_power:
        doc["vdd_power"] = power.vdd_power

    artifacts = build_artifacts(meta, base_dir, report)
    if artifacts:
        doc["artifacts"] = artifacts

    return doc
