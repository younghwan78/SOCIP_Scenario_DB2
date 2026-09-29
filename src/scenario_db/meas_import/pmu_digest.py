"""PMU digest importer (neutral sample format -> metric observations).

The in-house PMU/perfetto report format is not fixed yet, so the importer
defines a small *neutral* sample format that any report can be flattened
into (one row per sample). Adapters for a concrete report format only have to
produce these rows; everything downstream (catalog metrics, evidence
``metric_observations``, prediction/measurement comparison, the measured tier
of the clock ledger) already exists.

CSV (header required; ``#`` comment lines allowed)::

    metric,scope_kind,scope_ref,value,unit,stat,freq_mhz
    ip_clock_mhz,ip,MCSC,650,MHz,weighted_mean,
    ip_clock_residency,ip,MTNR,420,ms,,800
    mem_bw_read_mbs,mif,total,8100,MB/s,mean,
    cpu_cycles,cluster,big,1.2e9,count,sum,

JSON is the same rows: ``{"format": "scenariodb.pmu_digest", "version": 1,
"samples": [{...}]}`` or a bare list of row objects.

Source metrics (``metric`` column) and what they become:

=====================  ================  ================================  =========
source metric          scope_kind        catalog metric                    unit
=====================  ================  ================================  =========
``ip_clock_mhz``       ip                clock.ip (stats) / clock.ip_dominant  MHz
``ip_clock_residency`` ip                same, reduced from time-in-freq   (ratio)
``mem_bw_read_mbs``    mif, dram         bandwidth.mem_read (stats)        MB/s
``mem_bw_write_mbs``   mif, dram         bandwidth.mem_write (stats)       MB/s
``cpu_cycles``         cluster           cpu.cycles (value)                count
``cpu_instructions``   cluster           cpu.instructions (value)          count
``cpu_ipc``            cluster           cpu.ipc (value; derived if absent) ipc
=====================  ================  ================================  =========

``stat`` selects the statistic (``mean``/``weighted_mean``/``p50``/``p95``/
``min``/``max``/``dominant``; counters use ``sum``/``value``). ``ip_map`` /
``cluster_map`` in the meta ``pmu`` section translate PMU names (``MCSC``)
into catalog ids (``ip-mcsc-...``) so observations join with simulation
evidence; unmapped names are kept and reported as warnings.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scenario_db.meas_import.meta import PmuSpec
from scenario_db.models.evidence.metrics import validate_metric_observations

FORMAT_ID = "scenariodb.pmu_digest"
_REQUIRED_COLUMNS = ("metric", "scope_kind", "scope_ref", "value")
_STATS_FIELDS = {"mean", "p50", "p95", "p99", "min", "max", "std"}
_STAT_ALIASES = {"weighted_mean": "mean", "avg": "mean", "average": "mean", "median": "p50"}

_CLOCK_UNITS = {"mhz": 1.0, "ghz": 1000.0, "khz": 1e-3, "hz": 1e-6}
_BW_UNITS = {"mb/s": 1.0, "gb/s": 1000.0, "kb/s": 1e-3, "b/s": 1e-6}
_COUNT_UNITS = {"count": 1.0, "": 1.0}
_RATIO_UNITS = {"ipc": 1.0, "ratio": 1.0, "": 1.0}


class PmuDigestError(ValueError):
    """Raised on a malformed PMU sample file."""


@dataclass(slots=True)
class PmuSample:
    metric: str
    scope_kind: str
    scope_ref: str
    value: float
    unit: str = ""
    stat: str = ""
    freq_mhz: float | None = None
    line: int | None = None


@dataclass(slots=True)
class PmuDigest:
    observations: list[dict] = field(default_factory=list)
    sample_count: int = 0
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- reading
def read_pmu_samples(path: Path, fmt: str | None = None) -> list[PmuSample]:
    fmt = fmt or ("json" if path.suffix.lower() == ".json" else "csv")
    if fmt == "json":
        return _read_json(path)
    return _read_csv(path)


def _read_csv(path: Path) -> list[PmuSample]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        lines = [line for line in fh if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise PmuDigestError(f"PMU digest is empty: {path}")
    reader = csv.DictReader(lines)
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in _REQUIRED_COLUMNS if c not in header]
    if missing:
        raise PmuDigestError(f"PMU digest is missing columns {missing}; got {header}")
    samples = []
    for row in reader:
        clean = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}
        samples.append(_sample_from_row(clean, reader.line_num))
    return samples


def _read_json(path: Path) -> list[PmuSample]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PmuDigestError(f"PMU digest is not valid JSON: {exc}") from exc
    if isinstance(raw, dict):
        if raw.get("format") not in (None, FORMAT_ID):
            raise PmuDigestError(f"unsupported PMU digest format '{raw.get('format')}'")
        rows = raw.get("samples")
    else:
        rows = raw
    if not isinstance(rows, list) or not rows:
        raise PmuDigestError("PMU digest JSON needs a non-empty 'samples' list")
    return [
        _sample_from_row({k: "" if v is None else str(v) for k, v in row.items()}, index)
        for index, row in enumerate(rows, start=1)
        if isinstance(row, dict)
    ]


def _sample_from_row(row: dict[str, str], line: int) -> PmuSample:
    for column in _REQUIRED_COLUMNS:
        if not row.get(column):
            raise PmuDigestError(f"row {line}: '{column}' is required")
    try:
        value = float(row["value"])
    except ValueError as exc:
        raise PmuDigestError(f"row {line}: value '{row['value']}' is not a number") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise PmuDigestError(f"row {line}: value must be finite")
    freq: float | None = None
    if row.get("freq_mhz"):
        try:
            freq = float(row["freq_mhz"])
        except ValueError as exc:
            raise PmuDigestError(f"row {line}: freq_mhz '{row['freq_mhz']}' is not a number") from exc
    return PmuSample(
        metric=row["metric"].lower(),
        scope_kind=row["scope_kind"].lower(),
        scope_ref=row["scope_ref"],
        value=value,
        unit=row.get("unit", ""),
        stat=row.get("stat", "").lower(),
        freq_mhz=freq,
        line=line,
    )


# ------------------------------------------------------------------- reduction
def build_pmu_digest(
    samples: list[PmuSample],
    *,
    ip_map: dict[str, str] | None = None,
    cluster_map: dict[str, str] | None = None,
) -> PmuDigest:
    """Reduce neutral samples to canonical metric observations (validated against the catalog)."""
    ip_map = ip_map or {}
    cluster_map = cluster_map or {}
    digest = PmuDigest(sample_count=len(samples))
    clock_stats: dict[str, dict[str, float]] = {}
    clock_dominant: dict[str, float] = {}
    residency: dict[str, dict[float, float]] = {}
    bw: dict[tuple[str, str, str], dict[str, float]] = {}
    counters: dict[tuple[str, str], float] = {}
    seen: set[tuple[str, str, str, str, float | None]] = set()
    unmapped: set[str] = set()

    def scope_ref(sample: PmuSample) -> str:
        table = cluster_map if sample.scope_kind == "cluster" else ip_map if sample.scope_kind == "ip" else None
        if table is None:
            return sample.scope_ref
        if sample.scope_ref not in table:
            unmapped.add(f"{sample.scope_kind}:{sample.scope_ref}")
            return sample.scope_ref
        return table[sample.scope_ref]

    for sample in samples:
        key = (sample.metric, sample.scope_kind, sample.scope_ref, sample.stat, sample.freq_mhz)
        if key in seen:
            raise PmuDigestError(
                f"row {sample.line}: duplicate sample {sample.metric}/{sample.scope_kind}/{sample.scope_ref}"
                + (f"/{sample.stat}" if sample.stat else "")
            )
        seen.add(key)
        ref = scope_ref(sample)

        if sample.metric == "ip_clock_residency":
            _require_scope(sample, {"ip"})
            if sample.freq_mhz is None or sample.freq_mhz <= 0:
                raise PmuDigestError(f"row {sample.line}: ip_clock_residency needs freq_mhz > 0")
            if sample.value < 0:
                raise PmuDigestError(f"row {sample.line}: residency must be >= 0")
            residency.setdefault(ref, {})[sample.freq_mhz] = sample.value
        elif sample.metric == "ip_clock_mhz":
            _require_scope(sample, {"ip"})
            mhz = sample.value * _unit_factor(sample, _CLOCK_UNITS, "MHz")
            if mhz <= 0:
                raise PmuDigestError(f"row {sample.line}: clock must be positive")
            stat = _STAT_ALIASES.get(sample.stat, sample.stat) or "mean"
            if stat == "dominant":
                clock_dominant[ref] = mhz
            elif stat in _STATS_FIELDS:
                clock_stats.setdefault(ref, {})[stat] = mhz
            else:
                raise PmuDigestError(f"row {sample.line}: unsupported ip_clock_mhz stat '{sample.stat}'")
        elif sample.metric in ("mem_bw_read_mbs", "mem_bw_write_mbs"):
            _require_scope(sample, {"mif", "dram"})
            mbs = sample.value * _unit_factor(sample, _BW_UNITS, "MB/s")
            if mbs < 0:
                raise PmuDigestError(f"row {sample.line}: bandwidth must be >= 0")
            stat = _STAT_ALIASES.get(sample.stat, sample.stat) or "mean"
            if stat == "value":
                stat = "mean"
            if stat not in _STATS_FIELDS:
                raise PmuDigestError(f"row {sample.line}: unsupported bandwidth stat '{sample.stat}'")
            direction = "read" if sample.metric.endswith("read_mbs") else "write"
            bw.setdefault((f"bandwidth.mem_{direction}", sample.scope_kind, ref), {})[stat] = mbs
        elif sample.metric in ("cpu_cycles", "cpu_instructions", "cpu_ipc"):
            _require_scope(sample, {"cluster"})
            if sample.stat not in ("", "sum", "value", "mean"):
                raise PmuDigestError(f"row {sample.line}: unsupported counter stat '{sample.stat}'")
            factor = _unit_factor(sample, _RATIO_UNITS if sample.metric == "cpu_ipc" else _COUNT_UNITS, "count")
            if sample.value < 0:
                raise PmuDigestError(f"row {sample.line}: counter must be >= 0")
            counters[(sample.metric, ref)] = sample.value * factor
        else:
            digest.warnings.append(f"row {sample.line}: unknown PMU metric '{sample.metric}' skipped")

    for ref, levels in residency.items():
        derived = _residency_stats(levels)
        if derived is None:
            digest.warnings.append(f"ip {ref}: clock residency is all zero; skipped")
            continue
        stats, dominant = derived
        for name, value in stats.items():
            clock_stats.setdefault(ref, {}).setdefault(name, value)  # explicit rows win
        clock_dominant.setdefault(ref, dominant)

    for ref in sorted(clock_stats):
        digest.observations.append(_stats_obs("clock.ip", "ip", ref, "MHz", clock_stats[ref]))
    for ref in sorted(clock_dominant):
        digest.observations.append(_value_obs("clock.ip_dominant", "ip", ref, "MHz", clock_dominant[ref]))
    for (metric_id, kind, ref), stats in sorted(bw.items()):
        digest.observations.append(_stats_obs(metric_id, kind, ref, "MB/s", stats))
    for metric, obs_id, unit in (
        ("cpu_cycles", "cpu.cycles", "count"),
        ("cpu_instructions", "cpu.instructions", "count"),
    ):
        for (name, ref), value in sorted(counters.items()):
            if name == metric:
                digest.observations.append(_value_obs(obs_id, "cluster", ref, unit, value))
    clusters = {ref for (_, ref) in counters}
    for ref in sorted(clusters):
        explicit = counters.get(("cpu_ipc", ref))
        cycles = counters.get(("cpu_cycles", ref))
        instructions = counters.get(("cpu_instructions", ref))
        if explicit is not None:
            ipc: float | None = explicit
        elif cycles and instructions is not None:
            ipc = instructions / cycles
        else:
            ipc = None
        if ipc is not None:
            digest.observations.append(_value_obs("cpu.ipc", "cluster", ref, "ipc", round(ipc, 6)))

    if unmapped:
        digest.warnings.append(
            "PMU names without ip_map/cluster_map entry (kept as-is, will not join simulation "
            f"evidence): {sorted(unmapped)}"
        )
    try:
        validate_metric_observations_dicts(digest.observations)
    except ValueError as exc:
        raise PmuDigestError(str(exc)) from exc
    return digest


def import_pmu_digest(path: Path, spec: PmuSpec | None = None) -> PmuDigest:
    """Read + reduce a PMU sample file using the meta ``pmu`` section."""
    spec = spec or PmuSpec(file=str(path))
    samples = read_pmu_samples(path, spec.format)
    return build_pmu_digest(samples, ip_map=spec.ip_map, cluster_map=spec.cluster_map)


def validate_metric_observations_dicts(observations: list[dict]) -> None:
    from scenario_db.models.evidence.metrics import MetricObservation

    validate_metric_observations([MetricObservation.model_validate(item) for item in observations])


# --------------------------------------------------------------------- helpers
def _require_scope(sample: PmuSample, allowed: set[str]) -> None:
    if sample.scope_kind not in allowed:
        raise PmuDigestError(
            f"row {sample.line}: {sample.metric} needs scope_kind in {sorted(allowed)}, "
            f"got '{sample.scope_kind}'"
        )


def _unit_factor(sample: PmuSample, table: dict[str, float], canonical: str) -> float:
    factor = table.get(sample.unit.lower())
    if factor is None:
        raise PmuDigestError(
            f"row {sample.line}: unit '{sample.unit}' is not valid for {sample.metric} "
            f"(use {canonical} or one of {sorted(k for k in table if k)})"
        )
    return factor


def _residency_stats(levels: dict[float, float]) -> tuple[dict[str, float], float] | None:
    total = sum(levels.values())
    if total <= 0:
        return None
    active = sorted((f, r) for f, r in levels.items() if r > 0)
    mean = sum(f * r for f, r in active) / total
    dominant = max(active, key=lambda item: (item[1], item[0]))[0]
    cumulative = 0.0
    median = active[-1][0]
    for freq, amount in active:
        cumulative += amount
        if cumulative >= total / 2:
            median = freq
            break
    return (
        {"mean": round(mean, 6), "p50": median, "min": active[0][0], "max": active[-1][0]},
        dominant,
    )


def _stats_obs(metric_id: str, kind: str, ref: str, unit: str, stats: dict[str, float]) -> dict:
    return {"metric_id": metric_id, "scope": {"kind": kind, "ref": ref}, "unit": unit, "stats": dict(stats)}


def _value_obs(metric_id: str, kind: str, ref: str, unit: str, value: float) -> dict:
    return {"metric_id": metric_id, "scope": {"kind": kind, "ref": ref}, "unit": unit, "value": value}


# ------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    """Flatten a neutral PMU digest into metric observations (for inspection / meta.yaml use)."""
    parser = argparse.ArgumentParser(
        prog="python -m scenario_db.meas_import.pmu_digest",
        description="Validate a neutral PMU sample file and print the metric observations it yields.",
    )
    parser.add_argument("file", type=Path)
    parser.add_argument("--format", choices=["csv", "json"], default=None)
    parser.add_argument("--ip-map", action="append", default=[], metavar="PMU_NAME=ip-catalog-id")
    parser.add_argument("--cluster-map", action="append", default=[], metavar="PMU_NAME=cluster")
    args = parser.parse_args(argv)
    try:
        spec = PmuSpec(
            file=str(args.file),
            format=args.format or ("json" if args.file.suffix.lower() == ".json" else "csv"),
            ip_map=dict(item.split("=", 1) for item in args.ip_map),
            cluster_map=dict(item.split("=", 1) for item in args.cluster_map),
        )
        digest = import_pmu_digest(args.file, spec)
    except (PmuDigestError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "samples": digest.sample_count,
                "observations": digest.observations,
                "warnings": digest.warnings,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
