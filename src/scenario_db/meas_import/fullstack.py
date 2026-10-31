"""Full-stack perfetto (App · Framework · HAL · Kernel · FW · HW) -> measurement evidence for the Behavior page.

The trace names its work with debug args on each slice (the common-name contract shared with the
in-house Pipeline timing perfetto):

  sdb.task     common name (required; slices without it are counted and skipped)
  sdb.layer    app | framework | hal | kernel | fw | hw (required)
  sdb.frame    frame index of frame-path work; absent for own-cadence work (ABOX, AAC, chunk write …)
  sdb.node     pipeline node id when the task is a Pipeline timing item
  sdb.handoff  kick | complete | ipc | irq | data — how the work was handed to this slice

Hand-offs are perfetto flows (``flow`` table). Nothing is inferred from names or timestamp order.
A representative window (``--window-start-ms`` / ``--window-ms``) becomes ``timeline_events``;
own-cadence periods are measured over the whole trace (median start gap per common name).

``--handoff`` attaches the in-house hand-off order (``sdb.handoff/1`` JSON, design:
docs/design/handoff-flow-ko.md) as ``handoff_flows``. Steps naming a ``task`` / ``slice`` the
trace does not contain are reported, not dropped.

Run from implementation/:
  uv run python -m scenario_db.meas_import.fullstack --trace t.pftrace --out db_Exynos2600_SM-S947B \\
      --evidence-id meas-fullstack-... --scenario ... --variant ... --project ... --measured-at 2026-10-31T10:00:00+09:00 \\
      --silicon-rev EVT1 --sw-baseline sw-vendor-v1.2.3
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scenario_db.meas_import.perfetto_digest import PerfettoTraceProcessor, TraceQuery
from scenario_db.models.evidence.handoff import HandoffDoc
from scenario_db.models.evidence.measurement import MeasurementEvidence

LAYERS = ("app", "framework", "hal", "kernel", "fw", "hw")
HANDOFFS = ("kick", "complete", "ipc", "irq", "data")
GROUP = {"app": "APP", "framework": "FRAMEWORK", "hal": "HAL", "kernel": "KERNEL", "fw": "FW", "hw": "HW"}

SQL_BOUNDS = "SELECT start_ts, end_ts FROM trace_bounds"
SQL_FULLSTACK_SLICES = """
SELECT s.id AS slice_id, s.ts AS ts_ns, s.dur AS dur_ns, s.name AS slice_name, tr.name AS track_name,
       COALESCE(t.name, tr.name) AS thread_name, COALESCE(p.name, p2.name) AS process_name,
       EXTRACT_ARG(s.arg_set_id, 'debug.sdb.task') AS sdb_task,
       EXTRACT_ARG(s.arg_set_id, 'debug.sdb.layer') AS sdb_layer,
       EXTRACT_ARG(s.arg_set_id, 'debug.sdb.frame') AS sdb_frame,
       EXTRACT_ARG(s.arg_set_id, 'debug.sdb.node') AS sdb_node,
       EXTRACT_ARG(s.arg_set_id, 'debug.sdb.handoff') AS sdb_handoff
