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
``ip_clock_residency`` ip                same, reduced from time-in-freq,   (ratio)
                                         plus clock.ip_residency per level
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

Several physical instances of one IP (``MCSC0``, ``MCSC1``) must map to
instance-qualified ids (``ip-mcsc-...#0`` / ``#1``) or to scenario node ids;
mapping two PMU names onto one id is rejected instead of letting the last row
silently overwrite the first.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scenario_db.meas_import import clock_residency
from scenario_db.meas_import.meta import PmuSpec
from scenario_db.meas_import.table_adapter import table_samples
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
    group: str = ""                   # capture part (PMU pass) — residency only, see clock_residency


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
        group=row.get("group", ""),
    )


# ------------------------------------------------------------------- reduction
def build_pmu_digest(
    samples: list[PmuSample],
    *,
    ip_map: dict[str, str] | None = None,
    cluster_map: dict[str, str] | None = None,
    cpu_map: dict[str, str] | None = None,
    frames: float | None = None,
) -> PmuDigest:
    """Reduce neutral samples to canonical metric observations (validated against the catalog)."""
    ip_map = ip_map or {}
    cluster_map = cluster_map or {}
    digest = PmuDigest(sample_count=len(samples))
    cpu_samples: list[PmuSample] = []
    clock_samples: list[PmuSample] = []
    profile_requested = False
    clock_stats: dict[str, dict[str, float]] = {}
    clock_dominant: dict[str, float] = {}
    residency: dict[str, dict[float, float]] = {}
    bw: dict[tuple[str, str, str], dict[str, float]] = {}
    counters: dict[tuple[str, str], float] = {}
    seen: set[tuple[str, str, str, str, float | None, str]] = set()
    unmapped: set[str] = set()
    sources_by_target: dict[tuple[str, str], set[str]] = {}

    def scope_ref(sample: PmuSample) -> str:
        table = cluster_map if sample.scope_kind == "cluster" else ip_map if sample.scope_kind == "ip" else None
        if table is None:
            return sample.scope_ref
        if sample.scope_ref not in table:
            unmapped.add(f"{sample.scope_kind}:{sample.scope_ref}")
            target = sample.scope_ref
        else:
            target = table[sample.scope_ref]
        sources = sources_by_target.setdefault((sample.scope_kind, target), set())
        sources.add(sample.scope_ref)
        if len(sources) > 1:
            raise PmuDigestError(
                f"row {sample.line}: {sample.scope_kind} names {sorted(sources)} all map to '{target}'; "
                "map each HW instance to its own id (e.g. '<ip-id>#0', '<ip-id>#1' or a node id)"
            )
        return target

    for sample in samples:
        if not math.isfinite(sample.value):
            raise PmuDigestError(f"row {sample.line}: value must be finite")
        key = (sample.metric, sample.scope_kind, sample.scope_ref, sample.stat, sample.freq_mhz, sample.group)
        if key in seen:
            raise PmuDigestError(
                f"row {sample.line}: duplicate sample {sample.metric}/{sample.scope_kind}/{sample.scope_ref}"
                + (f"/{sample.stat}" if sample.stat else "")
            )
        seen.add(key)
        if clock_residency.observes(sample.metric):
            clock_samples.append(sample)
            if clock_residency.handles(sample.metric):
                continue
        profile_row = sample.metric in CPU_PROFILE_METRICS or (
            sample.metric in ("cpu_cycles", "cpu_instructions") and sample.scope_kind != "cluster"
        )
        if profile_row:
            cpu_samples.append(sample)
            profile_requested = True
            continue
        if sample.metric in ("cpu_cycles", "cpu_instructions"):
            cpu_samples.append(sample)  # cluster totals also feed the per-frame profile
        ref = scope_ref(sample)

        if sample.metric == "ip_clock_residency":
            _require_scope(sample, {"ip"})
            if sample.freq_mhz is None or not math.isfinite(sample.freq_mhz) or sample.freq_mhz <= 0:
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
    for ref in sorted(residency):
        total = sum(residency[ref].values())
        if total <= 0:
            continue
        for mhz, amount in sorted(residency[ref].items()):
            if amount > 0:
                digest.observations.append(
                    _value_obs("clock.ip_residency", "ip_freq", f"{ref}@{mhz:g}", "ratio", round(amount / total, 6))
                )
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

    if cpu_samples:
        _reduce_cpu_profile(cpu_samples, cluster_map=cluster_map, cpu_map=cpu_map or {}, frames=frames,
                            digest=digest, warn_without_window=profile_requested)
    if clock_samples:
        try:
            digest.observations.extend(clock_residency.reduce_samples(
                clock_samples, cpu_map=expand_cpu_map(cpu_map or {}), cluster_map=cluster_map, warnings=digest.warnings))
        except ValueError as exc:
            raise PmuDigestError(str(exc)) from exc
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


