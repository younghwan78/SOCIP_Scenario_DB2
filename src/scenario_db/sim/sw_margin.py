"""Timing-aware SW margin analysis.

Replaces the rule of thumb "HW time <= (1 - 0.25) x frame period" with a
margin derived from the pipeline timeline: previous-project SW task runtime,
SW event latency, per-IP serialized SW overhead (driver setup / IRQ completion)
and next-project SW growth.

Definitions (see docs/guides/sw-timing-margin.md):

* ``margin`` m is the existing clock margin: ``required_clock = pixels * fps /
  (1 - m) / ppc``, so an IP's HW time is ``(1 - m) * (1 + h_blank) * period``.
  The rule of thumb is m = 0.25.
* C1 (frame cycle / throughput): per resource, the per-frame busy time
  (HW time + serialized SW overhead, or the sum of SW tasks sharing one CPU
  resource) must fit the frame period. Deterministic and monotone in m.
* C2 (latency): sensor frame start -> sink completion within the sink budget
  (``latency_budget_frames`` x period). Applies to declared sinks (display)
  and to any sink listed in ``sink_budget_frames`` (e.g. storage_write).
  Shared-CPU contention makes C2 phase dependent, so feasibility in m is not
  guaranteed monotone.
* ``required margin`` m* is the lower edge of the feasible region that extends
  to the upper bound (grid scan + bisection refine), so an isolated feasible
  point below a failing one is reported but never selected.

The analysis is read-only: it never persists evidence or mutates the graph.
"""

from __future__ import annotations

import math
import random
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import (
    DVFSTable,
    SimRunResult,
    SimulationInputs,
    SimulationRunConfig,
    TimelineEvent,
)
from scenario_db.sim.runner import run_simulation

Statistic = Literal["min", "mean", "max"]
MAX_MONTE_CARLO_SAMPLES = 200
_MIN_MARGIN = 1e-6  # sim blocks treat a falsy margin as "unset"
_MIN_TASK_MS = 1e-6


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

    def sample(self, rng: random.Random) -> float:
        return triangular_sample(rng, self.min_ms, self.mean_ms, self.max_ms)


class IpSerialOverhead(BaseScenarioModel):
    """SW time that keeps one IP busy per frame outside its HW run."""

    setup: TimingStat | None = None
    completion: TimingStat | None = None
    source: str | None = None

    def value(self, statistic: Statistic) -> float:
        return sum(part.value(statistic) for part in (self.setup, self.completion) if part)

    def sample(self, rng: random.Random) -> float:
        return sum(part.sample(rng) for part in (self.setup, self.completion) if part)


class SwTaskAdjustment(BaseScenarioModel):
    scale: float | None = Field(default=None, ge=0)
    delta_ms: float | None = None

    @model_validator(mode="after")
    def _one(self) -> SwTaskAdjustment:
        if (self.scale is None) == (self.delta_ms is None):
            raise ValueError("choose exactly one of scale or delta_ms")
        return self

    def apply(self, value: float) -> float:
        return max(
            0.0,
            value * self.scale if self.scale is not None else value + float(self.delta_ms or 0.0),
        )


class ExtraSwTask(BaseScenarioModel):
    """Next-project SW task inserted between two existing timeline tasks."""

    id: str = Field(min_length=1)
    after: str
    before: str
    runtime: TimingStat
    latency_ms: float = Field(default=0.0, ge=0)
    resource_id: str = "CPU_CAMERA"


class SwGrowth(BaseScenarioModel):
    runtime_scale: float = Field(default=1.0, ge=0)
    latency_scale: float = Field(default=1.0, ge=0)
    overhead_scale: float = Field(default=1.0, ge=0)
    task_adjustments: dict[str, SwTaskAdjustment] = Field(default_factory=dict)
    extra_tasks: list[ExtraSwTask] = Field(default_factory=list, max_length=20)


class SwMarginConstraints(BaseScenarioModel):
    latency_budget_frames: float = Field(default=3.0, gt=0)
    sink_budget_frames: dict[str, float] = Field(default_factory=dict)
    cadence_tolerance: float = Field(default=1e-3, ge=0, le=0.2)
    frames: int = Field(default=12, ge=4, le=64)

    @model_validator(mode="after")
    def _positive(self) -> SwMarginConstraints:
        if any(v <= 0 for v in self.sink_budget_frames.values()):
            raise ValueError("sink_budget_frames must be positive")
        return self


