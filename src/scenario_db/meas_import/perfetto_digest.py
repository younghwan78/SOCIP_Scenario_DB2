"""Perfetto trace digest extraction.

The heavy trace_processor dependency is kept behind a small protocol so the
*shaping* logic (residency normalisation, percentile rollups, task mapping) is
fully unit-testable without a real trace or the perfetto binary.

- ``TraceQuery``: anything with ``query(sql) -> iterable of row-dicts``.
- ``PerfettoTraceProcessor``: lazy adapter over ``perfetto.trace_processor``.
- ``extract_*``: pure functions consuming query results.

SQL constants target the standard perfetto trace_processor schema
(``counter``/``cpu_counter_track`` for cpufreq, ``slice``/``thread_track``/
``thread``/``process`` for slices). They are module-level so they can be
reviewed and adjusted per trace config without touching the shaping code.
"""
from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from scenario_db.meas_import.meta import PerfettoSpec, TaskMatch
from scenario_db.meas_import.stats import measured_kpi, percentile


@runtime_checkable
class TraceQuery(Protocol):
    def query(self, sql: str) -> list[dict[str, Any]]: ...


# --- SQL ---------------------------------------------------------------------

# Time-weighted CPU frequency residency: each cpufreq counter sample holds until
# the next sample on the same track. ts/dur are nanoseconds in perfetto.
SQL_FREQ_RESIDENCY = """
WITH freq_spans AS (
  SELECT cct.cpu AS cpu,
         c.value AS freq_khz,
         COALESCE(
           LEAD(c.ts) OVER (PARTITION BY c.track_id ORDER BY c.ts),
           c.ts
         ) - c.ts AS dur_ns
  FROM counter c
  JOIN cpu_counter_track cct ON c.track_id = cct.id
  WHERE cct.name = 'cpufreq'
)
SELECT cpu, freq_khz, SUM(dur_ns) AS dur_ns
FROM freq_spans
GROUP BY cpu, freq_khz
"""

# Slice durations joined with the owning thread/process. dur is nanoseconds.
SQL_THREAD_SLICES = """
SELECT s.name AS slice_name,
       s.dur AS dur_ns,
       t.name AS thread_name,
       p.name AS process_name
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
LEFT JOIN process p ON t.upid = p.upid
WHERE s.dur >= 0
"""

# Count of frame-marker slices (used to normalise per-frame counts).
SQL_FRAME_COUNT = "SELECT COUNT(*) AS frame_count FROM slice WHERE name = :frame_name"

NS_PER_MS = 1_000_000.0

# CPU time per frequency while the CPU is not idle (clock_residency "active" basis):
# cpufreq spans x cpuidle spans per CPU (cpuidle value 4294967295 / -1 = left idle = running).
# Multi-statement: helper views + SPAN_JOIN; the last statement returns the rows.
SQL_CPU_ACTIVE_RESIDENCY = """
DROP TABLE IF EXISTS _sdb_cpu_freq_idle;
DROP VIEW IF EXISTS _sdb_cpu_freq;
DROP VIEW IF EXISTS _sdb_cpu_idle;
CREATE VIEW _sdb_cpu_freq AS
SELECT ts, dur, cpu, freq_khz FROM (
  SELECT c.ts AS ts, LEAD(c.ts) OVER (PARTITION BY c.track_id ORDER BY c.ts) - c.ts AS dur,
         cct.cpu AS cpu, c.value AS freq_khz
  FROM counter c JOIN cpu_counter_track cct ON c.track_id = cct.id
  WHERE cct.name = 'cpufreq'
) WHERE dur > 0;
CREATE VIEW _sdb_cpu_idle AS
SELECT ts, dur, cpu, CASE WHEN idle_value IN (4294967295, -1) THEN 1 ELSE 0 END AS running FROM (
  SELECT c.ts AS ts, LEAD(c.ts) OVER (PARTITION BY c.track_id ORDER BY c.ts) - c.ts AS dur,
         cct.cpu AS cpu, c.value AS idle_value
  FROM counter c JOIN cpu_counter_track cct ON c.track_id = cct.id
  WHERE cct.name = 'cpuidle'
) WHERE dur > 0;
CREATE VIRTUAL TABLE _sdb_cpu_freq_idle USING SPAN_JOIN(_sdb_cpu_freq PARTITIONED cpu, _sdb_cpu_idle PARTITIONED cpu);
SELECT cpu, freq_khz, SUM(dur) AS dur_ns FROM _sdb_cpu_freq_idle WHERE running = 1 GROUP BY cpu, freq_khz
"""


