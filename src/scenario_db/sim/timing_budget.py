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
import random
import re
from copy import deepcopy
from dataclasses import replace
from typing import Any, Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.cpu_power import PROFILER_COEFF as _CPU_PROFILER_COEFF
from scenario_db.sim.models import CpuProfile, DVFSTable, SimRunResult, SimulationInputs, SimulationRunConfig
from scenario_db.sim.power_params import effective_power_params
from scenario_db.sim.runner import run_simulation

Statistic = Literal["min", "mean", "max"]
Stage = Literal["rt", "nrt", "post", "output"]
STAGES: tuple[Stage, ...] = ("rt", "nrt", "post", "output")
STAGE_NAME = {"rt": "RT", "nrt": "NRT", "post": "Post-NRT (EIS/SW → GDC)", "output": "Output"}
_MIN_MARGIN = 1e-6
_MIN_TASK_MS = 1e-6
_MAX_MARGIN = 0.95
UHD_PIXELS = 3840 * 2160
# Linux EM / exynos-cpu-profiler coefficients from ip-cpu-s5e9965 (uW per MHz per V^2);
# shared with the simulation runner's CPU model (sim/cpu_power.py).
PROFILER_COEFF = list(_CPU_PROFILER_COEFF)
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

    cluster: int = Field(default=1, ge=0)
    freq_mhz: float = Field(default=2000.0, gt=0)
    volt_v: float = Field(default=0.80, gt=0)
    coeff_uw_per_mhz_v2: list[float] = Field(default_factory=lambda: list(PROFILER_COEFF), min_length=1)
    source: str = "ip-cpu-s5e9965 profiler coefficients; cluster/freq/volt assumed"

    @model_validator(mode="after")
    def _valid_power(self) -> CpuPowerConfig:
        if any(not math.isfinite(v) or v <= 0 for v in [self.freq_mhz, self.volt_v, *self.coeff_uw_per_mhz_v2]):
            raise ValueError("CPU power parameters must be finite and positive")
        if self.cluster >= len(self.coeff_uw_per_mhz_v2):
            raise ValueError("CPU cluster index is out of range")
        return self

    @classmethod
    def from_params(cls, params) -> CpuPowerConfig | None:
        """CPU power config from a ``power_model_params`` document (None if it has no cpu block).

        Unset fields keep the class defaults; ``source`` records the params id.
        """
        cpu = params.cpu
        if not cpu.clusters and all(value is None for value in (cpu.default_cluster, cpu.freq_mhz, cpu.volt_v)):
            return None
        values: dict[str, Any] = {
            "source": f"{params.params_ref}" + (f" ({cpu.source})" if cpu.source else ""),
        }
        if cpu.clusters:
            # EM-table clusters become the equivalent coefficient at the default frequency.
            from scenario_db.sim.cpu_power import CpuPowerModel

            model = CpuPowerModel.from_params(params)
            # The budget evaluates at one shared configured voltage. Fold each
            # cluster's actual OPP voltage into its coefficient at that voltage.
            values["coeff_uw_per_mhz_v2"] = [
                cluster.core_mw(model.freq_mhz, model.fallback_mv) * 1000.0 / (model.freq_mhz * model.volt_v**2)
                for cluster in model.clusters
            ]
            values["cluster"] = model.default_cluster
        if cpu.default_cluster is not None:
            values["cluster"] = cpu.default_cluster
        if cpu.freq_mhz is not None:
            values["freq_mhz"] = cpu.freq_mhz
        if cpu.volt_v is not None:
            values["volt_v"] = cpu.volt_v
        return cls(**values)

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
    # Measured SW runtime per task (min / mean / max ms) replacing the variant's assumed timing (S4: measurement
    # as input). ``statistic`` picks the value; ``runtime_scale`` / ``task_adjustments`` still apply on top.
    task_runtime: dict[str, TimingStat] = Field(default_factory=dict)
    ip_overhead: dict[str, TimingStat] = Field(default_factory=dict)
    stage_overrides: dict[str, Stage] = Field(default_factory=dict)
    rt_margin: float = Field(default=0.25, ge=0, lt=1)
    output_margin: float = Field(default=0.25, ge=0, lt=1)
    mfc_dual: Literal["auto", "on", "off"] = "auto"
    interval_tolerance: float = Field(default=1e-3, gt=0, le=0.05)
    frames: int = Field(default=12, ge=4, le=64)
    # TIM-09: leading output intervals excluded from the cadence verdict (pipeline fill / AE-AWB settle).
    # 0 = every interval judged (previous behaviour); jitter / drop statistics are reported either way.
    warmup_frames: int = Field(default=0, ge=0, le=16)
    timeline_frames: int = Field(default=6, ge=1, le=32)
    # Stage model: each stage's SW runs on its own thread/core. True keeps the
    # scenario's CPU resource (e.g. one CPU_CAMERA) so cross-stage contention shows.
    shared_cpu: bool = False
    # Throughput model of the NRT / Post stages.
    #   "stage"     (legacy): SW + HW of a stage must fit one frame period -> HW clocks raised to
    #               period - SW (the stage behaves like one frame-synchronous block).
    #   "pipelined": stages are decoupled by M2M buffers. Each IP keeps the rule clock (period x
    #               (1 - rt_margin)), each SW task must fit one period on its own thread; a chain longer
    #               than the period only adds latency. fps is judged by the output interval.
    throughput_model: Literal["stage", "pipelined"] = "stage"
    cpu: CpuPowerConfig = Field(default_factory=CpuPowerConfig)
    # CPU term: "flat" = coeff*f*V^2*util at one OPP (default); "profile" = measured per-frame CPU profile
    # replayed through EAS + schedutil with SW growth (sim/cpu_scenario.py). The service resolves
    # ``cpu_profile_ref`` (or the variant's newest measured profile) into ``cpu_profile``.
    cpu_model: Literal["flat", "profile"] = "flat"
    cpu_profile_ref: str | None = None
    cpu_profile: CpuProfile | None = None
    cpu_bw_source: Literal["model", "measured"] = "measured"   # with cpu_model=profile: CPU BW from bus bytes
    cpu_bw_scale: float = Field(default=1.0, gt=0, le=10)
    include_whatif: bool = False
    whatif_scales: list[float] = Field(
        default_factory=lambda: [1.0, 1.1, 1.2, 1.3, 1.4, 1.5], max_length=12
    )

    @model_validator(mode="after")
    def _scales(self) -> TimingBudgetOptions:
        if any(not math.isfinite(v) or v < 0 or v > 10 for v in self.whatif_scales):
            raise ValueError("whatif_scales must be finite and in [0, 10]")
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
    params = effective_power_params(config) if config is not None else None
    if params is not None and "cpu" not in options.model_fields_set:
        # Explicit options.cpu still wins; otherwise CPU coefficients come from data.
        cpu_from_params = CpuPowerConfig.from_params(params)
        if cpu_from_params is not None:
            options = options.model_copy(update={"cpu": cpu_from_params})
    dvfs_tables = dvfs_tables or {}
    base_config = (config or SimulationRunConfig()).model_copy(
        update={
            "include_timeline": True,
            # the drawn timeline needs a few frames beyond the last one shown (steady state)
            "timeline_frame_count": max(options.frames, options.timeline_frames + 4),
            "debug_trace": False,
        }
    )
    plan = _plan(graph, options, base_config)
    rule = _run(graph, options, base_config, dvfs_tables, plan, rule_only=True)
    budget = _run(graph, options, base_config, dvfs_tables, plan, rule_only=False)
    report = _report(graph, options, plan, rule, budget, dvfs_tables)
    report["dvfs"]["overrides"] = dict(base_config.dvfs_overrides)
    report["dvfs"]["ladders"] = dvfs_ladders(report["ips"], dvfs_tables, base_config.asv_group)
    if options.cpu_model == "profile":
        _profile_cpu(report, options, params, config)
    if options.include_whatif:
        report["whatif"] = whatif(graph, options, config=config, dvfs_tables=dvfs_tables)
    return report