class SwMarginOptions(BaseScenarioModel):
    statistic: Statistic = "max"
    rule_margin: float = Field(default=0.25, ge=0, lt=1)
    growth: SwGrowth = Field(default_factory=SwGrowth)
    growth_sweep: list[float] = Field(
        default_factory=lambda: [1.0, 1.1, 1.2, 1.3, 1.5], max_length=12
    )
    ip_overhead: dict[str, IpSerialOverhead] = Field(default_factory=dict)
    default_ip_overhead: IpSerialOverhead | None = None
    constraints: SwMarginConstraints = Field(default_factory=SwMarginConstraints)
    per_ip_plan: bool = True
    monte_carlo_samples: int = Field(default=0, ge=0, le=MAX_MONTE_CARLO_SAMPLES)
    seed: int = 0
    margin_upper_bound: float = Field(default=0.9, gt=0, lt=1)
    tolerance: float = Field(default=1e-3, gt=0, le=0.05)
    grid_step: float = Field(default=0.02, gt=0, le=0.1)
    # Above this margin the HW clock would have to rise > 1/(1-limit) x: not a clock problem.
    practical_margin_limit: float = Field(default=0.5, gt=0, lt=1)

    @model_validator(mode="after")
    def _sweep(self) -> SwMarginOptions:
        if any(not math.isfinite(v) or v < 0 for v in self.growth_sweep):
            raise ValueError("growth_sweep values must be finite and non-negative")
        if self.rule_margin >= self.margin_upper_bound:
            raise ValueError("rule_margin must be below margin_upper_bound")
        return self


def triangular_sample(rng: random.Random, low: float, mean: float, high: float) -> float:
    """Triangular draw whose mean equals ``mean`` (mode clamped into [low, high])."""
    if high <= low:
        return low
    mode = min(high, max(low, 3.0 * mean - low - high))
    return rng.triangular(low, high, mode)


# -------------------------------------------------------------------- results
@dataclass
class Evaluation:
    margin: float | dict[str, float]
    feasible: bool
    reasons: list[str]
    latency_ms: dict[str, float]
    latency_budget_ms: dict[str, float]
    sink_interval_ms: dict[str, float]
    latency_jitter_ms: dict[str, float]
    resource_load_ms: dict[str, float]
    set_clock_mhz: dict[str, float]
    core_power_mw: float
    total_power_mw: float
    result: SimRunResult = field(repr=False)
    overhead_ms: dict[str, float] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "margin": _round_margin(self.margin),
            "feasible": self.feasible,
            "reasons": self.reasons,
            "latency_ms": _round_map(self.latency_ms),
            "latency_budget_ms": _round_map(self.latency_budget_ms),
            "sink_interval_ms": _round_map(self.sink_interval_ms),
            "latency_jitter_ms": _round_map(self.latency_jitter_ms),
            "resource_load_ms": _round_map(self.resource_load_ms),
            "set_clock_mhz": _round_map(self.set_clock_mhz, 1),
            "core_power_mw": round(self.core_power_mw, 3),
            "total_power_mw": round(self.total_power_mw, 3),
        }


@dataclass
class _Context:
    graph: Any
    config: SimulationRunConfig
    dvfs_tables: dict[str, DVFSTable]
    options: SwMarginOptions
    period_ms: float
    h_blank: float
    workload_nodes: set[str]
    sensor_sync_nodes: set[str]
    sw_stats: dict[str, TimingStat]
    stage_tasks: set[str]
    warnings: list[str]
    evaluations: int = 0


