"""Aggregate curated Scenario tracks, preserving explicit producer mappings.

This consumes Perfetto slices, not vendor-specific raw ftrace kernel events.
Unknown events are counted, never converted to inferred tasks or dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

from scenario_db.meas_import.camera import CameraBundle, assemble_camera, parse_markdown
from scenario_db.meas_import.perfetto_digest import PerfettoTraceProcessor
from scenario_db.meas_import.sequence import SQL_SLICES, statistics
from scenario_db.models.evidence.camera import CameraPipeline


def logical_name(row, tasks):
    """Match exact configured prefix + decimal frame ID on an exact track.

    Legacy producers may continue to emit exact logical task IDs. Mapping is
    explicit to avoid accepting similarly named events from unrelated tracks.
    """
    matches = []
    for task in tasks:
        if task.trace_slice_name is None:
            matched = row["slice_name"] == task.task_id
        else:
            matched = (
                row.get("track_name") == task.trace_track_name
                and re.fullmatch(re.escape(task.trace_slice_name) + r" f[0-9]+", row["slice_name"] or "")
            )
        if matched:
            matches.append(task.task_id)
    if len(matches) > 1:
        raise ValueError("ambiguous semantic trace task mapping")
    return matches[0] if matches else None


def summarize(tp, template: CameraBundle):
    model = CameraPipeline.model_validate({
        **template.pipeline_model, "execution_path": template.execution_path.model_dump()
    })
    bounds = tp.query("SELECT start_ts, end_ts FROM trace_bounds")[0]
    values = defaultdict(list)
    ignored = 0
    incomplete = 0
    seen = set()
    # Count unfinished slices as exclusions rather than silently losing them.
    for row in tp.query(SQL_SLICES.replace("WHERE s.dur >= 0", "WHERE 1=1")):
        task_id = logical_name(row, model.tasks)
        if task_id is None:
            ignored += 1
            continue
        if task_id not in model.execution_path.enabled_task_ids:
            raise ValueError(f"trace contains inactive task: {task_id}")
        if int(row["dur_ns"]) < 0:
            incomplete += 1
            continue
        # A frame ID is scoped to a configured logical task, not timestamp order.
        frame = re.search(r" f([0-9]+)$", row["slice_name"])
        if frame:
            key = (task_id, int(frame[1]))
            if key in seen:
                raise ValueError(f"duplicate task/frame sample: {key}")
            seen.add(key)
        values[task_id].append(int(row["dur_ns"]) / 1e6)
    missing = set(model.execution_path.enabled_task_ids) - values.keys()
    if missing:
        raise ValueError(f"required tasks have no complete samples: {sorted(missing)}")
    sw, hw = [], []
    for task in model.tasks:
        if task.task_id not in values:
            continue
        stat = dict(task=task.task_id, **statistics(values[task.task_id]))
        if task.kind == "sw":
            sw.append(stat)
        elif task.kind == "hw" and len(task.node_refs) == 1:
            hw.append(dict(**stat, node_id=task.node_refs[0]))
        else:
            raise ValueError("trace summary supports individual HW/SW tasks only")
    report = dict(
        duration_ms=(int(bounds["end_ts"]) - int(bounds["start_ts"])) / 1e6,
        ignored_slices=ignored, incomplete_slices=incomplete,
        samples_by_task={k: len(v) for k, v in values.items()},
        causal_policy="No latency or flow inferred from frame numbers or timestamp order",
    )
    raw = template.model_dump(mode="json")
    raw["statistics"] = dict(sw_task_timing=sw, hw_task_timing=hw)
    result = CameraBundle.model_validate(raw)
    assemble_camera(result)
    return result, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Markdown bundle output")
    args = parser.parse_args(argv)
    template = parse_markdown(args.template.read_text(encoding="utf-8-sig"))
    trace = args.trace.resolve()
    base = args.out.parent.resolve()
    if not trace.is_relative_to(base):
        raise ValueError("trace must be inside output bundle directory")
    tp = PerfettoTraceProcessor(str(trace))
    try:
        result, report = summarize(tp, template)
    finally:
        tp.close()
    result.semantic_trace = trace.relative_to(base).as_posix()
    report["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
    text = (
        "# Camera Scenario trace statistics\n\n"
        + result.measurement_scope + "\n\n"
        + "```yaml camera-profile-v1\n"
        + yaml.safe_dump(result.model_dump(mode="json", exclude_none=True), sort_keys=False)
        + "```\n\nExtraction report:\n```json\n"
        + json.dumps(report, indent=2) + "\n```\n"
    )
    if args.out.exists() and args.out.read_text(encoding="utf-8") != text:
        raise ValueError("output exists with different content; use a new revision")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