def budget_simulation(graph, options: TimingBudgetOptions, *, config: SimulationRunConfig | None = None,
                      dvfs_tables: dict[str, DVFSTable] | None = None) -> SimRunResult:
    """The budget run of ``analyze_timing_budget`` (clocks and SW of the chosen condition) as a simulation result,
    e.g. to keep it as simulation evidence."""
    options = options.model_copy(update={"include_whatif": False})
    base_config = (config or SimulationRunConfig()).model_copy(
        update={"include_timeline": True, "timeline_frame_count": max(options.frames, options.timeline_frames + 4),
                "debug_trace": False})
    plan = _plan(graph, options, base_config)
    return _run(graph, options, base_config, dvfs_tables or {}, plan, rule_only=False)["result"]


def dvfs_ladders(ips: list[dict[str, Any]], tables: dict[str, DVFSTable], asv: int) -> dict[str, list[dict[str, Any]]]:
    """Selectable levels per DVFS domain used by this variant (slow -> fast), for a level override."""
    out: dict[str, list[dict[str, Any]]] = {}
    for g in sorted({ip["dvfs_group"] for ip in ips if ip.get("dvfs_group") in tables}):
        out[g] = [{"level": lv.level, "mhz": lv.speed_mhz, "mv": tables[g].voltage_for(lv, asv) or None}
                  for lv in sorted(tables[g].levels, key=lambda lv: lv.speed_mhz)]
    return out


def _sw_ranges(plan: dict, options: TimingBudgetOptions) -> dict[str, tuple[float, float, float]]:
    """Per SW task (min, mode, max) runtime for per-frame sampling; mode keeps the measured mean of a triangular
    distribution (mean = (min + mode + max) / 3). Tasks without a min/max profile stay fixed."""
    out: dict[str, tuple[float, float, float]] = {}
    for items in plan["sw_items"].values():
        for item in items:
            if item["kind"] != "sw":
                continue
            row = plan["profiles"].get(item["task"]) or {}
            if item["task"] in options.task_runtime:
                row = options.task_runtime[item["task"]].model_dump()
            vals = [row.get(k) for k in ("min_ms", "mean_ms", "max_ms")]
            if any(v is None for v in vals) or float(vals[2]) <= float(vals[0]):
                continue
            lo, mean, hi = (float(v) * options.runtime_scale for v in vals)
            adj = options.task_adjustments.get(item["task"])
            if adj is not None:
                lo, mean, hi = adj.apply(lo), adj.apply(mean), adj.apply(hi)
            mode = min(hi, max(lo, 3 * mean - lo - hi))
            out[item["task"]] = (lo, mode, hi)
    return out


