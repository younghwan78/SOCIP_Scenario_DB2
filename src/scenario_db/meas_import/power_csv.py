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
from statistics import fmean, pstdev

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


def aggregate_power(csv_path: Path, spec: PowerSpec, *, confidence_level: float | None = None) -> PowerDigest:
    rail_names, columns = _read_columns(csv_path, spec.time_column)
    digest = PowerDigest()
    digest.sample_count = max((len(v) for v in columns.values()), default=0)

    for rail in rail_names:
        values = columns[rail]
        if not values:
            continue
        digest.rail_kpi[rail] = measured_kpi(values, confidence_level=confidence_level)

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
            digest.cpu_cluster_power[cluster] = measured_kpi(summed, confidence_level=confidence_level)

    # total power
    if spec.total_power_column is not None:
        if spec.total_power_column not in columns:
            raise PowerCsvError(
                f"total_power_column '{spec.total_power_column}' is not a CSV column"
            )
        digest.total_power_mw = measured_kpi(columns[spec.total_power_column], confidence_level=confidence_level)
    elif spec.total_power_rails:
        summed = _per_sample_sum(columns, spec.total_power_rails)
        if summed:
            digest.total_power_mw = measured_kpi(summed, confidence_level=confidence_level)

    return digest


def _round(value: float, ndigits: int = 3) -> float:
    return round(value, ndigits)


def aggregate_power_rail_long(
    csv_path: Path, spec: PowerSpec, *, confidence_level: float | None = None
) -> PowerDigest:
    """Aggregate a real bench export: one row per (run, rail) with V/mA/mW.

    Statistics are taken *across runs* (sample size n = number of runs), the
    standard methodology of "measure N times, use the mean". Per-rail output
    carries the full triplet so callers can inspect current (primary metric)
    and verify the applied voltage, not just power.
    """
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        for required in (spec.run_column, spec.rail_column, spec.power_column):
            if required not in header:
                raise PowerCsvError(
                    f"rail_long column '{required}' not found in CSV header {header}"
                )
        has_v = spec.voltage_column in header
        has_i = spec.current_column in header

        # rail -> metric -> [values across runs]; rail_power_by_run aligns
        # cluster/total aggregation by run id, independent of CSV row order.
        rails: dict[str, dict[str, list[float]]] = {}
        rail_power_by_run: dict[str, dict[str, float]] = {}
        rail_order: list[str] = []
        run_order: list[str] = []
        run_rails: dict[str, set[str]] = {}
        for lineno, row in enumerate(reader, start=2):
            rail = (row.get(spec.rail_column) or "").strip()
            run = (row.get(spec.run_column) or "").strip()
            if not rail or not run:
                continue
            mw = _cell_float(row, spec.power_column, rail, lineno)
            if run not in run_rails:
                run_rails[run] = set()
                run_order.append(run)
            if rail in run_rails[run]:
                raise PowerCsvError(
                    f"duplicate rail_long row for run '{run}', rail '{rail}' at line {lineno}"
                )
            run_rails[run].add(rail)
            if rail not in rails:
                rails[rail] = {"v": [], "ma": [], "mw": []}
                rail_power_by_run[rail] = {}
                rail_order.append(rail)
            rail_power_by_run[rail][run] = mw
            rails[rail]["mw"].append(mw)
            if has_v:
                rails[rail]["v"].append(_cell_float(row, spec.voltage_column, rail, lineno))
            if has_i:
                rails[rail]["ma"].append(_cell_float(row, spec.current_column, rail, lineno))

    if not rail_order:
        raise PowerCsvError(f"rail_long CSV has no data rows: {csv_path}")

    missing_meta_rails = sorted(set(spec.rails) - set(rail_order))
    if missing_meta_rails:
        raise PowerCsvError(f"rails in meta.rails not present in rail_long CSV: {missing_meta_rails}")

    digest = PowerDigest()
    digest.sample_count = len(run_order)

    for rail in rail_order:
        mw_vals = rails[rail]["mw"]
        entry: dict = {"power_mw": _round(fmean(mw_vals))}
        if len(mw_vals) > 1:
            entry["std_mw"] = _round(pstdev(mw_vals))
        if rails[rail]["v"]:
            entry["voltage_v"] = _round(fmean(rails[rail]["v"]), 4)
        if rails[rail]["ma"]:
            entry["current_ma"] = _round(fmean(rails[rail]["ma"]))
        digest.vdd_power[rail] = entry
        digest.rail_kpi[rail] = measured_kpi(mw_vals, confidence_level=confidence_level)

    # cpu_breakdown: rails mapped to a cluster are summed per run, across runs.
    cluster_rails: dict[str, list[str]] = {}
    for rail, role in spec.rails.items():
        if role.role == "cpu_cluster" and rail in rails:
            cluster_rails.setdefault(role.cluster, []).append(rail)
    for cluster, members in cluster_rails.items():
        per_run = _required_run_totals(
            rail_power_by_run,
            run_order,
            members,
            context=f"cluster '{cluster}'",
        )
        if per_run:
            digest.cpu_cluster_power[cluster] = measured_kpi(per_run, confidence_level=confidence_level)

    total_rails = list(dict.fromkeys(spec.total_power_rails))
    if total_rails:
        missing_total_rails = [rail for rail in total_rails if rail not in rail_power_by_run]
        if missing_total_rails:
            raise PowerCsvError(
                f"total_power_rails not present in rail_long CSV: {missing_total_rails}"
            )
        run_totals = _required_run_totals(
            rail_power_by_run,
            run_order,
            total_rails,
            context="total_power_rails",
        )
    else:
        _ensure_consistent_run_rail_sets(run_rails, run_order)
        run_totals = [
            sum(rail_power_by_run[rail][run] for rail in run_rails[run])
            for run in run_order
        ]
    if run_totals:
        digest.total_power_mw = measured_kpi(run_totals, confidence_level=confidence_level)

    return digest