# ------------------------------------------------------------------ analysis
def analyze_sw_margin(
    graph,
    options: SwMarginOptions | None = None,
    *,
    config: SimulationRunConfig | None = None,
    dvfs_tables: dict[str, DVFSTable] | None = None,
) -> dict[str, Any]:
    """Solve the SW timing margin of one scenario variant (read-only)."""

    options = options or SwMarginOptions()
    ctx = _context(graph, options, config or SimulationRunConfig(), dvfs_tables or {})
    growth = options.growth
    required = solve_uniform_margin(ctx, growth)
    rule = evaluate(ctx, options.rule_margin, growth)
    at_required = (
        evaluate(ctx, required["margin"], growth) if required["margin"] is not None else None
    )
    report: dict[str, Any] = {
        "scenario_id": graph.scenario_id,
        "variant_id": graph.variant_id,
        "fps": round(1000.0 / ctx.period_ms, 6),
        "period_ms": round(ctx.period_ms, 6),
        "h_blank_margin": ctx.h_blank,
        "statistic": options.statistic,
        "rule_margin": options.rule_margin,
        "growth": growth.model_dump(exclude_defaults=True),
        "constraints": options.constraints.model_dump(),
        "required": required,
        "rule": {
            **rule.summary(),
            "hw_time_limit_ms": round(_hw_time_limit(ctx, options.rule_margin), 3),
            "margin_gap": None
            if required["margin"] is None
            else round(options.rule_margin - required["margin"], 4),
            "verdict": _verdict(
                options.rule_margin,
                required["margin"],
                ctx.options.tolerance,
                options.practical_margin_limit,
            ),
        },
        "growth_headroom_at_rule": solve_growth_headroom(ctx, options.rule_margin, growth),
        "growth_sweep": [
            {
                "runtime_scale": scale,
                **_margin_only(solve_uniform_margin(ctx, _scaled_growth(growth, scale))),
            }
            for scale in options.growth_sweep
        ],
        "critical_path": critical_breakdown(ctx, at_required) if at_required else None,
        "ip_overhead_ms": _round_map(at_required.overhead_ms if at_required else rule.overhead_ms),
        "sw_tasks": _sw_task_rows(ctx, growth),
    }
    if at_required is not None:
        report["required"]["clocks_mhz"] = _round_map(at_required.set_clock_mhz, 1)
        report["required"]["core_power_mw"] = round(at_required.core_power_mw, 3)
        report["required"]["total_power_mw"] = round(at_required.total_power_mw, 3)
        report["power_delta_rule_minus_required_mw"] = round(
            rule.total_power_mw - at_required.total_power_mw, 3
        )
    if options.per_ip_plan and required["margin"] is not None:
        report["per_ip_plan"] = solve_per_ip_plan(ctx, growth)
    if options.monte_carlo_samples:
        report["monte_carlo"] = monte_carlo(ctx, growth)
    if not ctx.dvfs_tables:
        ctx.warnings.append(
            "No DVFS table: clocks are continuous and voltage stays at reference; power deltas reflect no voltage scaling."
        )
    if not options.ip_overhead and options.default_ip_overhead is None:
        ctx.warnings.append(
            "No per-IP serialized SW overhead given: C1 checks HW time only, so the margin reflects pipeline SW latency, not driver setup/IRQ cost."
        )
    report["warnings"] = sorted(set(ctx.warnings))
    report["evaluations"] = ctx.evaluations
    return report