def interval_distribution(
    graph, options: TimingBudgetOptions, *, config: SimulationRunConfig | None = None,
    dvfs_tables: dict[str, DVFSTable] | None = None, trials: int = 8, frames: int = 24, seed: int = 7,
) -> dict[str, Any]:
    """Output interval / latency spread when every SW task varies frame to frame within its measured min..max.

    Clocks follow the chosen condition (same plan as the budget report); each trial re-runs the timeline with
    per-frame SW durations drawn from a triangular(min, mode, max) distribution that keeps the measured mean.
    Report only: the verdict of the budget report is not changed.
    """
    options = options.model_copy(update={"include_whatif": False})
    dvfs_tables = dvfs_tables or {}
    base_config = (config or SimulationRunConfig()).model_copy(
        update={"include_timeline": True, "timeline_frame_count": frames, "debug_trace": False})
    plan = _plan(graph, options, base_config)
    period = plan["period"]
    ranges = _sw_ranges(plan, options)
    rng = random.Random(seed)
    skip = min(max(options.warmup_frames, 2), max(frames - 3, 0))
    tol = options.interval_tolerance
    streams: dict[str, dict[str, Any]] = {}
    fixed: list[str] = []
    for _ in range(trials):
        inputs = _budget_inputs(graph, options, base_config, plan, plan["margins"])
        fixed = sorted(str(t["id"]) for t in inputs.timeline_tasks if t.get("task_type") == "sw" and str(t["id"]) not in ranges)
        for task in inputs.timeline_tasks:
            r = ranges.get(str(task["id"]))
            if r is not None:
                task["duration_by_frame"] = [max(_MIN_TASK_MS, rng.triangular(r[0], r[2], r[1])) for _ in range(frames)]
        result = run_simulation(inputs, dvfs_tables=dvfs_tables)
        by_node: dict[str, list] = {}
        for e in result.timeline_events:
            if e.frame_index is not None:
                by_node.setdefault(str(e.node_id), []).append(e)
        for t in inputs.timeline_tasks:
            node = str(t["id"])
            kind = "preview" if _DISPLAY_RE.search(node) else "video" if _ENCODER_RE.search(node) else None
            if kind is None or node not in by_node:
                continue
            ev = sorted(by_node[node], key=lambda e: e.frame_index)
            acc = streams.setdefault(node, {"node": node, "kind": kind, "intervals": [], "latency": []})
            ends = [e.end_ms for e in ev]
            acc["intervals"] += [round(b - a, 4) for a, b in zip(ends[skip:], ends[skip + 1:])]
            acc["latency"] += [round(e.end_ms - _frame_start(result, e.frame_index, period), 4) for e in ev[skip:]]
    rows = []
    for acc in streams.values():
        iv = acc["intervals"]
        drops = sum(max(0, round(g / period) - 1) for g in iv if g > 1.5 * period)
        rows.append(acc | {"drops": int(drops),
                           "off_cadence_pct": round(100.0 * sum(abs(g - period) > period * tol for g in iv) / len(iv), 2) if iv else None})
    rows.sort(key=lambda r: (r["kind"] != "preview", r["node"]))
    return {"period_ms": round(period, 4), "trials": trials, "frames": frames, "warmup_excluded": skip, "tolerance": tol,
            "method": "per-frame SW runtime ~ triangular(min, mode, max), mean kept; clocks fixed by the condition",
            "varied": sorted(ranges), "fixed": fixed, "streams": rows}


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
        "domains": {
            st: [{k: d[k] for k in ("domain", "ip", "rule_mhz", "required_mhz", "set_mhz", "level")}
                 for d in full.get("stage_domains", {}).get(st, [])]
            for st in ("rt", "nrt", "post", "output")
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
    # pipelined: SW tasks on the same CPU resource (shared_cpu, or one declared timeline_resource_id) serialize —
    # their per-frame sum must fit the period even though each task alone does (no free extra cores).
    cpu_group: dict[str, str] = {}
    if options.throughput_model == "pipelined":
        for st in ("nrt", "post"):
            for i in sw_items[st]:
                if i["kind"] != "sw":
                    continue
                declared = ((graph.variant.node_configs or {}).get(i["task"]) or {}).get("timeline_resource_id")
                cpu_group[i["task"]] = "CPU (shared_cpu)" if options.shared_cpu else str(declared or i["task"])
    group_load: dict[str, float] = {}
    group_tasks: dict[str, list[str]] = {}
    for st in ("nrt", "post"):
        for i in sw_items[st]:
            g = cpu_group.get(i["task"]) if i["kind"] == "sw" else None
            if g is not None:
                group_load[g] = group_load.get(g, 0.0) + i["runtime_ms"]
                group_tasks.setdefault(g, []).append(i["task"])
    for st in STAGES:
        nodes = [n for n in workloads if stage.get(n) == st]
        sw_total = _critical_sw(sw_items[st], edges)
        longest_sw = max((i["runtime_ms"] for i in sw_items[st]), default=0.0)
        cpu_groups: list[dict[str, Any]] = []
        if st in ("nrt", "post") and options.throughput_model == "pipelined":
            margin = options.rt_margin
            budget = (1.0 - margin) * period
            mine = {cpu_group[i["task"]] for i in sw_items[st] if i["task"] in cpu_group}
            cpu_groups = [{"resource": g, "tasks": group_tasks[g], "load_ms": round(group_load[g], 3)}
                          for g in sorted(mine) if len(group_tasks[g]) > 1]
            cpu_load = max((group_load[g] for g in mine), default=0.0)
            feasible = longest_sw <= period and cpu_load <= period
        elif st in ("nrt", "post"):
            budget = period - sw_total
            margin = 1.0 - budget / ((1.0 + h_blank) * period)
            feasible = margin <= _MAX_MARGIN
            margin = min(_MAX_MARGIN, max(_MIN_MARGIN, margin))
        else:
            margin = options.rt_margin if st == "rt" else options.output_margin
            budget = (1.0 - margin) * period
            feasible = True
        budgets[st] = {
            "cpu_groups": cpu_groups,
            "longest_sw_ms": longest_sw,
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
        "profiles": profiles,
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
    if task_id in options.task_runtime:
        row = options.task_runtime[task_id].model_dump()
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
                else options.rt_margin  # NRT/Post rule reference follows the SW margin rule
            )
            k = plan["shared"].get(n, 1)
            margins[n] = 1.0 - (1.0 - m) / k if k > 1 else m
    else:
        margins = plan["margins"]
    inputs = _budget_inputs(graph, options, config, plan, margins)
    result = run_simulation(inputs, dvfs_tables=dvfs_tables)
    return {"inputs": inputs, "result": result}


def _budget_inputs(graph, options, config, plan, margins) -> SimulationInputs:
    copy = _graph_copy(graph, options.statistic, margins)
    inputs = build_simulation_inputs(copy, config)
    for workload in inputs.workloads:
        cores = plan["dual"].get(workload.node_id)
        if cores:
            workload.width = max(1, workload.width // cores)
    _apply_sw(inputs, plan, options)
    return inputs


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
                pipelined = options.throughput_model == "pipelined" and plan["stage"].get(tid) in ("nrt", "post")
                # pipelined: every SW task is its own thread (frame N+1 can start while N is downstream)
                task["resource_id"] = f"CPU_{tid}" if pipelined else f"CPU_{plan['stage'].get(tid, 'nrt').upper()}"
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
    workloads = {w.node_id: w for w in run["inputs"].workloads}
    ips = []
    for node, res in result.resolved.items():
        cores = plan["dual"].get(node, 1)
        basis = _clock_basis(res, workloads.get(node), stage.get(node, "nrt"), dvfs_tables)
        ips.append(
            {
                **basis,
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
                "rule_dvfs_level": rule.resolved[node].dvfs_level if node in rule.resolved else None,
                # False when the IP's DVFS group has no table (level cannot be named, voltage is the default)
                "dvfs_table": bool(res.dvfs_group) and res.dvfs_group in dvfs_tables,
                "voltage_mv": round(res.set_voltage_mv, 2),
                "hw_ms": round(timing[node].hw_time_ms, 3) if node in timing else None,
                # OTF-linked across DVFS domains: hw_ms is the group's time; standalone = this IP alone
                "otf_group": timing[node].otf_group if node in timing else None,
                "standalone_hw_ms": round(timing[node].standalone_hw_time_ms, 3)
                if node in timing and timing[node].standalone_hw_time_ms is not None else None,
                "power_mw": round(res.total_power_mw * cores, 3),
                # v2-vf clock term inputs (0 / None under v1) for analytic re-scaling.
                "clock_power_fraction": res.clock_power_fraction or 0.0,
                "ref_clock_mhz": round(res.clock_ref_mhz, 3),
                "clock_overhead_mw": round(res.clock_overhead_mw * cores, 3),
                "clock_gating_eff": res.clock_gating_eff,
                "power_gating_eff": res.power_gating_eff,
                "leakage_power_mw": round(res.leakage_power_mw * cores, 3),
                "dvfs_promotion": res.dvfs_promotion,
                "feasible": res.feasible,
                "infeasible_reason": res.infeasible_reason,
                "clock_reason": res.clock_correction_reason,
            }
        )
    # IPs lifted by a shared DVFS domain: name the domain member that sets the level.
    by_group: dict[str, list[dict[str, Any]]] = {}
    for ip in ips:
        if ip["dvfs_group"]:
            by_group.setdefault(ip["dvfs_group"], []).append(ip)
    for members in by_group.values():
        leader = max(members, key=lambda m: m["own_required_mhz"])
        for m in members:
            m["domain_leader"] = leader["node"] if m["set_reason"] == "domain" else None
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
                "throughput": options.throughput_model if st in ("nrt", "post") else "frame",
                "longest_sw_ms": round(b["longest_sw_ms"], 3),
                "cpu_groups": b.get("cpu_groups", []),
                "chain_ms": round(b["sw_ms"] + stage_hw.get(st, 0.0), 3),
                "fill_pct": round(100 * (b["sw_ms"] + stage_hw.get(st, 0.0)) / period, 1)
                if st in ("nrt", "post")
                else round(100 * stage_hw.get(st, 0.0) / period, 1),
            }
        )
    intervals, latency = _cadence(result, run["inputs"], plan, options)
    power, bw = _power_bw(result, plan, options, period)
    bw["peak"] = _peak_bw(ips, bw, period)
    domains = {st: stage_domains(ips, st) for st in STAGES}
    verdict = _verdict(stages, intervals, ips, domains, period)
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
        "sw_margin": {"rt": options.rt_margin, "output": options.output_margin},
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
        "stage_domains": domains,
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
        skip = min(options.warmup_frames, max(len(gaps) - 1, 0))
        judged = gaps[skip:]
        worst = max((abs(g - period) for g in judged), default=0.0)
        return {
            "node": node,
            "values": [round(g, 4) for g in gaps],
            "max_ms": round(max(gaps), 4) if gaps else None,
            "min_ms": round(min(gaps), 4) if gaps else None,
            "ok": worst <= period * tol,
            **_interval_stats(gaps, period, tol, skip),
        }

    def lat(node):
        if node is None or node not in by_node:
            return None
        return round(
            max(e.end_ms - _frame_start(result, e.frame_index, period) for e in by_node[node]), 3
        )

    p, v = series(preview), series(video)
    # every terminal stream counts (dual / PIP / multi-encoder): the first display / encoder alone is not enough
    extra = [n for n in nodes if n not in (preview, video) and (_DISPLAY_RE.search(n) or _ENCODER_RE.search(n))]
    streams = [{"kind": "preview" if _DISPLAY_RE.search(n) else "video", **series(n)} for n in extra]
    streams = [x for x in streams if x["ok"] is not None]
    ok = (all(s["ok"] is not False for s in (p, v, *streams))
          and any(s["ok"] is not None for s in (p, v)))
    return (
        {"target_ms": round(period, 4), "tolerance": tol, "preview": p, "video": v, "streams": streams, "ok": ok},
        {
            "preview_ms": lat(preview),
            "video_ms": lat(video),
            "preview_frames": None if lat(preview) is None else round(lat(preview) / period, 2),
            "video_frames": None if lat(video) is None else round(lat(video) / period, 2),
        },
    )