def import_pmu_digest(
    path: Path,
    spec: PmuSpec | None = None,
    *,
    cpu_map: dict[str, str] | None = None,
) -> PmuDigest:
    """Read + reduce PMU input using the meta ``pmu`` section.

    ``path``: the neutral file, or (``format: table``) the directory the table
    sources are relative to. ``cpu_map`` is the fallback CPU -> cluster map.
    """
    spec = spec or PmuSpec(file=str(path))
    warnings: list[str] = []
    if spec.format == "table":
        assert spec.table is not None
        base = path if path.is_dir() else path.parent
        try:
            rows = table_samples(base, spec.table, warnings)
        except (OSError, ValueError, KeyError) as exc:
            raise PmuDigestError(f"table source: {exc}") from exc
        samples = [
            PmuSample(metric=r["metric"], scope_kind=r["scope_kind"], scope_ref=r["scope_ref"],
                      value=float(r["value"]), freq_mhz=r["freq_mhz"], line=index, group=r.get("group") or "")
            for index, r in enumerate(rows, start=1)
        ]
    else:
        samples = read_pmu_samples(path, spec.format)
    frames = spec.window.frame_count() if spec.window else None
    digest = build_pmu_digest(
        samples, ip_map=spec.ip_map, cluster_map=spec.cluster_map,
        cpu_map=spec.cpu_map or cpu_map or {}, frames=frames,
    )
    digest.warnings[:0] = warnings
    return digest


# --------------------------------------------------------- per-frame CPU profile
CPU_PROFILE_METRICS = frozenset({
    "cpu_stall_cycles", "cpu_bus_bytes", "cpu_freq_time", "cpu_thread_cycles",
    "cpu_time_active", "cpu_time_clock_gated", "cpu_time_power_gated",
})
_PF_METRIC = {
    "cycles": ("cpu.cycles_pf", "count"),
    "instructions": ("cpu.instructions_pf", "count"),
    "stall_cycles": ("cpu.stall_cycles_pf", "count"),
    "bus_bytes": ("cpu.bus_bytes_pf", "bytes"),
}


def expand_cpu_map(cpu_map: dict[str, str] | dict[int, str]) -> dict[int, str]:
    """{"0-3": "MID_LF", "8": "BIG"} -> {0: .., 1: .., 2: .., 3: .., 8: ..}."""
    out: dict[int, str] = {}
    for key, cluster in cpu_map.items():
        text = str(key).strip()
        for part in text.split(","):
            part = part.strip()
            if "-" in part:
                low, high = (int(x) for x in part.split("-", 1))
                out.update({cpu: cluster for cpu in range(low, high + 1)})
            elif part:
                out[int(part)] = cluster
    return out