def _context(graph, options: SwMarginOptions, config: SimulationRunConfig, dvfs_tables) -> _Context:
    probe_graph = _graph_copy(graph, options.statistic, _MIN_MARGIN + 0.1)
    run_config = config.model_copy(
        update={
            "include_timeline": True,
            "timeline_frame_count": options.constraints.frames,
            "debug_trace": False,
        }
    )
    inputs = build_simulation_inputs(probe_graph, run_config)
    fps = float(inputs.config.fps or run_config.fps or 30.0)
    task_ids = {str(t["id"]) for t in inputs.timeline_tasks}
    warnings: list[str] = []
    for node in {*options.ip_overhead, *options.growth.task_adjustments}:
        if node not in task_ids:
            raise ValueError(f"unknown timeline task: {node}")
    workload_nodes = {w.node_id for w in inputs.workloads}
    for node in options.ip_overhead:
        if node not in workload_nodes:
            raise ValueError(f"ip_overhead target is not a HW workload: {node}")
    sw_stats: dict[str, TimingStat] = {}
    stage_tasks: set[str] = set()
    for row in inputs.sw_task_timing:
        try:
            sw_stats[str(row["task"])] = TimingStat(
                min_ms=row["min_ms"], mean_ms=row["mean_ms"], max_ms=row["max_ms"]
            )
        except (KeyError, ValueError):
            continue
        if row.get("includes_hw_nodes"):
            stage_tasks.add(str(row["task"]))
            warnings.append(
                f"{row['task']} aggregates HW {row['includes_hw_nodes']}; SW growth scales the whole stage."
            )
    for extra in options.growth.extra_tasks:
        if extra.id in task_ids:
            raise ValueError(f"extra task id collides with timeline task: {extra.id}")
        if not any(_edge_pair(e) == (extra.after, extra.before) for e in inputs.timeline_edges):
            raise ValueError(
                f"extra task {extra.id}: no timeline edge {extra.after} -> {extra.before}"
            )
    if any(str(row.get("value_source")) == "assumed" for row in inputs.sw_task_timing):
        warnings.append(
            "Some SW task timing is 'assumed'; replace with previous-project measurements."
        )
    return _Context(
        graph=graph,
        config=run_config,
        dvfs_tables=dvfs_tables,
        options=options,
        period_ms=1000.0 / fps,
        h_blank=float(run_config.h_blank_margin),
        workload_nodes=workload_nodes,
        sensor_sync_nodes=_sensor_synchronous(inputs),
        sw_stats=sw_stats,
        stage_tasks=stage_tasks,
        warnings=warnings,
    )


def evaluate(
    ctx: _Context,
    margin: float | dict[str, float],
    growth: SwGrowth,
    *,
    sampled: dict[str, float] | None = None,
) -> Evaluation:
    """Run one timeline at ``margin`` (uniform or per node) and check C1/C2."""

    ctx.evaluations += 1
    options = ctx.options
    graph = _graph_copy(ctx.graph, options.statistic, margin)
    inputs = build_simulation_inputs(graph, ctx.config)
    overheads = _apply_sw_timing(ctx, inputs, growth, sampled or {})
    result = run_simulation(inputs, dvfs_tables=ctx.dvfs_tables)
    return _check(ctx, margin, result, inputs, overheads)


def solve_uniform_margin(
    ctx: _Context, growth: SwGrowth, *, sampled: dict[str, float] | None = None
) -> dict[str, Any]:
    solved = _robust_lower_edge(ctx, lambda m: evaluate(ctx, m, growth, sampled=sampled))
    margin = solved["value"]
    return {
        "margin": margin,
        "hw_time_limit_ms": None if margin is None else round(_hw_time_limit(ctx, margin), 3),
        "binding": solved["binding"],
        "status": solved["status"],
        "isolated_feasible": solved["isolated_feasible"],
    }


def _robust_lower_edge(ctx: _Context, feasible_at) -> dict[str, Any]:
    """Smallest x such that every grid point in [x, upper] is feasible.

    Grid scan from the upper bound down, then bisection inside the last gap.
    Isolated feasible points below the edge (phase luck) are reported only.
    """

    upper, step, tol = ctx.options.margin_upper_bound, ctx.options.grid_step, ctx.options.tolerance
    grid = [round(min(upper, i * step), 6) for i in range(int(upper / step) + 1)]
    if grid[-1] < upper:
        grid.append(upper)
    results = {x: feasible_at(x) for x in grid}
    if not results[upper].feasible:
        return {
            "value": None,
            "binding": results[upper].reasons,
            "status": "infeasible_at_upper_bound",
            "isolated_feasible": [],
        }
    edge_index = len(grid) - 1
    while edge_index > 0 and results[grid[edge_index - 1]].feasible:
        edge_index -= 1
    isolated = [round(x, 4) for x in grid[:edge_index] if results[x].feasible]
    if edge_index == 0:
        return {"value": 0.0, "binding": [], "status": "sw_negligible", "isolated_feasible": []}
    lo, hi = grid[edge_index - 1], grid[edge_index]
    binding = results[lo].reasons
    while hi - lo > tol:
        mid = (lo + hi) / 2
        evaluation = feasible_at(mid)
        if evaluation.feasible:
            hi = mid
        else:
            lo, binding = mid, evaluation.reasons
    return {
        "value": round(hi, 4),
        "binding": binding,
        "status": "solved",
        "isolated_feasible": isolated,
    }