def _interval_stats(gaps: list[float], period: float, tol: float, skip: int) -> dict[str, Any]:
    """TIM-09: jitter (std / p95 |gap - period|), drops (a gap of ~k periods = k-1 missing frames) and the
    natural warm-up (leading intervals off-cadence before the first on-cadence one). Report only - ``ok`` above
    stays the verdict; ``skip`` = intervals excluded by ``warmup_frames``."""
    if not gaps:
        return {"jitter_ms": None, "p95_dev_ms": None, "p99_dev_ms": None, "max_dev_ms": None, "duration_ms": 0.0,
                "drops": 0, "warmup_observed": 0, "warmup_excluded": 0}
    judged = gaps[skip:] or gaps
    mean = sum(judged) / len(judged)
    std = (sum((g - mean) ** 2 for g in judged) / len(judged)) ** 0.5
    devs = sorted(abs(g - period) for g in judged)
    def pct(q: float) -> float:
        return devs[min(len(devs) - 1, int(round(q * (len(devs) - 1))))]
    p95 = pct(0.95)
    drops = sum(max(0, round(g / period) - 1) for g in judged if g > 1.5 * period)
    lead = next((i for i, g in enumerate(gaps) if abs(g - period) <= period * tol), len(gaps))
    return {"jitter_ms": round(std, 4), "p95_dev_ms": round(p95, 4), "p99_dev_ms": round(pct(0.99), 4),
            "max_dev_ms": round(devs[-1], 4), "duration_ms": round(sum(judged), 3), "drops": int(drops),
            "warmup_observed": lead, "warmup_excluded": skip}


