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
SELECT cct.cpu AS cpu,
       c.value AS freq_khz,
       SUM(
         COALESCE(LEAD(c.ts) OVER (PARTITION BY c.track_id ORDER BY c.ts), c.ts) - c.ts
       ) AS dur_ns
FROM counter c
JOIN cpu_counter_track cct ON c.track_id = cct.id
WHERE cct.name = 'cpufreq'
GROUP BY cct.cpu, c.value
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


# --- sw task timing ----------------------------------------------------------

def _match_slice(row: dict[str, Any], match: TaskMatch) -> bool:
    proc = row.get("process_name") or ""
    thr = row.get("thread_name") or ""
    name = row.get("slice_name") or ""
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
        durations_ms = [
            float(row["dur_ns"]) / NS_PER_MS
            for row in rows
            if _match_slice(row, mapping.match)
        ]
        entry: dict[str, Any] = {"task": mapping.task}
        if mapping.cluster:
            entry["cluster"] = mapping.cluster
        if durations_ms:
            entry["mean_ms"] = round(sum(durations_ms) / len(durations_ms), 3)
            entry["p50_ms"] = round(percentile(durations_ms, 50.0), 3)
            entry["p95_ms"] = round(percentile(durations_ms, 95.0), 3)
            entry["max_ms"] = round(max(durations_ms), 3)
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


def extract_digest(tp: TraceQuery, spec: PerfettoSpec) -> PerfettoDigest:
    digest = PerfettoDigest()

    if spec.cpu_to_cluster:
        residency = extract_freq_residency(tp.query(SQL_FREQ_RESIDENCY), spec.cpu_to_cluster)
        digest.freq_residency = residency
        for cluster, bins in residency.items():
            avg = avg_freq_mhz(bins)
            if avg is not None:
                digest.cluster_avg_freq[cluster] = avg

    # frame count: explicit override, else count frame-marker slices.
    frame_count = spec.frame_count
    if frame_count is None and spec.frame_slice_name:
        sql = SQL_FRAME_COUNT.replace(":frame_name", _sql_quote(spec.frame_slice_name))
        rows = tp.query(sql)
        if rows:
            frame_count = int(rows[0].get("frame_count") or 0) or None
    digest.frame_count = frame_count

    if spec.task_mapping:
        slice_rows = tp.query(SQL_THREAD_SLICES)
        digest.sw_task_timing = extract_sw_task_timing(slice_rows, spec, frame_count)

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