def _names(tracks: list[str]) -> str:
    return ", ".join(_sql_quote(t) for t in tracks)


def sql_counter_residency(tracks: list[str]) -> str:
    """Wall-clock time per value of the named counter tracks (grouped by track)."""
    return f"""
SELECT track, value, SUM(dur) AS dur_ns FROM (
  SELECT t.name AS track, c.value AS value,
         LEAD(c.ts) OVER (PARTITION BY c.track_id ORDER BY c.ts) - c.ts AS dur
  FROM counter c JOIN counter_track t ON c.track_id = t.id
  WHERE t.name IN ({_names(tracks)})
) WHERE dur > 0 GROUP BY track, value
"""


def sql_counter_active_residency(freq_track: str, util_track: str, scale: float) -> str:
    """Busy-weighted time per frequency: frequency spans x utilisation spans (value / scale = busy share)."""
    return f"""
DROP TABLE IF EXISTS _sdb_cd_join;
DROP VIEW IF EXISTS _sdb_cd_freq;
DROP VIEW IF EXISTS _sdb_cd_util;
CREATE VIEW _sdb_cd_freq AS SELECT ts, dur, value AS freq FROM (
  SELECT c.ts AS ts, LEAD(c.ts) OVER (ORDER BY c.ts) - c.ts AS dur, c.value AS value
  FROM counter c JOIN counter_track t ON c.track_id = t.id WHERE t.name = {_sql_quote(freq_track)}
) WHERE dur > 0;
CREATE VIEW _sdb_cd_util AS SELECT ts, dur, value AS util FROM (
  SELECT c.ts AS ts, LEAD(c.ts) OVER (ORDER BY c.ts) - c.ts AS dur, c.value AS value
  FROM counter c JOIN counter_track t ON c.track_id = t.id WHERE t.name = {_sql_quote(util_track)}
) WHERE dur > 0;
CREATE VIRTUAL TABLE _sdb_cd_join USING SPAN_JOIN(_sdb_cd_freq, _sdb_cd_util);
SELECT freq AS value, SUM(dur * MIN(MAX(util / {float(scale)!r}, 0.0), 1.0)) AS busy_ns, SUM(dur) AS dur_ns
FROM _sdb_cd_join GROUP BY freq
"""


# --- frequency residency -----------------------------------------------------

def extract_freq_residency(
    rows: list[dict[str, Any]],
    cpu_to_cluster: dict[int, str],
) -> dict[str, list[dict]]:
    """Aggregate per-cpu freq dur_ns into per-cluster residency bins.

    Returns {cluster: [{freq_mhz, ratio, time_ms}, ...]} with ratio summing to
    ~1.0 within each cluster, ordered by descending residency.
    """
    # cluster -> freq_mhz -> dur_ns
    by_cluster: dict[str, dict[float, float]] = {}
    for row in rows:
        cpu = int(row["cpu"])
        cluster = cpu_to_cluster.get(cpu)
        if cluster is None:
            continue
        freq_mhz = round(float(row["freq_khz"]) / 1000.0, 3)
        dur_ns = float(row["dur_ns"] or 0.0)
        by_cluster.setdefault(cluster, {})
        by_cluster[cluster][freq_mhz] = by_cluster[cluster].get(freq_mhz, 0.0) + dur_ns

    out: dict[str, list[dict]] = {}
    for cluster, freq_dur in by_cluster.items():
        total = sum(freq_dur.values())
        bins = []
        for freq_mhz, dur_ns in freq_dur.items():
            ratio = (dur_ns / total) if total > 0 else 0.0
            bins.append(
                {
                    "freq_mhz": freq_mhz,
                    "ratio": round(ratio, 4),
                    "time_ms": round(dur_ns / NS_PER_MS, 3),
                }
            )
        bins.sort(key=lambda b: b["ratio"], reverse=True)
        out[cluster] = bins
    return out


def avg_freq_mhz(bins: list[dict]) -> float | None:
    """Residency-weighted average frequency from residency bins."""
    total_ratio = sum(b["ratio"] for b in bins)
    if total_ratio <= 0:
        return None
    return round(sum(b["freq_mhz"] * b["ratio"] for b in bins) / total_ratio, 3)


# --- clock-domain residency --------------------------------------------------

_TO_MHZ = {"mhz": 1.0, "khz": 1e-3, "hz": 1e-6, "ghz": 1000.0}