def solve_per_ip_plan(ctx: _Context, growth: SwGrowth) -> dict[str, Any]:
    """Per-IP margin: C1 analytic floor per IP, then one shared lift for C2."""

    base = evaluate(ctx, 0.0, growth)
    floors: dict[str, float] = {}
    for node in sorted(ctx.workload_nodes):
        overhead = base.overhead_ms.get(node, 0.0)
        # (1 - m)(1 + h_blank) P + overhead <= P
        floor = 1.0 - (ctx.period_ms - overhead) / ((1.0 + ctx.h_blank) * ctx.period_ms)
        floors[node] = min(ctx.options.margin_upper_bound, max(0.0, floor))

    def plan(lift: float) -> dict[str, float]:
        return {node: max(floor, lift) for node, floor in floors.items()}

    solved = _robust_lower_edge(ctx, lambda lift: evaluate(ctx, plan(lift), growth))
    if solved["value"] is None:
        return {"status": "infeasible_at_upper_bound", "binding": solved["binding"]}
    lift = solved["value"]
    final = evaluate(ctx, plan(lift), growth)
    margins = plan(lift)
    return {
        "status": "solved",
        "latency_lift": round(lift, 4),
        "margins": {k: round(v, 4) for k, v in margins.items()},
        "cycle_floor": {k: round(v, 4) for k, v in floors.items()},
        "clocks_mhz": _round_map(final.set_clock_mhz, 1),
        "core_power_mw": round(final.core_power_mw, 3),
        "total_power_mw": round(final.total_power_mw, 3),
    }


def solve_growth_headroom(
    ctx: _Context, margin: float, growth: SwGrowth, *, max_scale: float = 3.0, step: float = 0.05
) -> dict[str, Any]:
    """Largest SW runtime+overhead scale s such that every s' <= s stays feasible at ``margin``."""

    if not evaluate(ctx, margin, _scaled_growth(growth, 0.0)).feasible:
        return {"max_runtime_scale": None, "status": "hw_only_infeasible"}
    last_ok = 0.0
    scale = step
    while scale <= max_scale + 1e-9:
        evaluation = evaluate(ctx, margin, _scaled_growth(growth, scale))
        if not evaluation.feasible:
            return {
                "max_runtime_scale": round(last_ok, 3),
                "status": "solved",
                "binding": evaluation.reasons,
            }
        last_ok = scale
        scale = round(scale + step, 6)
    return {"max_runtime_scale": max_scale, "status": "at_or_above_bound"}


def monte_carlo(ctx: _Context, growth: SwGrowth) -> dict[str, Any]:
    """Required margin distribution when SW timing is sampled per run.

    Each sample holds one draw per SW task / IP overhead for all frames
    (sustained condition), triangular with the recorded min/mean/max.
    """

    rng = random.Random(ctx.options.seed)
    margins: list[float] = []
    infeasible = 0
    for _ in range(ctx.options.monte_carlo_samples):
        sampled = {task: stat.sample(rng) for task, stat in ctx.sw_stats.items()}
        for node, overhead in _overhead_specs(ctx).items():
            sampled[f"overhead:{node}"] = overhead.sample(rng)
        for extra in growth.extra_tasks:
            sampled[f"extra:{extra.id}"] = extra.runtime.sample(rng)
        solved = solve_uniform_margin(ctx, growth, sampled=sampled)
        if solved["margin"] is None:
            infeasible += 1
        else:
            margins.append(solved["margin"])
    margins.sort()
    rule = ctx.options.rule_margin
    samples = ctx.options.monte_carlo_samples
    return {
        "samples": samples,
        "seed": ctx.options.seed,
        "infeasible_samples": infeasible,
        "p50": _quantile(margins, 0.5),
        "p90": _quantile(margins, 0.9),
        "p99": _quantile(margins, 0.99),
        "max": margins[-1] if margins else None,
        "rule_coverage": round(sum(1 for m in margins if m <= rule + 1e-12) / samples, 4)
        if samples
        else None,
    }


