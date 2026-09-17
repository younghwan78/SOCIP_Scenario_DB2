"""Bounded semantic trace preview. Exact logical slice names; no timing aggregation."""

from __future__ import annotations
import hashlib
import math
from pathlib import Path

from scenario_db.meas_import.camera import stamp
from scenario_db.meas_import.perfetto_digest import PerfettoTraceProcessor
from scenario_db.meas_import.sequence import SQL_SLICES
from scenario_db.models.evidence.common import Artifact


def sequence_preview(tp, model, *, start_ms=0, window_ms=100, limit=2000):
    if (
        not math.isfinite(start_ms)
        or not math.isfinite(window_ms)
        or start_ms < 0
        or not 0 < window_ms <= 10000
    ):
        raise ValueError("preview window must be finite, positive and <= 10000 ms")
    origin_rows = tp.query("SELECT start_ts AS origin FROM trace_bounds")
    origin = int(origin_rows[0]["origin"])
    start = origin + int(start_ms * 1_000_000)
    end = start + int(window_ms * 1_000_000)
    sql = SQL_SLICES.replace(
        "WHERE s.dur >= 0", f"WHERE s.dur >= 0 AND s.ts >= {start} AND s.ts + s.dur <= {end}"
    )
    rows = tp.query(sql + f" LIMIT {limit + 1}")
    if len(rows) > limit:
        raise ValueError("preview event limit exceeded; select a smaller window")
    tasks = {
        t.task_id: t for t in model.tasks if t.task_id in model.execution_path.enabled_task_ids
    }
    disabled = {t.task_id for t in model.execution_path.disabled_tasks}
    if any(r["slice_name"] in disabled for r in rows):
        raise ValueError("trace includes disabled task in selected path")
    events = {}
    for row in rows:
        task = tasks.get(row["slice_name"])
        if task is None:
            continue
        sid = int(row["slice_id"])
        s, d = int(row["ts_ns"]), int(row["dur_ns"])
        events[sid] = dict(
            event_id=f"slice:{sid}",
            task_id=f"slice:{sid}",
            logical_task_id=task.task_id,
            task_type=task.kind,
            node_id=task.node_refs[0] if len(task.node_refs) == 1 else None,
            start_ns=s,
            duration_ns=d,
            start_ms=(s - origin) / 1e6,
            duration_ms=d / 1e6,
            end_ms=(s + d - origin) / 1e6,
            resource_id=str(row["track_id"]),
            time_origin_ns=origin,
            predecessors=[],
            value_source="measured",
        )
    if not events:
        raise ValueError("no logical task slices matched; producer must use task_id as slice name")
    allowed = {(e.source_task_id, e.target_task_id) for e in model.edges}
    ids = ",".join(str(i) for i in events)
    flows = tp.query(
        f"SELECT slice_out, slice_in FROM flow WHERE slice_out IN ({ids}) AND slice_in IN ({ids}) LIMIT {limit * 5 + 1}"
    )
    if len(flows) > limit * 5:
        raise ValueError("preview flow limit exceeded")
    for flow in flows:
        source, target = events[int(flow["slice_out"])], events[int(flow["slice_in"])]
        if (source["logical_task_id"], target["logical_task_id"]) not in allowed:
            raise ValueError("semantic trace flow disagrees with declared edge")
        target["predecessors"].append(source["event_id"])
    return list(events.values())


def attach_trace(evidence, path: Path, *, start_ms=0, window_ms=100):
    if not path.is_file():
        raise ValueError("semantic trace file not found")
    tp = PerfettoTraceProcessor(str(path))
    try:
        evidence.timeline_events = sequence_preview(
            tp, evidence.pipeline_model, start_ms=start_ms, window_ms=window_ms
        )
    finally:
        tp.close()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    evidence.artifacts.append(
        Artifact(
            type="semantic_perfetto_trace",
            storage="fileshare",
            path=path.name,
            sha256=digest,
            bytes=path.stat().st_size,
            mime="application/octet-stream",
        )
    )
    stamp(evidence)