def extract_cpu_active_residency(rows: list[dict[str, Any]], cpu_to_cluster: dict[int, str]) -> dict[str, dict[float, float]]:
    """{cluster: {MHz: running ns}} from SQL_CPU_ACTIVE_RESIDENCY rows (CPUs summed per cluster)."""
    out: dict[str, dict[float, float]] = {}
    for row in rows:
        cluster = cpu_to_cluster.get(int(row["cpu"]))
        dur = float(row.get("dur_ns") or 0.0)
        if cluster is None or dur <= 0 or not row.get("freq_khz"):
            continue
        mhz = round(float(row["freq_khz"]) / 1000.0, 3)
        level = out.setdefault(cluster, {})
        level[mhz] = level.get(mhz, 0.0) + dur
    return out


def extract_counter_residency(rows: list[dict[str, Any]], tracks: list[str], unit: str) -> tuple[str | None, dict[float, float]]:
    """(track used, {MHz: ns}) — the first configured track that has samples."""
    by_track: dict[str, dict[float, float]] = {}
    for row in rows:
        value, dur = row.get("value"), float(row.get("dur_ns") or 0.0)
        if value is None or float(value) <= 0 or dur <= 0:
            continue
        mhz = round(float(value) * _TO_MHZ[unit], 3)
        level = by_track.setdefault(str(row.get("track")), {})
        level[mhz] = level.get(mhz, 0.0) + dur
    for track in tracks:
        if by_track.get(track):
            return track, by_track[track]
    return None, {}


def extract_active_split(rows: list[dict[str, Any]], unit: str) -> tuple[dict[float, float], float | None]:
    """({MHz: busy ns}, busy share) from sql_counter_active_residency rows."""
    busy: dict[float, float] = {}
    total = busy_total = 0.0
    for row in rows:
        value = row.get("value")
        if value is None or float(value) <= 0:
            continue
        b, d = float(row.get("busy_ns") or 0.0), float(row.get("dur_ns") or 0.0)
        total += d
        busy_total += b
        if b > 0:
            mhz = round(float(value) * _TO_MHZ[unit], 3)
            busy[mhz] = busy.get(mhz, 0.0) + b
    return busy, (busy_total / total if total > 0 else None)


def extract_clock_domains(tp: TraceQuery, spec: PerfettoSpec, digest: PerfettoDigest) -> None:
    """Fill ``digest.clock_residency`` / ``clock_ratios`` (see clock_residency.perfetto_observations)."""
    if spec.cpu_active_residency and spec.cpu_to_cluster:
        for cluster, bins in sorted(extract_cpu_active_residency(tp.query(SQL_CPU_ACTIVE_RESIDENCY), spec.cpu_to_cluster).items()):
            digest.clock_residency.append({"domain_class": "cpu", "domain": cluster, "basis": "active", "bins": bins})
    for dom in spec.clock_domains:
        track, wall = extract_counter_residency(tp.query(sql_counter_residency(dom.tracks)), dom.tracks, dom.freq_unit)
        if track is None:
            digest.warnings.append(f"clock domain {dom.name}: no samples on tracks {dom.tracks}")
            continue
        digest.clock_residency.append({"domain_class": dom.domain_class, "domain": dom.name, "basis": "wall", "bins": wall})
        if dom.utilization_track:
            busy, share = extract_active_split(
                tp.query(sql_counter_active_residency(track, dom.utilization_track, dom.utilization_scale)), dom.freq_unit)
            if busy:
                digest.clock_residency.append({"domain_class": dom.domain_class, "domain": dom.name, "basis": "active", "bins": busy})
            if share is not None:
                digest.clock_ratios.append({"domain_class": dom.domain_class, "domain": dom.name, "active_ratio": share})
            else:
                digest.warnings.append(f"clock domain {dom.name}: utilization track {dom.utilization_track} has no samples")


# --- sw task timing ----------------------------------------------------------

def _match_slice(row: dict[str, Any], match: TaskMatch) -> bool:
    proc = row.get("process_name") or ""
    thr = row.get("thread_name") or ""
    name = row.get("slice_name") or ""
    if match.track is not None and row.get("track_name") != match.track:
        return False
    if match.process is not None and proc != match.process:
        return False
    if match.process_re is not None and not re.search(match.process_re, proc):
        return False
    if match.thread is not None and thr != match.thread:
        return False
    if match.thread_re is not None and not re.search(match.thread_re, thr):
        return False
    if match.slice_re is not None and not re.search(match.slice_re, name):
        return False
    return True