def _required_run_totals(
    rail_power_by_run: dict[str, dict[str, float]],
    run_order: list[str],
    required_rails: list[str],
    *,
    context: str,
) -> list[float]:
    """Sum required rails per run, failing if any run lacks a member rail."""
    missing_by_run: list[str] = []
    for run in run_order:
        missing = [rail for rail in required_rails if run not in rail_power_by_run.get(rail, {})]
        if missing:
            missing_by_run.append(f"run {run}: {', '.join(missing)}")
    if missing_by_run:
        raise PowerCsvError(
            f"rail_long missing required rails for {context}: {'; '.join(missing_by_run)}"
        )
    return [
        sum(rail_power_by_run[rail][run] for rail in required_rails)
        for run in run_order
    ]


def _ensure_consistent_run_rail_sets(run_rails: dict[str, set[str]], run_order: list[str]) -> None:
    """Require the same rail set per run when total_power_rails means all rails."""
    if not run_order:
        return
    expected = set(run_rails[run_order[0]])
    problems: list[str] = []
    for run in run_order[1:]:
        actual = run_rails[run]
        missing = sorted(expected - actual)
        added = sorted(actual - expected)
        if missing or added:
            parts = []
            if missing:
                parts.append(f"missing {', '.join(missing)}")
            if added:
                parts.append(f"added {', '.join(added)}")
            problems.append(f"run {run}: {'; '.join(parts)}")
    if problems:
        raise PowerCsvError(
            "rail_long rail set mismatch across runs; set total_power_rails "
            f"to a stable subset or fix CSV: {'; '.join(problems)}"
        )


def _cell_float(row: dict, column: str, rail: str, lineno: int) -> float:
    cell = (row.get(column) or "").strip()
    try:
        return float(cell)
    except ValueError as exc:
        raise PowerCsvError(
            f"non-numeric value '{cell}' for {column} of rail '{rail}' at line {lineno}"
        ) from exc