FROM slice s
JOIN track tr ON tr.id = s.track_id
LEFT JOIN thread_track tt ON tt.id = s.track_id
LEFT JOIN thread t ON t.utid = tt.utid
LEFT JOIN process p ON p.upid = t.upid
LEFT JOIN process_track pt ON pt.id = s.track_id
LEFT JOIN process p2 ON p2.upid = pt.upid
WHERE s.dur >= 0
ORDER BY s.ts, s.id
"""
SQL_FLOWS = "SELECT slice_out, slice_in FROM flow"


def _median(values: list[float]) -> float | None:
    return sorted(values)[len(values) // 2] if values else None


def extract(tp: TraceQuery, *, window_start_ms: float = 0.0, window_ms: float = 200.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Timeline events of the window + an extraction report. Raises ValueError on contract violations."""
    bounds = tp.query(SQL_BOUNDS)[0]
    t0 = int(bounds["start_ts"])
    rows = tp.query(SQL_FULLSTACK_SLICES)
    named, skipped = [], 0
    for row in rows:
        if not row.get("sdb_task"):
            skipped += 1
            continue
        layer = str(row.get("sdb_layer") or "").lower()
        if layer not in LAYERS:
            raise ValueError(f"slice {row['slice_id']} ({row['sdb_task']}): sdb.layer must be one of {LAYERS}, got {row.get('sdb_layer')!r}")
        handoff = row.get("sdb_handoff")
        if handoff is not None and handoff not in HANDOFFS:
            raise ValueError(f"slice {row['slice_id']} ({row['sdb_task']}): sdb.handoff must be one of {HANDOFFS}")
        named.append({**row, "layer": layer, "frame": None if row.get("sdb_frame") is None else int(row["sdb_frame"]),
                      "start_ms": (int(row["ts_ns"]) - t0) / 1e6, "dur_ms": int(row["dur_ns"]) / 1e6})

    # own cadence over the whole trace (median start gap of frame-less work)
    starts: dict[str, list[float]] = defaultdict(list)
    for r in named:
        if r["frame"] is None:
            starts[r["sdb_task"]].append(r["start_ms"])
    period = {task: _median([b - a for a, b in zip(sorted(v), sorted(v)[1:])]) for task, v in starts.items()}

    window = [r for r in named if window_start_ms <= r["start_ms"] <= window_start_ms + window_ms]
    ids: dict[int, str] = {}
    used: dict[str, int] = defaultdict(int)
    counter: dict[str, int] = defaultdict(int)
    for r in window:
        if r["frame"] is not None:
            base = f"{r['sdb_task']}#f{r['frame']}"
        else:
            base = f"{r['sdb_task']}#c{counter[r['sdb_task']]}"
            counter[r["sdb_task"]] += 1
        used[base] += 1
        ids[int(r["slice_id"])] = base if used[base] == 1 else f"{base}.{used[base] - 1}"
    preds: dict[int, list[int]] = defaultdict(list)
    for f in tp.query(SQL_FLOWS):
        preds[int(f["slice_in"])].append(int(f["slice_out"]))

    events = []
    for r in window:
        sid = int(r["slice_id"])
        process = r.get("process_name") or r.get("track_name") or "?"
        thread = r.get("thread_name") or r.get("track_name") or "?"
        ev: dict[str, Any] = {
            "task_id": ids[sid], "logical_task_id": r["sdb_task"], "layer": r["layer"], "process": process, "thread": thread,
            "resource_name": f"fullstack/{GROUP[r['layer']]}/{process} · {thread}",
            "task_type": "hw" if r["layer"] == "hw" else "sw", "frame_index": r["frame"],
            "start_ms": round(r["start_ms"] - window_start_ms, 4), "end_ms": round(r["start_ms"] - window_start_ms + r["dur_ms"], 4),
            "duration_ms": round(r["dur_ms"], 4),
            "predecessors": [ids[p] for p in preds.get(sid, []) if p in ids],
        }
        if r.get("sdb_handoff"):
            ev["handoff"] = r["sdb_handoff"]
        if r.get("sdb_node"):
            ev["node_id"] = r["sdb_node"]
        own = period.get(r["sdb_task"]) if r["frame"] is None else None
        if own:
            ev["cadence_period_ms"] = round(own, 4)
        events.append(ev)
    report = {
        "trace_duration_ms": (int(bounds["end_ts"]) - t0) / 1e6,
        "named_slices": len(named), "skipped_unnamed_slices": skipped, "window_events": len(events),
        "window": [window_start_ms, window_start_ms + window_ms],
        "common_names": len({r["sdb_task"] for r in named}),
        "layers": {layer: sum(1 for r in named if r["layer"] == layer) for layer in LAYERS},
        "causal_policy": "Hand-offs only from perfetto flows; nothing inferred from names or timestamp order",
    }
    return events, report