def critical_breakdown(ctx: _Context, evaluation: Evaluation) -> dict[str, Any]:
    """Split the worst sink latency into HW / SW / serialized overhead / wait."""

    events = {e.task_id: e for e in evaluation.result.timeline_events}
    worst = None
    for event in events.values():
        budget = evaluation.latency_budget_ms.get(str(event.node_id))
        if budget is None or event.frame_index is None:
            continue
        latency = event.end_ms - _frame_start(evaluation.result, event.frame_index, ctx.period_ms)
        key = latency / budget
        if worst is None or key > worst[0]:
            worst = (key, event, latency)
    if worst is None:
        return {}
    _, sink, latency = worst
    parts = {"hw_ms": 0.0, "sw_ms": 0.0, "serial_overhead_ms": 0.0, "wait_ms": 0.0}
    chain: list[str] = []
    current: TimelineEvent | None = sink
    frame_start = _frame_start(evaluation.result, sink.frame_index or 0, ctx.period_ms)
    # Walk the latest-finishing predecessor back to the frame start. Each task
    # contributes only the time after its predecessor finished, so OTF-overlapped
    # stages are not double counted and the parts sum to the sink latency.
    while current is not None:
        chain.append(str(current.node_id))
        preds = [events[p] for p in current.predecessors if p in events]
        parent = max(preds, key=lambda e: e.end_ms) if preds else None
        boundary = parent.end_ms if parent is not None else frame_start
        parts["wait_ms"] += max(0.0, current.start_ms - boundary)
        exclusive = max(0.0, current.end_ms - max(current.start_ms, boundary))
        if current.task_type == "sw":
            parts["sw_ms"] += exclusive
        else:
            overhead = min(exclusive, evaluation.overhead_ms.get(str(current.node_id), 0.0))
            parts["hw_ms"] += exclusive - overhead
            parts["serial_overhead_ms"] += overhead
        current = parent
    chain.reverse()
    total = sum(parts.values()) or 1.0
    return {
        "sink": sink.node_id,
        "frame_index": sink.frame_index,
        "latency_ms": round(latency, 3),
        "budget_ms": round(evaluation.latency_budget_ms[str(sink.node_id)], 3),
        **{k: round(v, 3) for k, v in parts.items()},
        "share_pct": {k.removesuffix("_ms"): round(100.0 * v / total, 1) for k, v in parts.items()},
        "chain": chain,
        "note": "Latest-finishing predecessor walk from the sink to the sensor frame start; parts sum to the latency.",
    }


# ------------------------------------------------------------------- helpers
def _graph_copy(graph, statistic: Statistic, margin: float | dict[str, float]):
    variant = deepcopy(graph.variant)
    variant.design_conditions = {**(variant.design_conditions or {}), "sw_timing_case": statistic}
    variant.node_configs = deepcopy(variant.node_configs or {})
    for node in graph.pipeline_nodes:
        node_id = str(node.get("id"))
        value = margin.get(node_id, 0.0) if isinstance(margin, dict) else margin
        variant.node_configs.setdefault(node_id, {}).setdefault("sim", {})["sw_margin"] = max(
            _MIN_MARGIN, float(value)
        )
    return replace(graph, variant=variant)


def _overhead_specs(ctx: _Context) -> dict[str, IpSerialOverhead]:
    specs: dict[str, IpSerialOverhead] = {}
    default = ctx.options.default_ip_overhead
    for node in ctx.workload_nodes:
        if node in ctx.options.ip_overhead:
            specs[node] = ctx.options.ip_overhead[node]
        elif default is not None and node not in ctx.sensor_sync_nodes:
            specs[node] = default
    return specs