def _peak_bw(ips: list[dict[str, Any]], bw: dict[str, Any], period: float) -> dict[str, Any]:
    """Average vs peak traffic (TIM-08). Average = bytes/frame x fps; an IP moves the same bytes inside its active
    time, so its peak ~ average x period / hw_ms. Raising its clock shortens hw_ms: average unchanged, peak up.
    ``stage_mbs`` = the stage's IPs streaming together; ``upper_mbs`` = all stages overlapping (pipelined bound)."""
    by_ip: dict[str, float] = {}
    stage_of: dict[str, str] = {}
    for ip in ips:
        avg = bw["hw_by_ip"].get(ip["node"])
        hw = ip.get("standalone_hw_ms") or ip.get("hw_ms")
        if avg and hw and hw > 0:
            by_ip[ip["node"]] = round(avg * min(period / hw, 1000.0), 1)
            stage_of[ip["node"]] = ip["stage"]
    by_stage: dict[str, float] = {}
    for node, mbs in by_ip.items():
        by_stage[stage_of[node]] = round(by_stage.get(stage_of[node], 0.0) + mbs, 1)
    return {"by_ip": dict(sorted(by_ip.items(), key=lambda x: -x[1])), "by_stage": by_stage,
            "max_stage_mbs": max(by_stage.values(), default=0.0), "upper_mbs": round(sum(by_stage.values()), 1),
            "avg_mbs": bw["total_mbs"]}


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
        if d.node_id in sw_nodes or d.node_id.startswith("cpu."):
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