def evidence(events: list[dict[str, Any]], *, evidence_id: str, scenario: str, variant: str, project: str,
             measured_at: str, silicon_rev: str, sw_baseline_ref: str, thermal: str = "room",
             trace_path: str | None = None, trace_sha256: str | None = None,
             window_ms: float = 200.0, data_origin: str = "physical_capture") -> dict[str, Any]:
    raw = [{"type": "perfetto.fullstack", "path": trace_path, "sha256": trace_sha256}] if trace_path else []
    return {
        "id": evidence_id, "schema_version": "2.2", "kind": "evidence.measurement",
        "scenario_ref": scenario, "variant_ref": variant, "project_ref": project, "measured_at": measured_at,
        "execution_context": {"silicon_rev": silicon_rev, "sw_baseline_ref": sw_baseline_ref, "thermal": thermal, "method": "measurement"},
        "provenance": {"collection_method": "perfetto_fullstack", "data_origin": data_origin,
                       "duration_per_sample_s": window_ms / 1000.0, "raw_artifacts": raw},
        "aggregation": {"strategy": "single_run"},
        "timeline_events": events,
    }


def handoff_flows(raw: dict[str, Any], events: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a ``sdb.handoff/1`` document and cross-check its task / slice references against the trace."""
    doc = HandoffDoc.model_validate(raw)
    tasks = {str(e.get("logical_task_id")) for e in events}
    slices = {str(e.get("task_id")) for e in events}
    steps = [s for f in doc.flows for s in f.steps if s.note is None]
    report = {
        "flows": len(doc.flows), "steps": len(steps), "cadences": len(doc.cadences),
        "unknown_tasks": sorted({s.task for s in steps if s.task and s.task not in tasks}),
        "unknown_slices": sorted({s.slice for s in steps if s.slice and s.slice not in slices}),
    }
    return doc.model_dump(by_alias=True, exclude_none=True, exclude_defaults=True), report


def main(argv: list[str] | None = None) -> int:
    import yaml

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trace", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True, help="fixture DB folder (writes 03_evidence/<id>.yaml)")
    ap.add_argument("--evidence-id", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--measured-at", required=True, help="ISO 8601 with timezone")
    ap.add_argument("--silicon-rev", required=True, help="e.g. EVT1")
    ap.add_argument("--sw-baseline", required=True, help="sw profile id, e.g. sw-vendor-v1.2.3")
    ap.add_argument("--thermal", default="room")
    ap.add_argument("--window-start-ms", type=float, default=0.0)
    ap.add_argument("--window-ms", type=float, default=200.0)
    ap.add_argument("--handoff", type=Path, help="in-house hand-off order, sdb.handoff/1 JSON")
    args = ap.parse_args(argv)
    tp = PerfettoTraceProcessor(str(args.trace))
    try:
        events, report = extract(tp, window_start_ms=args.window_start_ms, window_ms=args.window_ms)
    finally:
        tp.close()
    doc = evidence(events, evidence_id=args.evidence_id, scenario=args.scenario, variant=args.variant, project=args.project,
                   measured_at=args.measured_at, silicon_rev=args.silicon_rev, sw_baseline_ref=args.sw_baseline,
                   thermal=args.thermal, trace_path=args.trace.name,
                   trace_sha256=hashlib.sha256(args.trace.read_bytes()).hexdigest(), window_ms=args.window_ms)
    if args.handoff:
        raw = args.handoff.read_bytes()
        doc["handoff_flows"], report["handoff"] = handoff_flows(json.loads(raw), events)
        doc["provenance"]["raw_artifacts"].append(
            {"type": "json.handoff", "path": args.handoff.name, "sha256": hashlib.sha256(raw).hexdigest()})
    MeasurementEvidence.model_validate(doc)
    out = args.out / "03_evidence" / f"{args.evidence_id}.yaml"
    text = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    if out.exists() and out.read_text(encoding="utf-8") != text:
        raise SystemExit(f"{out} exists with different content; use a new evidence id")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({**report, "evidence": str(out)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