def _apply_sw_timing(
    ctx: _Context, inputs: SimulationInputs, growth: SwGrowth, sampled: dict[str, float]
) -> dict[str, float]:
    statistic = ctx.options.statistic
    overheads: dict[str, float] = {}
    for task in inputs.timeline_tasks:
        task_id = str(task["id"])
        if task.get("task_type") == "sw":
            base = sampled.get(task_id, float(task.get("duration_ms") or 0.0))
            value = base * growth.runtime_scale
            if task_id in growth.task_adjustments:
                value = growth.task_adjustments[task_id].apply(value)
            # Keep a positive floor: zero-length tasks can stall the critical-path walk.
            task["duration_ms"] = max(_MIN_TASK_MS, value)
            task["measured_duration"] = True
    specs = _overhead_specs(ctx)
    for task in inputs.timeline_tasks:
        node = str(task.get("node_id") or task["id"])
        spec = specs.get(node)
        if spec is None or task.get("task_type") == "sw":
            continue
        base = sampled.get(f"overhead:{node}", spec.value(statistic))
        overhead = base * growth.overhead_scale
        task["serial_overhead_ms"] = overhead
        overheads[node] = overhead
    for edge in inputs.timeline_edges:
        if edge.get("latency_ms"):
            edge["latency_ms"] = float(edge["latency_ms"]) * growth.latency_scale
    for extra in growth.extra_tasks:
        runtime = max(
            _MIN_TASK_MS,
            (
                sampled.get(f"extra:{extra.id}", extra.runtime.value(statistic))
                * growth.runtime_scale
            ),
        )
        inputs.timeline_tasks.append(
            {
                "id": extra.id,
                "node_id": extra.id,
                "hw_name": extra.id.upper(),
                "task_type": "sw",
                "duration_ms": runtime,
                "measured_duration": True,
                "resource_id": extra.resource_id,
                "resource_capacity": 1,
            }
        )
        inputs.timeline_edges.append(
            {
                "from": extra.after,
                "to": extra.id,
                "type": "control",
                **(
                    {"latency_ms": extra.latency_ms * growth.latency_scale}
                    if extra.latency_ms
                    else {}
                ),
            }
        )
        inputs.timeline_edges.append({"from": extra.id, "to": extra.before, "type": "control"})
    return overheads