def _reduce_cpu_profile(
    samples: list[PmuSample],
    *,
    cluster_map: dict[str, str],
    cpu_map: dict[str, str],
    frames: float | None,
    digest: PmuDigest,
    warn_without_window: bool = True,
) -> None:
    """Per-frame counters per task x cluster, cluster frequency residency and gating ratios."""
    if frames is not None and (not math.isfinite(frames) or frames <= 0):
        raise PmuDigestError("CPU profile frame count must be finite and positive")
    cpus = expand_cpu_map(cpu_map)
    counters: dict[tuple[str | None, str, str], float] = {}
    freq: dict[tuple[str, float], float] = {}
    states: dict[tuple[str, str], float] = {}
    thread_cycles: dict[tuple[str, str, str], float] = {}
    missing: set[str] = set()
    for sample in samples:
        kind = sample.scope_kind
        task, place = (None, sample.scope_ref)
        thread: str | None = None
        if kind in ("task_thread_cpu", "task_thread_cluster"):
            # scope_ref "<task>#<thread>@<cpu|cluster>"
            head, _, place = sample.scope_ref.rpartition("@")
            task, _, thread = head.partition("#")
            if not task or not thread:
                raise PmuDigestError(f"row {sample.line}: {kind} scope_ref must be '<task>#<thread>@<cpu|cluster>'")
            kind = kind.replace("task_thread_", "task_")
        elif kind in ("task_cpu", "task_cluster"):
            task, _, place = sample.scope_ref.rpartition("@")
            if not task:
                raise PmuDigestError(f"row {sample.line}: {kind} scope_ref must be '<task>@<cpu|cluster>'")
        if kind in ("cpu", "task_cpu"):
            digits = "".join(ch for ch in place if ch.isdigit())
            cluster = cpus.get(int(digits)) if digits else None
            if cluster is None:
                missing.add(place)
                continue
        elif kind in ("cluster", "task_cluster"):
            cluster = cluster_map.get(place, place)
        else:
            raise PmuDigestError(f"row {sample.line}: {sample.metric} needs scope cpu/cluster/task_cpu/task_cluster")
        if sample.value < 0:
            raise PmuDigestError(f"row {sample.line}: {sample.metric} must be >= 0")
        if sample.metric == "cpu_thread_cycles":
            if task is None or thread is None:
                raise PmuDigestError(f"row {sample.line}: cpu_thread_cycles needs scope task_thread_cpu/task_thread_cluster")
            tkey = (task, cluster, thread)
            thread_cycles[tkey] = thread_cycles.get(tkey, 0.0) + sample.value
        elif sample.metric == "cpu_freq_time":
            if not sample.freq_mhz or not math.isfinite(sample.freq_mhz) or sample.freq_mhz <= 0:
                raise PmuDigestError(f"row {sample.line}: cpu_freq_time needs freq_mhz > 0")
            freq[(cluster, sample.freq_mhz)] = freq.get((cluster, sample.freq_mhz), 0.0) + sample.value
        elif sample.metric.startswith("cpu_time_"):
            key = (cluster, sample.metric[len("cpu_time_"):])
            states[key] = states.get(key, 0.0) + sample.value
        else:
            key3 = (task, cluster, sample.metric[len("cpu_"):])
            counters[key3] = counters.get(key3, 0.0) + sample.value
    if missing:
        digest.warnings.append(f"CPU ids without cpu_map entry (skipped): {sorted(missing)}")
    if counters:
        if frames:
            for (task, cluster, name), value in sorted(counters.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2])):
                metric_id, unit = _PF_METRIC[name]
                kind, ref = ("task_cluster", f"{task}@{cluster}") if task else ("cluster", cluster)
                digest.observations.append(_value_obs(metric_id, kind, ref, unit, round(value / frames, 3)))
            for (task, cluster, thread), value in sorted(thread_cycles.items()):
                digest.observations.append(_value_obs(
                    "cpu.thread_cycles_pf", "task_thread", f"{task}@{cluster}#{thread}", "count", round(value / frames, 3)))
        elif warn_without_window:
            digest.warnings.append("pmu.window (frames, or duration_s + fps) is not set; per-frame CPU profile not emitted")
    for cluster in sorted({c for c, _ in freq}):
        levels = {f: t for (c, f), t in freq.items() if c == cluster and t > 0}
        total = sum(levels.values())
        for mhz, amount in sorted(levels.items()):
            digest.observations.append(
                _value_obs("cpu.freq_residency", "cluster_freq", f"{cluster}@{mhz:g}", "ratio", round(amount / total, 6))
            )
    for cluster in sorted({c for c, _ in states}):
        total = sum(t for (c, _), t in states.items() if c == cluster)
        if total <= 0:
            continue
        for state in ("active", "clock_gated", "power_gated"):
            if (cluster, state) in states:
                digest.observations.append(_value_obs(
                    f"cpu.{state}_ratio", "cluster", cluster, "ratio", round(states[(cluster, state)] / total, 6)))



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
