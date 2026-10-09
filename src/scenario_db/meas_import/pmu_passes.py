"""Merge PMU counters captured in several passes (counter multiplexing avoided by splitting the events).

A capture split into passes (e.g. 15 s x 3: core/topdown, cache, bus events) carries the same anchor
counters in every pass — ``cycles`` (CPU_CYCLES) and ``instructions`` (INST_RETIRED). Passes ran at
different times, so their counters cannot be summed or time-aligned. Per scope (task x cpu/cluster,
thread) the merge is:

- anchors: mean over the passes that have them (one pass worth of work)
- any other counter: its per-instruction ratio in the passes that measured it x the merged
  instructions (falls back to the plain mean when a pass has no instruction anchor)
- thread cycles: mean over the passes that have them

Quality: the coefficient of variation of the anchors across passes per task (and for the whole
capture) becomes ``cpu.pass_cv`` (scope ``task`` / ``capture``); above ``PASS_CV_WARN`` the passes saw
different work (thermal, load, scene) and the merged profile is less trustworthy.

``pmu.window`` describes ONE pass (its frames / duration), because merged counters are per pass.
"""
from __future__ import annotations

import math
from typing import Any

PASS_CV_WARN = 0.05
ANCHORS = ("cpu_cycles", "cpu_instructions")
COUNTERS = ("cpu_cycles", "cpu_instructions", "cpu_stall_cycles", "cpu_bus_bytes")
MIN_TASK_SHARE = 0.01          # tasks below 1 % of the cycles are not worth a warning


def _cv(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var) / mean


def _task_of(kind: str, ref: str) -> str | None:
    if kind.startswith("task_thread_"):
        return ref.rpartition("@")[0].partition("#")[0]
    if kind.startswith("task_"):
        return ref.rpartition("@")[0]
    return None


def merge_counter_groups(samples: list[Any], make: Any) -> tuple[list[Any], list[dict], list[str]]:
    """(samples with grouped counters replaced by merged ones, cpu.pass_cv observations, warnings).

    ``make(metric, scope_kind, scope_ref, value, line)`` builds a sample of the caller's type.
    Samples without a group, and non-counter samples, pass through unchanged.
    """
    grouped = [s for s in samples if s.group and (s.metric in COUNTERS or s.metric == "cpu_thread_cycles")]
    if not grouped:
        return samples, [], []
    ids = {id(s) for s in grouped}
    rest = [s for s in samples if id(s) not in ids]
    groups = sorted({s.group for s in grouped})
    warnings: list[str] = []
    if len(groups) < 2:
        warnings.append(f"PMU counters carry one group only ({groups[0]}): no pass merge")
        return [make(s.metric, s.scope_kind, s.scope_ref, s.value, s.line) for s in grouped] + rest, [], warnings
    # (scope_kind, scope_ref) -> group -> metric -> value
    table: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for s in grouped:
        cell = table.setdefault((s.scope_kind, s.scope_ref), {}).setdefault(s.group, {})
        cell[s.metric] = cell.get(s.metric, 0.0) + s.value
    missing_anchor: set[str] = set()
    merged: list[Any] = []
    for (kind, ref), by_group in sorted(table.items()):
        if kind.startswith("task_thread_"):
            vals = [g["cpu_thread_cycles"] for g in by_group.values() if "cpu_thread_cycles" in g]
            if vals:
                merged.append(make("cpu_thread_cycles", kind, ref, sum(vals) / len(vals), None))
            continue
        anchors: dict[str, float] = {}
        for a in ANCHORS:
            vals = [g[a] for g in by_group.values() if a in g]
            if vals:
                anchors[a] = sum(vals) / len(vals)
            if len(vals) < len(groups):
                missing_anchor.add(a)
        for metric in sorted({m for g in by_group.values() for m in g}):
            if metric in ANCHORS:
                value = anchors[metric]
            else:
                with_instr = [g for g in by_group.values() if metric in g and g.get("cpu_instructions")]
                if with_instr and "cpu_instructions" in anchors:
                    ratio = sum(g[metric] for g in with_instr) / sum(g["cpu_instructions"] for g in with_instr)
                    value = ratio * anchors["cpu_instructions"]
                else:
                    vals = [g[metric] for g in by_group.values() if metric in g]
                    value = sum(vals) / len(vals)
            merged.append(make(metric, kind, ref, value, None))
    if missing_anchor:
        warnings.append(f"PMU pass merge: anchor counters {sorted(missing_anchor)} missing in some passes — "
                        "put CPU_CYCLES and INST_RETIRED in every pass")
    # anchor stability per task and for the capture
    per_task: dict[str, dict[str, dict[str, float]]] = {}
    for (kind, ref), by_group in table.items():
        if kind.startswith("task_thread_"):
            continue
        task = _task_of(kind, ref) or "(cluster)"
        for g, cell in by_group.items():
            acc = per_task.setdefault(task, {}).setdefault(g, {})
            for a in ANCHORS:
                if a in cell:
                    acc[a] = acc.get(a, 0.0) + cell[a]
    total_cycles = sum(sum(v.get("cpu_cycles", 0.0) for v in gs.values()) for gs in per_task.values()) or 1.0
    obs: list[dict] = []
    capture: dict[str, dict[str, float]] = {}
    noisy = []
    for task, by_group in sorted(per_task.items()):
        cvs = [c for c in (_cv([v[a] for v in by_group.values() if a in v]) for a in ANCHORS) if c is not None]
        for g, v in by_group.items():
            cap = capture.setdefault(g, {})
            for a in ANCHORS:
                cap[a] = cap.get(a, 0.0) + v.get(a, 0.0)
        if not cvs or task == "(cluster)":
            continue
        cv = max(cvs)
        obs.append({"metric_id": "cpu.pass_cv", "scope": {"kind": "task", "ref": task}, "unit": "ratio", "value": round(cv, 6)})
        share = sum(v.get("cpu_cycles", 0.0) for v in by_group.values()) / total_cycles
        if cv > PASS_CV_WARN and share >= MIN_TASK_SHARE:
            noisy.append(f"{task} {cv * 100:.1f}%")
    cap_cvs = [c for c in (_cv([v[a] for v in capture.values() if v.get(a)]) for a in ANCHORS) if c is not None]
    if cap_cvs:
        obs.append({"metric_id": "cpu.pass_cv", "scope": {"kind": "capture", "ref": "all"}, "unit": "ratio",
                    "value": round(max(cap_cvs), 6)})
    if noisy:
        warnings.append(f"PMU passes {groups} disagree on the anchor counters (CV > {PASS_CV_WARN * 100:.0f}%): "
                        + ", ".join(noisy[:10]))
    return merged + rest, obs, warnings