def extract_sw_task_timing(
    rows: list[dict[str, Any]],
    spec: PerfettoSpec,
    frame_count: int | None,
) -> list[dict]:
    """Roll up matched slice durations (ns) into per-task ms statistics."""
    out: list[dict] = []
    for mapping in spec.task_mapping:
        if mapping.execution_kind != "sw":
            continue
        durations_ms = [
            float(row["dur_ns"]) / NS_PER_MS
            for row in rows
            if _match_slice(row, mapping.match)
        ]
        entry: dict[str, Any] = {"task": mapping.task}
        if mapping.cluster:
            entry["cluster"] = mapping.cluster
        if durations_ms:
            entry["min_ms"] = min(durations_ms)
            entry["value_source"] = "measured"
            entry["mean_ms"] = sum(durations_ms) / len(durations_ms)
            entry["p50_ms"] = percentile(durations_ms, 50.0)
            entry["p95_ms"] = percentile(durations_ms, 95.0)
            entry["max_ms"] = max(durations_ms)
            entry["samples"] = len(durations_ms)
            if frame_count and frame_count > 0:
                entry["count_per_frame"] = round(len(durations_ms) / frame_count, 4)
        out.append(entry)
    return out


# --- orchestration -----------------------------------------------------------

class PerfettoDigest:
    def __init__(self) -> None:
        self.freq_residency: dict[str, list[dict]] = {}
        self.cluster_avg_freq: dict[str, float] = {}
        self.sw_task_timing: list[dict] = []
        self.frame_count: int | None = None
        self.hw_task_timing: list[dict] = []
        self.sw_event_latency: list[dict] = []
        self.timeline_events: list[dict] = []
        # clock-domain residency: [{domain_class, domain, basis, bins {MHz: ns}}], [{domain_class, domain, active_ratio}]
        self.clock_residency: list[dict] = []
        self.clock_ratios: list[dict] = []
        self.warnings: list[str] = []


def extract_digest(tp: TraceQuery, spec: PerfettoSpec) -> PerfettoDigest:
    digest = PerfettoDigest()

    if spec.cpu_to_cluster:
        residency = extract_freq_residency(tp.query(SQL_FREQ_RESIDENCY), spec.cpu_to_cluster)
        digest.freq_residency = residency
        for cluster, bins in residency.items():
            avg = avg_freq_mhz(bins)
            if avg is not None:
                digest.cluster_avg_freq[cluster] = avg

    if spec.cpu_active_residency or spec.clock_domains:
        extract_clock_domains(tp, spec, digest)

    # frame count: explicit override, else count frame-marker slices.
    frame_count = spec.frame_count
    if frame_count is None and spec.frame_slice_name:
        sql = SQL_FRAME_COUNT.replace(":frame_name", _sql_quote(spec.frame_slice_name))
        rows = tp.query(sql)
        if rows:
            frame_count = int(rows[0].get("frame_count") or 0) or None
    digest.frame_count = frame_count

    if spec.task_mapping and not (spec.include_sequence or spec.event_latency_mapping or any(m.execution_kind == "hw" for m in spec.task_mapping)):
        slice_rows = tp.query(SQL_THREAD_SLICES)
        digest.sw_task_timing = extract_sw_task_timing(slice_rows, spec, frame_count)

    if spec.include_sequence or spec.event_latency_mapping or any(m.execution_kind == "hw" for m in spec.task_mapping):
        from scenario_db.meas_import.sequence import extract_sequence
        extract_sequence(tp, spec, digest)

    if spec.required:
        found = {r["task"] for r in [*digest.sw_task_timing, *digest.hw_task_timing] if r.get("samples")}
        missing = {m.task for m in spec.task_mapping} - found
        if missing:
            raise ValueError(f"required task mappings have no samples: {sorted(missing)}")
    return digest


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# --- lazy real adapter -------------------------------------------------------

class PerfettoTraceProcessor:
    """Thin adapter over the perfetto trace_processor Python API.

    Imported lazily so the package has no hard dependency on perfetto. Raises a
    clear error when the optional dependency is missing.
    """

    def __init__(self, trace_path: str):
        try:
            from perfetto.trace_processor import TraceProcessor  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise RuntimeError(
                "perfetto trace digest requested but the 'perfetto' package is not "
                "installed. Install it (uv add perfetto) or omit the 'perfetto' "
                "section from meta.yaml to import power data only."
            ) from exc
        self._tp = TraceProcessor(trace=trace_path)

    def query(self, sql: str) -> list[dict[str, Any]]:  # pragma: no cover - needs binary
        return [dict(row.__dict__) for row in self._tp.query(sql)]

    def close(self) -> None:  # pragma: no cover - needs binary
        self._tp.close()