def _verdict(stages, intervals, ips, domains=None, period: float | None = None) -> dict[str, Any]:
    limit = period if period else float("inf")
    reasons = []
    for s in stages:
        if not s["feasible"] and s.get("throughput") == "pipelined":
            over = [g for g in s.get("cpu_groups") or [] if g["load_ms"] > limit]
            if s["longest_sw_ms"] > limit or not s.get("cpu_groups"):
                reasons.append(f"{s['name']}: SW task {s['longest_sw_ms']:.2f} ms > frame period (한 thread가 1 frame 안에 못 끝남)")
            for g in over:
                reasons.append(f"{s['name']}: CPU {g['resource']}의 SW 합 {g['load_ms']:.2f} ms > frame period "
                               f"(같은 thread/core: {', '.join(g['tasks'])})")
        elif not s["feasible"]:
            reasons.append(f"{s['name']}: SW {s['sw_ms']:.2f} ms leaves no HW budget")
    rt = next(s for s in stages if s["id"] == "rt")
    if rt["hw_ms"] > rt["budget_ms"] * 1.0001:
        pct = round(100 * (1.0 - float(rt.get("margin", 0.25))))
        reasons.append(f"RT HW {rt['hw_ms']:.2f} ms > {pct}% budget {rt['budget_ms']:.2f} ms")
    for key in ("preview", "video"):
        s = intervals[key]
        if s["ok"] is False:
            reasons.append(
                f"{key} interval {s['max_ms']:.3f} ms != {intervals['target_ms']:.3f} ms"
            )
    for s in intervals.get("streams") or []:
        if s["ok"] is False:
            reasons.append(f"{s['node']} ({s['kind']}) interval {s['max_ms']:.3f} ms != {intervals['target_ms']:.3f} ms")
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
    notes = []
    period = intervals.get("target_ms") or 0.0
    for s in stages:
        if s.get("throughput") == "pipelined" and period and s["chain_ms"] > period * 1.0001:
            extra = math.ceil(s["chain_ms"] / period) - 1
            notes.append(f"{s['name']}: SW+HW {s['chain_ms']:.1f} ms > period {period:.1f} ms → buffering으로 latency +{extra} frame "
                         "(fps는 출력 간격으로 판정)")
    for st in ("nrt", "post"):
        for d in (domains or {}).get(st, []):
            if d["rule_mhz"] and d["set_mhz"] > d["rule_mhz"] * 1.05:
                lv = f" (L{d['rule_level']}→L{d['level']})" if d["level"] is not None and d["rule_level"] is not None else ""
                if d["required_mhz"] > d["rule_mhz"]:
                    notes.append(f"{st.upper()} {d['domain']}: 필요 {d['required_mhz']:.1f} MHz > rule {d['rule_mhz']:.0f} → {d['set_mhz']:.0f} MHz{lv}")
                else:  # lifted by another IP of the shared DVFS domain
                    by = f" ({d['domain_leader'].upper()})" if d.get("domain_leader") else ""
                    notes.append(f"{st.upper()} {d['domain']}: domain 공유{by}로 {d['set_mhz']:.0f} MHz{lv} (자체 필요 {d['required_mhz']:.1f})")
    return {
        "status": status,
        "reasons": reasons,
        "notes": notes,
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
    """IP whose clock the stage budget moves most (max set/rule ratio, then own need, then HW time).

    IPs whose time is counted inside a SW stage (``included_stage_budget``) never drive the stage.
    """
    rows = [
        ip
        for ip in ips
        if ip["stage"] == stage and ip.get("set_clock_mhz") and ip.get("rule_clock_mhz")
        and ip.get("basis") != "stage_budget"
    ]
    if not rows:
        return None
    return max(
        rows,
        key=lambda ip: (
            round(ip["set_clock_mhz"] / ip["rule_clock_mhz"], 3),
            ip.get("own_required_mhz") or 0.0,
            ip.get("hw_ms") or 0.0,
            ip.get("standalone_hw_ms") is None,   # OTF pacer (sets the group time) over a waiting member
        ),
    )


def stage_domains(ips: list[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    """One row per DVFS domain used by the stage (NRT = CAM + INTCAM …): its clock, need and quantisation."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for ip in ips:
        if ip["stage"] == stage:
            groups.setdefault(ip.get("dvfs_group") or ip["node"], []).append(ip)
    out = []
    for domain, members in groups.items():
        timed = [m for m in members if m.get("basis") != "stage_budget"] or members
        driver = max(timed, key=lambda m: (m.get("own_required_mhz") or 0.0, m.get("hw_ms") or 0.0))
        need = max((m.get("own_required_mhz") or 0.0) for m in timed)
        out.append({
            "domain": domain,
            "ip": driver["node"],
            "nodes": sorted(m["node"] for m in members),
            "rule_mhz": driver.get("rule_clock_mhz"),
            "required_mhz": round(need, 1),
            "set_mhz": driver["set_clock_mhz"],
            "level": driver.get("dvfs_level"),
            "rule_level": driver.get("rule_dvfs_level"),
            "next_mhz": driver.get("next_level_mhz"),
            "headroom_pct": round((driver["set_clock_mhz"] / need - 1) * 100, 1) if need > 0 else None,
            "hw_ms": max((m.get("hw_ms") or 0.0) for m in timed),
            "basis": driver.get("basis"),
            "set_reason": driver.get("set_reason"),
            "domain_leader": driver.get("domain_leader"),
        })
    return sorted(out, key=lambda d: (-(d["set_mhz"] or 0), d["domain"]))


_EPS_MHZ = 1e-6
_SENSOR_KINDS = ("vvalid_stream", "mipi_ingress", "otf_align")


def _clock_basis(res, workload, stage: str, dvfs_tables: dict[str, DVFSTable]) -> dict[str, Any]:
    """What decided this IP's clock: its own need (binding constraint) and why the set clock is higher."""
    base = float(res.base_required_clock_mhz or 0.0)
    cands: list[tuple[str, float]] = [("budget" if stage in ("nrt", "post") else "rule", base)]
    for c in (workload.clock_constraints if workload is not None else []):
        cands.append((c.kind, float(c.mhz)))
    if res.manual_clock_mhz:
        cands.append(("manual", float(res.manual_clock_mhz)))
    kind, own = max(cands, key=lambda kv: kv[1])
    if workload is not None and workload.readout_clocked and kind in ("vvalid_stream", "otf_align"):
        kind = "sensor_readout"
    set_mhz = float(res.set_clock_mhz)
    table = dvfs_tables.get(res.dvfs_group or "")
    reason, next_mhz = "exact", None
    if table is not None and table.levels:
        speeds = sorted(lv.speed_mhz for lv in table.levels if lv.speed_mhz > 0)
        own_level = next((v for v in speeds if v >= own - _EPS_MHZ), None)
        next_mhz = next((v for v in speeds if v > set_mhz + _EPS_MHZ), None)
        if own_level is not None and set_mhz > own_level + _EPS_MHZ:
            reason = "domain"
        elif speeds and own < speeds[0] - _EPS_MHZ and set_mhz <= speeds[0] + _EPS_MHZ:
            reason = "dvfs_floor"
        elif set_mhz > own + _EPS_MHZ:
            reason = "dvfs_step"
    elif set_mhz > own + _EPS_MHZ:
        reason = "domain"
    return {
        "own_required_mhz": round(own, 1),
        "basis": kind,
        "set_reason": reason,
        "next_level_mhz": next_mhz,
        "sensor_readout_ms": round(workload.sensor_readout_ms, 3) if workload is not None and workload.sensor_readout_ms else None,
    }


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
                "domain": (stage_driver(report["ips"], st) or {}).get("dvfs_group"),
                "domains": [{k: d[k] for k in ("domain", "ip", "rule_mhz", "required_mhz", "set_mhz", "level")}
                            for d in report.get("stage_domains", {}).get(st, [])],
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


def _profile_cpu(report: dict[str, Any], options: TimingBudgetOptions, params: Any, config: SimulationRunConfig | None) -> None:
    """``cpu_model: profile``: CPU power / BW from the measured profile; the flat numbers stay as *_flat."""
    from scenario_db.sim.cpu_power import CpuPowerModel
    from scenario_db.sim.cpu_scenario import apply_profile_cpu

    profile = options.cpu_profile or (config.cpu_profile if config is not None else None)
    note = None
    if profile is None:
        note = "cpu_model=profile but no measured CPU profile was resolved; flat CPU model kept"
    elif params is None or not params.cpu.clusters:
        note = "cpu_model=profile needs power_model_params with cpu.clusters; flat CPU model kept"
    if note:
        report["power"]["cpu_profile"] = {"kind": "flat", "note": note}
        return
    try:
        apply_profile_cpu(report, profile=profile, model=CpuPowerModel.from_params(params), growth=options.runtime_scale,
                          bw_source=options.cpu_bw_source, cpu_bw_scale=options.cpu_bw_scale,
                          profile_ref=options.cpu_profile_ref)
    except ValueError as exc:
        report["power"]["cpu_profile"] = {"kind": "flat", "note": f"profile CPU model failed: {exc}; flat CPU model kept"}


# ------------------------------------------------------------ DVFS level what-if
def _stage_slack(report: dict[str, Any]) -> dict[str, float]:
    """SW time still available per stage at the current clocks (ms; negative = over).

    RT / Output: HW budget left ((1-margin) period - HW). NRT / Post: "stage" model = period - (SW + HW);
    "pipelined" = period - the longest single SW task (each SW task is its own thread).
    """
    period = float(report["period_ms"])
    out: dict[str, float] = {}
    for s in report["stages"]:
        if s["id"] in ("nrt", "post"):
            used = s.get("longest_sw_ms", s["sw_ms"]) if s.get("throughput") == "pipelined" else s["sw_ms"] + s["hw_ms"]
            out[s["id"]] = round(period - used, 3)
        else:
            out[s["id"]] = round(s["budget_ms"] - s["hw_ms"], 3)
    return out


def _brief(report: dict[str, Any]) -> dict[str, Any]:
    p, b = report["power"], report["bw"]
    return {"total_mw": p["total_mw"], "cpu_mw": p["cpu_mw"], "hw_mw": p["hw_mw"], "bw_mw": p["bw_mw"], "bw_mbs": b["total_mbs"],
            "peak_stage_mbs": (b.get("peak") or {}).get("max_stage_mbs"), "peak_upper_mbs": (b.get("peak") or {}).get("upper_mbs"),
            "verdict": report["verdict"]["status"], "reasons": report["verdict"]["reasons"][:3],
            "intervals_ok": report["intervals"]["ok"], "latency_ms": report["latency"],
            "slack_ms": _stage_slack(report),
            "stage_hw_ms": {s["id"]: s["hw_ms"] for s in report["stages"]}}


def _dpeak(brief: dict[str, Any], base: dict[str, Any]) -> float | None:
    a, b = brief.get("peak_stage_mbs"), base.get("peak_stage_mbs")
    return round(a - b, 1) if a is not None and b is not None else None


def dvfs_level_whatif(graph, options: TimingBudgetOptions, *, config: SimulationRunConfig | None = None,
                      dvfs_tables: dict[str, DVFSTable] | None = None, shifts: tuple[int, ...] = (-2, -1, 1, 2),
                      domains: list[str] | None = None,
                      combos: list[dict[str, int]] | None = None) -> dict[str, Any]:
    """Pin one DVFS domain k levels faster (+) / slower (-) than the resolved level and re-run the budget.

    ``combos`` (TIM-05): several domains moved together, e.g. ``{"CAM": -1, "INTCAM": -1}`` (``{"*": -1}`` = every domain); a shift past the lowest /
    highest OPP is reported as a boundary row (``boundary``) instead of being dropped.

    Answers the routine project question "if we raise / lower CAM by one level, what happens to the SW margin,
    power and BW?". Every row is a full timing-budget run with ``config.dvfs_overrides`` for that domain.
    """
    tables = dvfs_tables or {}
    config = config or SimulationRunConfig()
    opts = options.model_copy(update={"include_whatif": False})
    base = analyze_timing_budget(graph, opts, config=config, dvfs_tables=tables)
    found: dict[str, dict[str, Any]] = {}
    for ip in base["ips"]:
        g = ip.get("dvfs_group")
        if not g or g not in tables or ip.get("dvfs_level") is None:
            continue
        d = found.setdefault(g, {"domain": g, "level": ip["dvfs_level"], "mhz": ip["set_clock_mhz"], "mv": ip["voltage_mv"],
                                 "stages": set(), "ips": []})
        d["stages"].add(ip["stage"])
        d["ips"].append(ip["node"])
    base_brief = _brief(base)
    rows: list[dict[str, Any]] = []
    combo_rows: list[dict[str, Any]] = []
    for g, info in sorted(found.items()):
        if domains and g not in domains:
            continue
        ladder = sorted(tables[g].levels, key=lambda lv: lv.speed_mhz)      # slow -> fast
        idx = next((i for i, lv in enumerate(ladder) if lv.level == info["level"]), None)
        if idx is None:
            continue
        for k in shifts:
            j = idx + k
            if not 0 <= j < len(ladder):
                edge = ladder[0] if j < 0 else ladder[-1]
                rows.append({"domain": g, "shift": k, "level": None, "mhz": None,
                             "boundary": "최저 OPP" if j < 0 else "최고 OPP",
                             "error": f"{'최저' if j < 0 else '최고'} OPP L{edge.level} ({edge.speed_mhz:g} MHz)에서 더 {'내릴' if j < 0 else '올릴'} level 없음"})
                continue
            target = ladder[j]
            cfg = config.model_copy(update={"dvfs_overrides": {**config.dvfs_overrides, g: target.level}})
            try:
                rep = analyze_timing_budget(graph, opts, config=cfg, dvfs_tables=tables)
            except ValueError as exc:
                rows.append({"domain": g, "shift": k, "level": target.level, "mhz": target.speed_mhz, "error": str(exc)})
                continue
            brief = _brief(rep)
            rows.append({"domain": g, "shift": k, "level": target.level, "mhz": target.speed_mhz, **brief,
                         "delta_mw": round(brief["total_mw"] - base_brief["total_mw"], 2),
                         "delta_hw_mw": round(brief["hw_mw"] - base_brief["hw_mw"], 2),
                         "delta_bw_mw": round(brief["bw_mw"] - base_brief["bw_mw"], 2),
                         "delta_mbs": round(brief["bw_mbs"] - base_brief["bw_mbs"], 1),
                         "delta_peak_mbs": _dpeak(brief, base_brief),
                         "delta_slack_ms": {s: round(v - base_brief["slack_ms"].get(s, 0.0), 3) for s, v in brief["slack_ms"].items()}})
    for combo in combos or []:
        if "*" in combo:  # every domain of this variant moved together
            combo = {g: combo["*"] for g in found} | {g: k for g, k in combo.items() if g != "*"}
        overrides: dict[str, int] = {}
        label, problem = [], None
        for g, k in sorted(combo.items()):
            if g not in found:
                problem = f"{g}: 이 variant에서 level을 정할 수 없는 domain"
                break
            ladder = sorted(tables[g].levels, key=lambda lv: lv.speed_mhz)
            idx = next((i for i, lv in enumerate(ladder) if lv.level == found[g]["level"]), None)
            j = None if idx is None else idx + k
            if j is None or not 0 <= j < len(ladder):
                problem = f"{g} {k:+d}: OPP 경계 밖"
                break
            overrides[g] = ladder[j].level
            label.append(f"{g} L{ladder[j].level}")
        row: dict[str, Any] = {"combo": dict(sorted(combo.items())), "label": " + ".join(label) or None}
        if problem:
            rows_combo = row | {"error": problem, "boundary": "경계" if "경계" in problem else None}
            combo_rows.append(rows_combo)
            continue
        cfg = config.model_copy(update={"dvfs_overrides": {**config.dvfs_overrides, **overrides}})
        try:
            rep_c = analyze_timing_budget(graph, opts, config=cfg, dvfs_tables=tables)
        except ValueError as exc:
            combo_rows.append(row | {"error": str(exc)})
            continue
        brief = _brief(rep_c)
        combo_rows.append(row | brief | {
            "delta_mw": round(brief["total_mw"] - base_brief["total_mw"], 2),
            "delta_hw_mw": round(brief["hw_mw"] - base_brief["hw_mw"], 2),
            "delta_bw_mw": round(brief["bw_mw"] - base_brief["bw_mw"], 2),
            "delta_mbs": round(brief["bw_mbs"] - base_brief["bw_mbs"], 1),
            "delta_peak_mbs": _dpeak(brief, base_brief),
            "delta_slack_ms": {s: round(v - base_brief["slack_ms"].get(s, 0.0), 3) for s, v in brief["slack_ms"].items()}})
    return {"base": base_brief, "fps": base["fps"], "period_ms": base["period_ms"],
            "throughput_model": options.throughput_model, "combos": combo_rows,
            "domains": [{**{k: v for k, v in d.items() if k != "stages"}, "stages": sorted(d["stages"])} for d in found.values()],
            "rows": rows}
