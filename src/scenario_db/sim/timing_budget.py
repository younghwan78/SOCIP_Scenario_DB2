"""Stage timing budget: required IP clock, output cadence, power and BW.

Model (docs/guides/timing-budget.md):

* Stages are pipelined through memory (M2M), so every stage owns one frame
  period P per frame and stages of different frames overlap.
* RT (sensor-synchronous OTF): the 25 % SW margin rule, HW time <= 0.75 P,
  bounded below by the sensor line-rate clock correction.
* NRT (MTNR ... MCSC): HW budget = P - SW on the stage (runtime + latency of
  post_crta / pre_me_rta / post_irta, and per-IP driver/IRQ overhead).
* Post-NRT (via memory, one frame later): SW after the NRT HW (EIS when
  stabilization is on, portrait blend, ...) then GDC; HW budget = P - that SW.
* Output (DPU, MFC/APV): the 25 % rule; UHD/8K encode splits across the MFC and
  MFD cores (half the pixels per core, half the clock, same frame time).
* Pass criterion: preview and video completion interval = 1000/fps within
  +/- tolerance (default 0.1 %). Latency is reported, never budgeted.

Read-only: builds simulation inputs from a copied graph and never persists.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import replace
from typing import Any, Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import DVFSTable, SimRunResult, SimulationInputs, SimulationRunConfig
from scenario_db.sim.runner import run_simulation

Statistic = Literal["min", "mean", "max"]
Stage = Literal["rt", "nrt", "post", "output"]
STAGES: tuple[Stage, ...] = ("rt", "nrt", "post", "output")
STAGE_NAME = {"rt": "RT", "nrt": "NRT", "post": "Post-NRT (EIS/SW → GDC)", "output": "Output"}
_MIN_MARGIN = 1e-6
_MIN_TASK_MS = 1e-6
_MAX_MARGIN = 0.95
UHD_PIXELS = 3840 * 2160
# Linux EM / exynos-cpu-profiler coefficients from ip-cpu-s5e9965 (uW per MHz per V^2).
PROFILER_COEFF = [449.0, 449.0, 505.0, 1127.0]
_OUTPUT_RE = re.compile(r"(^|_)(mfc|mfd|apv|dpu|panel|display)", re.I)
_GDC_RE = re.compile(r"(^|_)gdc", re.I)
_ENCODER_RE = re.compile(r"(^|_)(mfc|apv)", re.I)
_DISPLAY_RE = re.compile(r"(^|_)dpu", re.I)


# --------------------------------------------------------------------- inputs
class TimingStat(BaseScenarioModel):
    min_ms: float = Field(ge=0)
    mean_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> TimingStat:
        if not self.min_ms <= self.mean_ms <= self.max_ms:
            raise ValueError("timing must satisfy min_ms <= mean_ms <= max_ms")
        return self

    def value(self, statistic: Statistic) -> float:
        return float(getattr(self, f"{statistic}_ms"))


class SwTaskAdjustment(BaseScenarioModel):
    scale: float | None = Field(default=None, ge=0)
    delta_ms: float | None = None

    @model_validator(mode="after")
    def _one(self) -> SwTaskAdjustment:
        if (self.scale is None) == (self.delta_ms is None):
            raise ValueError("choose exactly one of scale or delta_ms")
        return self

    def apply(self, value: float) -> float:
        if self.scale is not None:
            return max(0.0, value * self.scale)
        return max(0.0, value + float(self.delta_ms or 0.0))


class CpuPowerConfig(BaseScenarioModel):
    """Camera SW CPU power: coeff * f * V^2 * util (Linux EM convention)."""

    cluster: int = Field(default=1, ge=0, le=3)
    freq_mhz: float = Field(default=2000.0, gt=0)
    volt_v: float = Field(default=0.80, gt=0)
    coeff_uw_per_mhz_v2: list[float] = Field(default_factory=lambda: list(PROFILER_COEFF))
    source: str = "ip-cpu-s5e9965 profiler coefficients; cluster/freq/volt assumed"

    def power_mw(self, busy_ms: float, period_ms: float) -> float:
        util = busy_ms / period_ms if period_ms > 0 else 0.0
        return (
            self.coeff_uw_per_mhz_v2[self.cluster] * self.freq_mhz * self.volt_v**2 * util / 1000.0
        )


class TimingBudgetOptions(BaseScenarioModel):
    statistic: Statistic = "max"
    eis: Literal["auto", "on", "off"] = "auto"
    runtime_scale: float = Field(default=1.0, ge=0, le=10)
    latency_scale: float = Field(default=1.0, ge=0, le=10)
    task_adjustments: dict[str, SwTaskAdjustment] = Field(default_factory=dict)
    task_latency: dict[str, TimingStat] = Field(default_factory=dict)
    ip_overhead: dict[str, TimingStat] = Field(default_factory=dict)
    stage_overrides: dict[str, Stage] = Field(default_factory=dict)
    rt_margin: float = Field(default=0.25, ge=0, lt=1)
    output_margin: float = Field(default=0.25, ge=0, lt=1)
    mfc_dual: Literal["auto", "on", "off"] = "auto"
    interval_tolerance: float = Field(default=1e-3, gt=0, le=0.05)
    frames: int = Field(default=12, ge=4, le=64)
    timeline_frames: int = Field(default=6, ge=1, le=16)
    # Stage model: each stage's SW runs on its own thread/core. True keeps the
    # scenario's CPU resource (e.g. one CPU_CAMERA) so cross-stage contention shows.
    shared_cpu: bool = False
    cpu: CpuPowerConfig = Field(default_factory=CpuPowerConfig)
    include_whatif: bool = False
    whatif_scales: list[float] = Field(
        default_factory=lambda: [1.0, 1.1, 1.2, 1.3, 1.4, 1.5], max_length=12
    )

    @model_validator(mode="after")
    def _scales(self) -> TimingBudgetOptions:
        if any(not math.isfinite(v) or v < 0 for v in self.whatif_scales):
            raise ValueError("whatif_scales must be finite and non-negative")
        return self


# ------------------------------------------------------------------- analysis
def analyze_timing_budget(
    graph,
    options: TimingBudgetOptions | None = None,
    *,
    config: SimulationRunConfig | None = None,
    dvfs_tables: dict[str, DVFSTable] | None = None,
) -> dict[str, Any]:
    options = options or TimingBudgetOptions()
    dvfs_tables = dvfs_tables or {}
    base_config = (config or SimulationRunConfig()).model_copy(
        update={
            "include_timeline": True,
            "timeline_frame_count": options.frames,
            "debug_trace": False,
        }
    )
    plan = _plan(graph, options, base_config)
    rule = _run(graph, options, base_config, dvfs_tables, plan, rule_only=True)
    budget = _run(graph, options, base_config, dvfs_tables, plan, rule_only=False)
    report = _report(graph, options, plan, rule, budget, dvfs_tables)
    if options.include_whatif:
        report["whatif"] = whatif(graph, options, config=config, dvfs_tables=dvfs_tables)
    return report


def whatif(
    graph, options: TimingBudgetOptions, *, config=None, dvfs_tables=None
) -> list[dict[str, Any]]:
    """SW growth x EIS x statistic grid (summary rows only)."""

    rows = []
    for statistic in ("mean", "max"):
        for eis in ("on", "off"):
            for scale in options.whatif_scales:
                opts = options.model_copy(
                    update={
                        "statistic": statistic,
                        "eis": eis,
                        "runtime_scale": scale,
                        "include_whatif": False,
                    }
                )
                r = summarize(graph, opts, config=config, dvfs_tables=dvfs_tables)
                rows.append({"statistic": statistic, "eis": eis == "on", "scale": scale, **r})
    return rows


def summarize(
    graph, options: TimingBudgetOptions, *, config=None, dvfs_tables=None
) -> dict[str, Any]:
    full = analyze_timing_budget(
        graph,
        options.model_copy(update={"include_whatif": False}),
        config=config,
        dvfs_tables=dvfs_tables,
    )
    stages = {s["id"]: s for s in full["stages"]}
    ips = full["ips"]

    def stage_clock(stage: str) -> float | None:
        ip = stage_driver(ips, stage)
        return ip["set_clock_mhz"] if ip else None

    def stage_rule_clock(stage: str) -> float | None:
        ip = stage_driver(ips, stage)
        return ip["rule_clock_mhz"] if ip else None

    return {
        "verdict": full["verdict"],
        "eis_on": full["eis"]["on"],
        "stages": {
            k: {
                "sw_ms": v["sw_ms"],
                "budget_ms": v["budget_ms"],
                "hw_ms": v["hw_ms"],
                "feasible": v["feasible"],
            }
            for k, v in stages.items()
        },
        "nrt_driver": (stage_driver(ips, "nrt") or {}).get("node"),
        "nrt_clock_mhz": stage_clock("nrt"),
        "nrt_rule_clock_mhz": stage_rule_clock("nrt"),
        "post_clock_mhz": stage_clock("post"),
        "rt_clock_mhz": stage_clock("rt"),
        "interval_ok": full["intervals"]["ok"],
        "preview_interval_max_ms": full["intervals"]["preview"]["max_ms"],
        "video_interval_max_ms": full["intervals"]["video"]["max_ms"],
        "latency": full["latency"],
        "power": {k: full["power"][k] for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw")},
        "bw_total_mbs": full["bw"]["total_mbs"],
    }


# ------------------------------------------------------------------- planning
def _plan(graph, options: TimingBudgetOptions, config: SimulationRunConfig) -> dict[str, Any]:
    probe = _graph_copy(graph, options.statistic, 0.25)
    inputs = build_simulation_inputs(probe, config)
    period = 1000.0 / float(inputs.config.fps or config.fps or 30.0)
    h_blank = float(config.h_blank_margin)
    tasks = {str(t["id"]): t for t in inputs.timeline_tasks}
    edges = inputs.timeline_edges
    workloads = {w.node_id: w for w in inputs.workloads}
    for key in (*options.ip_overhead, *options.stage_overrides):
        if key not in tasks:
            raise ValueError(f"unknown timeline task: {key}")
    for key in options.ip_overhead:
        if key not in workloads:
            raise ValueError(f"ip_overhead target is not a HW workload: {key}")
    for key in (*options.task_adjustments, *options.task_latency):
        if key not in tasks or tasks[key].get("task_type") != "sw":
            raise ValueError(f"not a SW task: {key}")
    stage = _classify(tasks, edges, workloads, options.stage_overrides)
    profiles = {str(row["task"]): row for row in inputs.sw_task_timing}
    conditions = graph.variant.design_conditions or {}
    stabilization = conditions.get("stabilization")
    eis_tasks = [
        t
        for t, s in stage.items()
        if s == "post"
        and tasks[t].get("task_type") == "sw"
        and (
            "eis" in t.lower()
            or any(_GDC_RE.search(_edge_pair(e)[1]) for e in edges if _edge_pair(e)[0] == t)
        )
    ]
    eis_auto = bool(eis_tasks) and str(stabilization).strip().lower() not in {
        "",
        "none",
        "0",
        "false",
        "off",
    }
    eis_on = eis_auto if options.eis == "auto" else options.eis == "on"
    warnings: list[str] = []
    if options.eis == "on" and not eis_tasks:
        warnings.append(
            "EIS requested but the pipeline has no SW task feeding GDC; nothing to add."
        )
    sw_items: dict[str, list[dict[str, Any]]] = {s: [] for s in STAGES}
    edge_latency: dict[str, float] = {}
    for edge in edges:
        src, dst = _edge_pair(edge)
        if edge.get("latency_ms"):
            edge_latency[dst] = max(edge_latency.get(dst, 0.0), float(edge["latency_ms"]))
    for task_id, task in tasks.items():
        if task.get("task_type") != "sw":
            continue
        st = stage[task_id]
        if task_id in eis_tasks and not eis_on:
            continue
        runtime = _task_runtime(task_id, task, profiles, options)
        latency = _task_latency(task_id, profiles, edge_latency, options)
        if profiles.get(task_id, {}).get("includes_hw_nodes"):
            warnings.append(
                f"{task_id} is a SW stage that includes HW {profiles[task_id]['includes_hw_nodes']}; its time counts as SW."
            )
        sw_items[st].append(
            {
                "task": task_id,
                "kind": "sw",
                "runtime_ms": runtime,
                "latency_ms": latency,
                "source": str(profiles.get(task_id, {}).get("value_source") or "timeline"),
            }
        )
    for node, stat in options.ip_overhead.items():
        sw_items[stage[node]].append(
            {
                "task": node,
                "kind": "ip_overhead",
                "runtime_ms": stat.value(options.statistic),
                "latency_ms": 0.0,
                "source": "ip_overhead",
            }
        )
    margins: dict[str, float] = {}
    shared: dict[str, int] = {}
    budgets: dict[str, dict[str, Any]] = {}
    for st in STAGES:
        nodes = [n for n in workloads if stage.get(n) == st]
        sw_total = _critical_sw(sw_items[st], edges)
        if st in ("nrt", "post"):
            budget = period - sw_total
            margin = 1.0 - budget / ((1.0 + h_blank) * period)
            feasible = margin <= _MAX_MARGIN
            margin = min(_MAX_MARGIN, max(_MIN_MARGIN, margin))
        else:
            margin = options.rt_margin if st == "rt" else options.output_margin
            budget = (1.0 - margin) * period
            feasible = True
        budgets[st] = {
            "sw_ms": sw_total,
            "budget_ms": budget,
            "margin": margin,
            "feasible": feasible,
            "nodes": nodes,
        }
        # Streams time-multiplexed on one IP (dual/PIP: same resource_id) share its budget.
        share: dict[str, int] = {}
        for node in nodes:
            res = str(tasks[node].get("resource_id") or node) if node in tasks else node
            share[res] = share.get(res, 0) + 1
        for node in nodes:
            res = str(tasks[node].get("resource_id") or node) if node in tasks else node
            k = share[res]
            if k > 1:
                shared[node] = k
                margins[node] = min(_MAX_MARGIN, 1.0 - (1.0 - margin) / k)
            else:
                margins[node] = margin
    dual = {}
    for node, workload in workloads.items():
        if stage.get(node) == "output" and _ENCODER_RE.search(
            node + " " + str(workload.ip_ref or "")
        ):
            want = (
                workload.pixels >= UHD_PIXELS
                if options.mfc_dual == "auto"
                else options.mfc_dual == "on"
            )
            if want and "apv" not in (node + str(workload.ip_ref)).lower():
                dual[node] = 2
    if any(i["source"] == "assumed" for items in sw_items.values() for i in items):
        warnings.append(
            "SW timing contains 'assumed' values; replace with previous-project measurements."
        )
    explicit_resource = {
        tid: bool(((graph.variant.node_configs or {}).get(tid) or {}).get("timeline_resource_id"))
        for tid in tasks
    }
    return {
        "explicit_resource": explicit_resource,
        "shared": shared,
        "eis_tasks": eis_tasks,
        "period": period,
        "h_blank": h_blank,
        "stage": stage,
        "tasks": tasks,
        "sw_items": sw_items,
        "budgets": budgets,
        "margins": margins,
        "dual": dual,
        "eis_on": eis_on,
        "eis_auto": eis_auto,
        "stabilization": stabilization,
        "warnings": warnings,
    }


def _classify(tasks, edges, workloads, overrides) -> dict[str, Stage]:
    succ: dict[str, set[str]] = {}
    pred: dict[str, set[str]] = {}
    for edge in edges:
        a, b = _edge_pair(edge)
        succ.setdefault(a, set()).add(b)
        pred.setdefault(b, set()).add(a)
    rt = _sensor_synchronous(tasks, edges)
    stage: dict[str, Stage] = {}
    for tid, task in tasks.items():
        ref = (
            tid
            + " "
            + str(
                (workloads.get(tid).ip_ref if tid in workloads else "") or task.get("hw_name") or ""
            )
        )
        if tid in rt:
            stage[tid] = "rt"
        elif task.get("task_type") == "sw":
            continue
        elif _OUTPUT_RE.search(ref):
            stage[tid] = "output"
        elif _GDC_RE.search(ref):
            stage[tid] = "post"
        else:
            stage[tid] = "nrt"
    # SW gating NRT HW (ancestors) -> nrt; SW after NRT HW (EIS, blend, ...) or feeding GDC -> post;
    # SW after output HW (writer, storage) -> output.
    nrt_hw = [tid for tid, s in stage.items() if s == "nrt"]
    ancestors = _closure(nrt_hw, pred)
    descendants = _closure(nrt_hw, succ)
    for tid, task in tasks.items():
        if tid in stage:
            continue
        if _downstream_of(tid, pred, stage, "output"):
            stage[tid] = "output"
        elif tid in ancestors:
            stage[tid] = "nrt"
        elif tid in descendants or any(stage.get(s) == "post" for s in succ.get(tid, ())):
            stage[tid] = "post"
        else:
            stage[tid] = "nrt"
    stage.update(overrides)
    return stage


def _critical_sw(items: list[dict[str, Any]], edges: list) -> float:
    """Longest serial SW path in a stage (parallel chains, e.g. front/rear, do not add).

    Marks each item's ``critical`` flag. IP overhead items serialize with their IP
    and are added on top of the SW path.
    """
    sw = {i["task"]: i for i in items if i["kind"] == "sw"}
    succ: dict[str, list[str]] = {}
    indeg = {k: 0 for k in sw}
    for edge in edges:
        a, b = _edge_pair(edge)
        if a in sw and b in sw and b not in succ.get(a, []):
            succ.setdefault(a, []).append(b)
            indeg[b] += 1
    best: dict[str, float] = {}
    parent: dict[str, str | None] = {}
    order = [k for k, d in indeg.items() if d == 0]
    queue = list(order)
    for k in order:
        best[k] = sw[k]["runtime_ms"] + sw[k]["latency_ms"]
        parent[k] = None
    while queue:
        a = queue.pop(0)
        for b in succ.get(a, []):
            cand = best[a] + sw[b]["runtime_ms"] + sw[b]["latency_ms"]
            if cand > best.get(b, -1.0):
                best[b], parent[b] = cand, a
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)
    for i in items:
        i["critical"] = i["kind"] == "ip_overhead"
    if best:
        end = max(best, key=lambda k: best[k])
        node: str | None = end
        while node is not None:
            sw[node]["critical"] = True
            node = parent.get(node)
    overhead = sum(i["runtime_ms"] for i in items if i["kind"] == "ip_overhead")
    return (max(best.values()) if best else 0.0) + overhead


def _closure(start, adjacency) -> set[str]:
    seen: set[str] = set()
    queue = list(start)
    while queue:
        node = queue.pop()
        for nxt in adjacency.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _downstream_of(tid, pred, stage, target) -> bool:
    seen, queue = set(), list(pred.get(tid, ()))
    while queue:
        node = queue.pop()
        if node in seen:
            continue
        seen.add(node)
        if stage.get(node) == target:
            return True
        queue.extend(pred.get(node, ()))
    return False


def _task_runtime(task_id: str, task: dict, profiles: dict, options: TimingBudgetOptions) -> float:
    row = profiles.get(task_id)
    base = (
        float(row[f"{options.statistic}_ms"])
        if row and row.get(f"{options.statistic}_ms") is not None
        else float(task.get("duration_ms") or 0.0)
    )
    value = base * options.runtime_scale
    if task_id in options.task_adjustments:
        value = options.task_adjustments[task_id].apply(value)
    return value


def _task_latency(
    task_id: str, profiles: dict, edge_latency: dict, options: TimingBudgetOptions
) -> float:
    if task_id in options.task_latency:
        return options.task_latency[task_id].value(options.statistic) * options.latency_scale
    row = profiles.get(task_id) or {}
    for key in (
        f"start_latency_{options.statistic}_ms",
        "start_latency_mean_ms",
        "start_jitter_mean_ms",
    ):
        if row.get(key) is not None:
            return float(row[key]) * options.latency_scale
    return float(edge_latency.get(task_id, 0.0)) * options.latency_scale


# ------------------------------------------------------------------- running
def _run(graph, options, config, dvfs_tables, plan, *, rule_only: bool) -> dict[str, Any]:
    if rule_only:
        margins = {}
        for n in plan["margins"]:
            m = (
                options.rt_margin
                if plan["stage"][n] == "rt"
                else options.output_margin
                if plan["stage"][n] == "output"
                else 0.25
            )
            k = plan["shared"].get(n, 1)
            margins[n] = 1.0 - (1.0 - m) / k if k > 1 else m
    else:
        margins = plan["margins"]
    copy = _graph_copy(graph, options.statistic, margins)
    inputs = build_simulation_inputs(copy, config)
    for workload in inputs.workloads:
        cores = plan["dual"].get(workload.node_id)
        if cores:
            workload.width = max(1, workload.width // cores)
    _apply_sw(inputs, plan, options)
    result = run_simulation(inputs, dvfs_tables=dvfs_tables)
    return {"inputs": inputs, "result": result}


def _apply_sw(inputs: SimulationInputs, plan: dict, options: TimingBudgetOptions) -> None:
    items = {
        i["task"]: i for items in plan["sw_items"].values() for i in items if i["kind"] == "sw"
    }
    overhead = {
        i["task"]: i["runtime_ms"]
        for items in plan["sw_items"].values()
        for i in items
        if i["kind"] == "ip_overhead"
    }
    for task in inputs.timeline_tasks:
        tid = str(task["id"])
        if task.get("task_type") == "sw":
            own_stage = str(task.get("resource_id") or "").startswith("stage:")
            if not options.shared_cpu and not own_stage and not plan["explicit_resource"].get(tid):
                task["resource_id"] = f"CPU_{plan['stage'].get(tid, 'nrt').upper()}"
            if tid in items:
                task["duration_ms"] = max(_MIN_TASK_MS, items[tid]["runtime_ms"])
            else:  # EIS off
                task["duration_ms"] = _MIN_TASK_MS
            task["measured_duration"] = True
        elif tid in overhead:
            task["serial_overhead_ms"] = overhead[tid]
    for edge in inputs.timeline_edges:
        dst = _edge_pair(edge)[1]
        if dst in items:
            if items[dst]["latency_ms"] > 0 or edge.get("latency_ms"):
                edge["latency_ms"] = items[dst]["latency_ms"]
        elif edge.get("latency_ms") and dst in plan["eis_tasks"]:
            edge["latency_ms"] = 0.0


# ------------------------------------------------------------------ reporting
def _report(graph, options, plan, rule_run, run, dvfs_tables) -> dict[str, Any]:
    result: SimRunResult = run["result"]
    rule: SimRunResult = rule_run["result"]
    period = plan["period"]
    stage = plan["stage"]
    timing = {t.node_id: t for t in result.timing_breakdown}
    ips = []
    for node, res in result.resolved.items():
        cores = plan["dual"].get(node, 1)
        ips.append(
            {
                "node": node,
                "hw_name": res.hw_name,
                "stage": stage.get(node, "nrt"),
                "dvfs_group": res.dvfs_group,
                "cores": cores,
                "shared_streams": plan["shared"].get(node, 1),
                "rule_clock_mhz": round(rule.resolved[node].set_clock_mhz, 1)
                if node in rule.resolved
                else None,
                "required_clock_mhz": round(res.required_clock_mhz, 1),
                "set_clock_mhz": round(res.set_clock_mhz, 1),
                "dvfs_level": res.dvfs_level,
                "voltage_mv": round(res.set_voltage_mv, 2),
                "hw_ms": round(timing[node].hw_time_ms, 3) if node in timing else None,
                "power_mw": round(res.total_power_mw * cores, 3),
                "feasible": res.feasible,
                "infeasible_reason": res.infeasible_reason,
                "clock_reason": res.clock_correction_reason,
            }
        )
    # Stage HW time = busiest physical resource (streams sharing one IP add up).
    per_resource: dict[tuple[str, str], float] = {}
    for ip in ips:
        if ip["hw_ms"] is None:
            continue
        task = plan["tasks"].get(ip["node"], {})
        key = (ip["stage"], str(task.get("resource_id") or ip["node"]))
        per_resource[key] = per_resource.get(key, 0.0) + ip["hw_ms"]
    stage_hw: dict[str, float] = {}
    for (st, _res), value in per_resource.items():
        stage_hw[st] = max(stage_hw.get(st, 0.0), value)
    stages = []
    for st in STAGES:
        b = plan["budgets"][st]
        overhead = sum(i["runtime_ms"] for i in plan["sw_items"][st] if i["kind"] == "ip_overhead")
        stages.append(
            {
                "id": st,
                "name": STAGE_NAME[st],
                "nodes": b["nodes"],
                "sw_items": [
                    {k: (round(v, 4) if isinstance(v, float) else v) for k, v in i.items()}
                    for i in plan["sw_items"][st]
                ],
                "sw_ms": round(b["sw_ms"], 3),
                "budget_ms": round(b["budget_ms"], 3),
                "hw_ms": round(stage_hw.get(st, 0.0), 3),
                "overhead_ms": round(overhead, 3),
                "margin": round(b["margin"], 4),
                "feasible": b["feasible"],
                "fill_pct": round(100 * (b["sw_ms"] + stage_hw.get(st, 0.0)) / period, 1)
                if st in ("nrt", "post")
                else round(100 * stage_hw.get(st, 0.0) / period, 1),
            }
        )
    intervals, latency = _cadence(result, run["inputs"], plan, options)
    power, bw = _power_bw(result, plan, options, period)
    verdict = _verdict(stages, intervals, ips)
    return {
        "scenario_id": graph.scenario_id,
        "variant_id": graph.variant_id,
        "fps": round(1000.0 / period, 4),
        "period_ms": round(period, 4),
        "statistic": options.statistic,
        "eis": {
            "on": plan["eis_on"],
            "auto": plan["eis_auto"],
            "mode": options.eis,
            "stabilization": plan["stabilization"],
        },
        "mfc_dual": {k: v for k, v in plan["dual"].items()},
        "growth": {"runtime_scale": options.runtime_scale, "latency_scale": options.latency_scale},
        "dvfs": {"tables": sorted(dvfs_tables), "applied": bool(dvfs_tables)},
        "stages": stages,
        "ips": sorted(
            ips, key=lambda i: (STAGES.index(i["stage"]) if i["stage"] in STAGES else 9, i["node"])
        ),
        "intervals": intervals,
        "latency": latency,
        "power": power,
        "bw": bw,
        "verdict": verdict,
        "timeline": [
            {
                "node": str(e.node_id),
                "type": e.task_type,
                "frame": e.frame_index,
                "start_ms": round(e.start_ms, 3),
                "end_ms": round(e.end_ms, 3),
                "stage": stage.get(str(e.node_id), "nrt"),
            }
            for e in result.timeline_events
            if e.frame_index is not None and e.frame_index < options.timeline_frames
        ],
        "warnings": sorted(set(plan["warnings"] + list(result.warnings)))[:40],
    }


def _cadence(
    result: SimRunResult, inputs: SimulationInputs, plan: dict, options: TimingBudgetOptions
):
    period = plan["period"]
    by_node: dict[str, list] = {}
    for e in result.timeline_events:
        if e.frame_index is not None:
            by_node.setdefault(str(e.node_id), []).append(e)
    nodes = [str(t["id"]) for t in inputs.timeline_tasks]
    preview = next((n for n in nodes if _DISPLAY_RE.search(n)), None)
    video = next((n for n in nodes if _ENCODER_RE.search(n)), None)
    tol = options.interval_tolerance

    def series(node):
        if node is None or node not in by_node:
            return {"node": node, "values": [], "max_ms": None, "min_ms": None, "ok": None}
        events = sorted(by_node[node], key=lambda e: e.frame_index)
        ends = [e.end_ms for e in events]
        gaps = [b - a for a, b in zip(ends, ends[1:])]
        worst = max((abs(g - period) for g in gaps), default=0.0)
        return {
            "node": node,
            "values": [round(g, 4) for g in gaps],
            "max_ms": round(max(gaps), 4) if gaps else None,
            "min_ms": round(min(gaps), 4) if gaps else None,
            "ok": worst <= period * tol,
        }

    def lat(node):
        if node is None or node not in by_node:
            return None
        return round(
            max(e.end_ms - _frame_start(result, e.frame_index, period) for e in by_node[node]), 3
        )

    p, v = series(preview), series(video)
    ok = all(s["ok"] is not False for s in (p, v)) and any(s["ok"] is not None for s in (p, v))
    return (
        {"target_ms": round(period, 4), "tolerance": tol, "preview": p, "video": v, "ok": ok},
        {
            "preview_ms": lat(preview),
            "video_ms": lat(video),
            "preview_frames": None if lat(preview) is None else round(lat(preview) / period, 2),
            "video_frames": None if lat(video) is None else round(lat(video) / period, 2),
        },
    )


def _power_bw(result: SimRunResult, plan: dict, options: TimingBudgetOptions, period: float):
    stage = plan["stage"]
    tasks = plan["tasks"]
    hw_by_ip = {n: r.total_power_mw * plan["dual"].get(n, 1) for n, r in result.resolved.items()}
    busy = {
        i["task"]: i["runtime_ms"]
        for items in plan["sw_items"].values()
        for i in items
        if i["kind"] == "sw"
    }
    for tid, task in tasks.items():  # output-side SW (writer, storage) is CPU work too
        if task.get("task_type") == "sw" and tid not in busy and stage.get(tid) == "output":
            busy[tid] = float(task.get("duration_ms") or 0.0)
    cpu_by_task = {t: options.cpu.power_mw(ms, period) for t, ms in busy.items()}
    sw_nodes = {t for t, task in tasks.items() if task.get("task_type") == "sw"}
    bw_hw: dict[str, float] = {}
    bw_sw: dict[str, float] = {}
    bw_power_hw = bw_power_sw = 0.0
    for d in result.dma_breakdown:
        if d.node_id in sw_nodes:
            bw_sw[d.node_id] = bw_sw.get(d.node_id, 0.0) + d.bw_mbs
            bw_power_sw += d.bw_power_mw
        else:
            bw_hw[d.node_id] = bw_hw.get(d.node_id, 0.0) + d.bw_mbs
            bw_power_hw += d.bw_power_mw
    cpu = sum(cpu_by_task.values())
    hw = sum(hw_by_ip.values())
    bwp = bw_power_hw + bw_power_sw
    total = cpu + hw + bwp
    share = {
        k: (round(100 * v / total, 1) if total else 0.0)
        for k, v in (("cpu", cpu), ("hw", hw), ("bw", bwp))
    }
    bw_total = sum(bw_hw.values()) + sum(bw_sw.values())
    power = {
        "total_mw": round(total, 2),
        "cpu_mw": round(cpu, 2),
        "hw_mw": round(hw, 2),
        "bw_mw": round(bwp, 2),
        "bw_hw_mw": round(bw_power_hw, 2),
        "bw_sw_mw": round(bw_power_sw, 2),
        "share_pct": share,
        "hw_by_ip": {k: round(v, 3) for k, v in sorted(hw_by_ip.items(), key=lambda x: -x[1])},
        "cpu_by_task": {
            k: round(v, 3) for k, v in sorted(cpu_by_task.items(), key=lambda x: -x[1])
        },
        "cpu_busy_ms": round(sum(busy.values()), 3),
        "cpu_model": options.cpu.model_dump(),
        "zero_power_ips": sorted(n for n, v in hw_by_ip.items() if v <= 0),
    }
    bw = {
        "total_mbs": round(bw_total, 1),
        "hw_mbs": round(sum(bw_hw.values()), 1),
        "sw_mbs": round(sum(bw_sw.values()), 1),
        "hw_by_ip": {k: round(v, 1) for k, v in sorted(bw_hw.items(), key=lambda x: -x[1])},
        "sw_by_task": {k: round(v, 1) for k, v in sorted(bw_sw.items(), key=lambda x: -x[1])},
        "share_pct": {
            "hw": round(100 * sum(bw_hw.values()) / bw_total, 1) if bw_total else 0.0,
            "sw": round(100 * sum(bw_sw.values()) / bw_total, 1) if bw_total else 0.0,
        },
    }
    return power, bw


def _verdict(stages, intervals, ips) -> dict[str, Any]:
    reasons = []
    for s in stages:
        if not s["feasible"]:
            reasons.append(f"{s['name']}: SW {s['sw_ms']:.2f} ms leaves no HW budget")
    rt = next(s for s in stages if s["id"] == "rt")
    if rt["hw_ms"] > rt["budget_ms"] * 1.0001:
        reasons.append(f"RT HW {rt['hw_ms']:.2f} ms > 75% budget {rt['budget_ms']:.2f} ms")
    for key in ("preview", "video"):
        s = intervals[key]
        if s["ok"] is False:
            reasons.append(
                f"{key} interval {s['max_ms']:.3f} ms != {intervals['target_ms']:.3f} ms"
            )
    for ip in ips:
        if not ip["feasible"]:
            reasons.append(f"{ip['node']}: {ip['infeasible_reason']}")
    factor = None
    nrt = [ip for ip in ips if ip["stage"] == "nrt" and ip["rule_clock_mhz"]]
    if nrt:
        factor = max(ip["set_clock_mhz"] / ip["rule_clock_mhz"] for ip in nrt)
    if reasons:
        status = "fail"
    elif factor and factor > 1.05:
        status = "clock_up"
    else:
        status = "ok"
    return {
        "status": status,
        "reasons": reasons,
        "nrt_clock_factor": None if factor is None else round(factor, 3),
    }


# -------------------------------------------------------------------- helpers
def _graph_copy(graph, statistic: Statistic, margin: float | dict[str, float]):
    variant = deepcopy(graph.variant)
    variant.design_conditions = {**(variant.design_conditions or {}), "sw_timing_case": statistic}
    variant.node_configs = deepcopy(variant.node_configs or {})
    for node in graph.pipeline_nodes:
        node_id = str(node.get("id"))
        value = margin.get(node_id, 0.25) if isinstance(margin, dict) else margin
        variant.node_configs.setdefault(node_id, {}).setdefault("sim", {})["sw_margin"] = max(
            _MIN_MARGIN, float(value)
        )
    return replace(graph, variant=variant)


def _sensor_synchronous(tasks: dict, edges: list) -> set[str]:
    sources = {tid for tid, t in tasks.items() if t.get("constraint_type") == "source"}
    otf: dict[str, set[str]] = {}
    for edge in edges:
        if str(edge.get("type") or "").upper() == "OTF":
            a, b = _edge_pair(edge)
            otf.setdefault(a, set()).add(b)
            otf.setdefault(b, set()).add(a)
    seen, queue = set(sources), list(sources)
    while queue:
        node = queue.pop()
        for peer in otf.get(node, ()):
            if peer not in seen:
                seen.add(peer)
                queue.append(peer)
    return seen


def _frame_start(result: SimRunResult, frame_index: int, period: float) -> float:
    starts = [
        e.start_ms
        for e in result.timeline_events
        if e.constraint_type == "source" and e.frame_index == frame_index
    ]
    return min(starts) if starts else frame_index * period


def _edge_pair(edge: dict[str, Any]) -> tuple[str, str]:
    return str(edge.get("from") or edge.get("source")), str(edge.get("to") or edge.get("target"))


def stage_driver(ips: list[dict[str, Any]], stage: str) -> dict[str, Any] | None:
    """IP whose clock the stage budget moves most (max set/rule ratio, then longest HW time)."""
    rows = [
        ip
        for ip in ips
        if ip["stage"] == stage and ip.get("set_clock_mhz") and ip.get("rule_clock_mhz")
    ]
    if not rows:
        return None
    return max(
        rows,
        key=lambda ip: (
            round(ip["set_clock_mhz"] / ip["rule_clock_mhz"], 3),
            ip.get("hw_ms") or 0.0,
        ),
    )


DERIVED_VARIANT_MARKERS = ("-explored-", "-timing-min", "-timing-max")


def fleet_row(report: dict[str, Any]) -> dict[str, Any]:
    """Compact per-variant summary for the fleet view."""

    stages = {s["id"]: s for s in report["stages"]}

    def stage_clock(stage: str, key: str) -> float | None:
        ip = stage_driver(report["ips"], stage)
        return ip.get(key) if ip else None

    def stage_level(stage: str) -> int | None:
        ip = stage_driver(report["ips"], stage)
        return ip.get("dvfs_level") if ip else None

    return {
        "variant_id": report["variant_id"],
        "fps": report["fps"],
        "period_ms": report["period_ms"],
        "statistic": report["statistic"],
        "eis_on": report["eis"]["on"],
        "stabilization": report["eis"]["stabilization"],
        "mfc_dual": bool(report["mfc_dual"]),
        "stages": {
            k: {
                "sw_ms": v["sw_ms"],
                "budget_ms": v["budget_ms"],
                "hw_ms": v["hw_ms"],
                "feasible": v["feasible"],
            }
            for k, v in stages.items()
        },
        "clocks": {
            st: {
                "ip": (stage_driver(report["ips"], st) or {}).get("node"),
                "rule_mhz": stage_clock(st, "rule_clock_mhz"),
                "set_mhz": stage_clock(st, "set_clock_mhz"),
                "level": stage_level(st),
            }
            for st in STAGES
        },
        "intervals": {
            "ok": report["intervals"]["ok"],
            "preview_max_ms": report["intervals"]["preview"]["max_ms"],
            "video_max_ms": report["intervals"]["video"]["max_ms"],
        },
        "latency": report["latency"],
        "power": {
            k: report["power"][k] for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw", "share_pct")
        },
        "bw": {k: report["bw"][k] for k in ("total_mbs", "hw_mbs", "sw_mbs")},
        "verdict": report["verdict"],
    }