def _check(
    ctx: _Context,
    margin,
    result: SimRunResult,
    inputs: SimulationInputs,
    overheads: dict[str, float],
) -> Evaluation:
    period = ctx.period_ms
    constraints = ctx.options.constraints
    tol = constraints.cadence_tolerance
    reasons: list[str] = []
    if not result.feasible:
        reasons.append(f"clock: {result.infeasible_reason or 'DVFS/IP max clock exceeded'}")
    # C1: per-resource busy time within one frame (mid frame avoids warm-up).
    frames = sorted({e.frame_index for e in result.timeline_events if e.frame_index is not None})
    probe_frame = frames[len(frames) // 2] if frames else None
    load: dict[str, float] = {}
    for event in result.timeline_events:
        if (
            event.frame_index != probe_frame
            or not event.resource_id
            or event.constraint_type == "source"
        ):
            continue
        load[event.resource_id] = load.get(event.resource_id, 0.0) + (event.end_ms - event.start_ms)
    for resource, busy in sorted(load.items()):
        if busy > period * (1 + tol):
            reasons.append(f"C1 load {resource}: {busy:.3f} > {period:.3f} ms/frame")
    # C2: latency for constrained sinks; interval reported for information.
    constrained, leaves = _sink_nodes(inputs, constraints)
    by_node: dict[str, list] = {}
    for event in result.timeline_events:
        by_node.setdefault(str(event.node_id), []).append(event)
    latency: dict[str, float] = {}
    budget: dict[str, float] = {}
    interval: dict[str, float] = {}
    jitter: dict[str, float] = {}
    for sink in sorted(constrained | leaves):
        events = sorted(
            (e for e in by_node.get(sink, []) if e.frame_index is not None),
            key=lambda e: e.frame_index,
        )
        if not events:
            continue
        latency[sink] = max(e.end_ms - _frame_start(result, e.frame_index, period) for e in events)
        steady = events[len(events) // 2 :]
        if len(steady) >= 2:
            interval[sink] = _slope(
                [float(e.frame_index) for e in steady], [e.end_ms for e in steady]
            )
            lat = [e.end_ms - _frame_start(result, e.frame_index, period) for e in steady]
            jitter[sink] = max(lat) - min(lat)
        if sink not in constrained:
            continue
        budget[sink] = (
            constraints.sink_budget_frames.get(sink, constraints.latency_budget_frames) * period
        )
        if latency[sink] > budget[sink] * (1 + 1e-9):
            reasons.append(f"C2 latency {sink}: {latency[sink]:.2f} > {budget[sink]:.2f} ms")
    return Evaluation(
        margin=margin,
        feasible=not reasons,
        reasons=reasons,
        latency_ms=latency,
        latency_budget_ms=budget,
        sink_interval_ms=interval,
        latency_jitter_ms=jitter,
        resource_load_ms=load,
        set_clock_mhz={k: v.set_clock_mhz for k, v in result.resolved.items()},
        core_power_mw=sum(v.total_power_mw for v in result.resolved.values()),
        total_power_mw=result.total_power_mw,
        result=result,
        overhead_ms=overheads,
    )


def _sink_nodes(
    inputs: SimulationInputs, constraints: SwMarginConstraints
) -> tuple[set[str], set[str]]:
    """(latency-constrained sinks, other leaf tasks reported for information)."""
    task_ids = {str(t["id"]) for t in inputs.timeline_tasks}
    sources = {str(t["id"]) for t in inputs.timeline_tasks if t.get("constraint_type") == "source"}
    has_successor = {_edge_pair(e)[0] for e in inputs.timeline_edges}
    leaves = {t for t in task_ids if t not in has_successor} - sources
    declared = {str(t["id"]) for t in inputs.timeline_tasks if t.get("constraint_type") == "sink"}
    constrained = (declared | set(constraints.sink_budget_frames)) & task_ids
    return constrained, leaves - constrained


def _sensor_synchronous(inputs: SimulationInputs) -> set[str]:
    sources = {str(t["id"]) for t in inputs.timeline_tasks if t.get("constraint_type") == "source"}
    otf: dict[str, set[str]] = {}
    for edge in inputs.timeline_edges:
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


def _scaled_growth(growth: SwGrowth, scale: float) -> SwGrowth:
    return growth.model_copy(
        update={
            "runtime_scale": growth.runtime_scale * scale,
            "overhead_scale": growth.overhead_scale * scale,
        }
    )


def _hw_time_limit(ctx: _Context, margin: float) -> float:
    return (1.0 - margin) * (1.0 + ctx.h_blank) * ctx.period_ms


def _verdict(rule: float, required: float | None, tol: float, practical_limit: float = 1.0) -> str:
    if required is None:
        return "infeasible"
    if required > practical_limit:
        return "clock_unreachable"
    if required > rule + tol:
        return "rule_insufficient"
    if required < rule - 0.05:
        return "rule_over_provisioned"
    return "rule_adequate"


def _sw_task_rows(ctx: _Context, growth: SwGrowth) -> list[dict[str, Any]]:
    rows = []
    for task, stat in sorted(ctx.sw_stats.items()):
        value = stat.value(ctx.options.statistic) * growth.runtime_scale
        if task in growth.task_adjustments:
            value = growth.task_adjustments[task].apply(value)
        rows.append(
            {
                "task": task,
                **stat.model_dump(),
                "applied_ms": round(value, 4),
                "stage_includes_hw": task in ctx.stage_tasks,
            }
        )
    for extra in growth.extra_tasks:
        rows.append(
            {
                "task": extra.id,
                **extra.runtime.model_dump(),
                "applied_ms": round(
                    extra.runtime.value(ctx.options.statistic) * growth.runtime_scale, 4
                ),
                "extra": True,
            }
        )
    return rows


def _margin_only(solved: dict[str, Any]) -> dict[str, Any]:
    return {
        "margin": solved["margin"],
        "hw_time_limit_ms": solved["hw_time_limit_ms"],
        "status": solved["status"],
        "binding": solved["binding"][:3],
    }


def _slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope: steady-state completion interval (robust to alternating jitter)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0.0


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    index = min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))
    return values[index]


def _round_map(values: dict[str, float], digits: int = 3) -> dict[str, float]:
    return {k: round(float(v), digits) for k, v in sorted(values.items())}


def _round_margin(margin: float | dict[str, float]):
    return (
        {k: round(v, 4) for k, v in margin.items()}
        if isinstance(margin, dict)
        else round(float(margin), 4)
    )
