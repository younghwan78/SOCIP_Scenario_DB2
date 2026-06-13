"""Power-monitor CSV parsing and aggregation.

The CSV is a per-sample waveform: one time column plus one column per power
rail (values in mW). We aggregate each rail over the capture into a
``MeasuredKpi``-shaped digest, and use the ``rails`` role map to produce:

- ``vdd_power``      : {rail: {mean_mw, p95_mw}} for rails with role == vdd
- ``cpu_cluster_power`` : {cluster: MeasuredKpi} summed per-sample within a cluster
- ``total_power_mw`` : MeasuredKpi from the per-sample sum of total_power_rails
                       (or directly from total_power_column)
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from scenario_db.meas_import.meta import PowerSpec
from scenario_db.meas_import.stats import measured_kpi


@dataclass(slots=True)
class PowerDigest:
    rail_kpi: dict[str, dict] = field(default_factory=dict)        # rail -> MeasuredKpi dict
    vdd_power: dict[str, dict] = field(default_factory=dict)       # rail -> {mean_mw, p95_mw}
    cpu_cluster_power: dict[str, dict] = field(default_factory=dict)  # cluster -> MeasuredKpi dict
    total_power_mw: dict | None = None                            # MeasuredKpi dict
    sample_count: int = 0


class PowerCsvError(ValueError):
    """Raised on structural problems in the power CSV / spec mismatch."""


def _read_columns(csv_path: Path, time_column: str) -> tuple[list[str], dict[str, list[float]]]:
    """Return (rail_names, {rail: [values...]}). The time column is dropped."""
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise PowerCsvError(f"power CSV is empty: {csv_path}") from exc
        header = [h.strip() for h in header]
        if time_column not in header:
            raise PowerCsvError(
                f"time column '{time_column}' not found in CSV header {header}"
            )
        rail_names = [h for h in header if h != time_column]
        idx = {name: header.index(name) for name in rail_names}
        columns: dict[str, list[float]] = {name: [] for name in rail_names}
        for lineno, row in enumerate(reader, start=2):
            if not row or all(c.strip() == "" for c in row):
                continue
            if len(row) < len(header):
                raise PowerCsvError(
                    f"malformed row at line {lineno}: expected {len(header)} columns, got {len(row)}"
                )
            for name in rail_names:
                cell = row[idx[name]].strip()
                if cell == "":
                    continue
                try:
                    columns[name].append(float(cell))
                except ValueError as exc:
                    raise PowerCsvError(
                        f"non-numeric value '{cell}' for rail '{name}' at line {lineno}"
                    ) from exc
    return rail_names, columns


def _per_sample_sum(columns: dict[str, list[float]], rails: list[str]) -> list[float]:
    missing = [r for r in rails if r not in columns]
    if missing:
        raise PowerCsvError(f"total_power_rails not present in CSV: {missing}")
    lengths = {len(columns[r]) for r in rails}
    if len(lengths) > 1:
        raise PowerCsvError(f"rail columns have differing sample counts: {lengths}")
    n = lengths.pop() if lengths else 0
    return [sum(columns[r][i] for r in rails) for i in range(n)]


def aggregate_power(csv_path: Path, spec: PowerSpec) -> PowerDigest:
    rail_names, columns = _read_columns(csv_path, spec.time_column)
    digest = PowerDigest()
    digest.sample_count = max((len(v) for v in columns.values()), default=0)

    for rail in rail_names:
        values = columns[rail]
        if not values:
            continue
        digest.rail_kpi[rail] = measured_kpi(values)

    # role-based mapping
    cluster_columns: dict[str, list[list[float]]] = {}
    for rail, role in spec.rails.items():
        if rail not in columns:
            raise PowerCsvError(f"rail '{rail}' in meta.rails is not a CSV column")
        if role.role == "vdd":
            kpi = digest.rail_kpi.get(rail)
            if kpi is not None:
                digest.vdd_power[rail] = {"mean_mw": kpi["mean"], "p95_mw": kpi["p95"]}
        elif role.role == "cpu_cluster":
            cluster_columns.setdefault(role.cluster, []).append(columns[rail])

    for cluster, col_list in cluster_columns.items():
        lengths = {len(c) for c in col_list}
        if len(lengths) > 1:
            raise PowerCsvError(
                f"cluster '{cluster}' rails have differing sample counts: {lengths}"
            )
        n = lengths.pop() if lengths else 0
        summed = [sum(col[i] for col in col_list) for i in range(n)]
        if summed:
            digest.cpu_cluster_power[cluster] = measured_kpi(summed)

    # total power
    if spec.total_power_column is not None:
        if spec.total_power_column not in columns:
            raise PowerCsvError(
                f"total_power_column '{spec.total_power_column}' is not a CSV column"
            )
        digest.total_power_mw = measured_kpi(columns[spec.total_power_column])
    elif spec.total_power_rails:
        summed = _per_sample_sum(columns, spec.total_power_rails)
        if summed:
            digest.total_power_mw = measured_kpi(summed)

    return digest
