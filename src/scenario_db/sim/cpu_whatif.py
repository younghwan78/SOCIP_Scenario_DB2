"""CPU placement / frequency what-if from a measured per-frame profile.

No time series is needed: every task is reduced to per-frame demand measured
on a base cluster (cycles, stall cycles, bus bytes), and a candidate placement
is evaluated in steady state per frame.

Time model (stall split): on the base cluster c0 at its mean frequency f0

    core_cycles = cycles - stall_cycles         (scale with IPC and frequency)
    stall_ms    = stall_cycles / f0             (memory time, frequency-invariant)

on a target cluster c at frequency f with SW growth g:

    t(f)  = g * core_cycles * ipc_rel(c0) / ipc_rel(c) / f  +  g * stall_ms
    busy  = t(f) * f  cycles  ->  energy = busy * P_core(f) / f

Per cluster the OPP is the lowest-power one that meets every task budget
(``budgets_ms``) and ``sum t <= util_cap * cores * period`` (and each task
fits in one core, t <= period). Static power = cores * leak(V) * (active +
idle * (1 - power_gating_eff)); idle clusters keep only the gated leakage.
The DSU follows the busiest cluster's utilisation. CPU memory traffic =
bus bytes * growth * fps * ``cpu_bw_scale`` (e.g. a different L3/SLC).

Assumptions to calibrate in-house: stall time is frequency-invariant,
IPC ratio is per core type, a task runs on one cluster.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from scenario_db.sim.cpu_power import OTHER_TASK, ClusterModel, CpuPowerModel


@dataclass(frozen=True)
class WhatIfSpec:
    growth: dict[str, float] = field(default_factory=dict)       # task -> instruction scale
    default_growth: float = 1.0
    candidates: dict[str, list[str]] = field(default_factory=dict)  # task -> target clusters
    budgets_ms: dict[str, float] = field(default_factory=dict)   # task -> max time per frame
    util_cap: float = 0.8
    power_gating_eff: float = 0.9
    cpu_bw_scale: float = 1.0
    max_cases: int = 5000


@dataclass
class _Demand:
    task: str
    core_cycles: float        # at IPC of the base cluster
    stall_ms: float
    bus_bytes: float
    base_cluster: str
    base_ipc_rel: float
    threads: dict[str, float] | None = None   # thread -> cycles on base_cluster


def _mean_mhz(residency: dict[float, float] | None, fallback: float) -> float:
    if not residency:
        return fallback
    total = sum(residency.values())
    return sum(f * s for f, s in residency.items()) / total if total > 0 else fallback


def _cluster(model: CpuPowerModel, name: str) -> ClusterModel | None:
    return next((c for c in model.clusters if c.name.lower() == name.lower()), None)


def _map_to_target(name: str, base: CpuPowerModel | None, target: CpuPowerModel) -> str:
    """Base cluster name on the target SoC: same name, else same core type, else the default."""
    if _cluster(target, name) is not None:
        return _cluster(target, name).name  # type: ignore[union-attr]
    core_type = (_cluster(base, name).core_type if base and _cluster(base, name) else None)  # type: ignore[union-attr]
    if core_type:
        match = next((c for c in target.clusters if c.core_type == core_type), None)
        if match is not None:
            return match.name
    return target.clusters[target.default_cluster].name


def demands(profile: Any, *, base: CpuPowerModel, warnings: list[str]) -> dict[str, list[_Demand]]:
    out: dict[str, list[_Demand]] = {}
    no_stall: set[str] = set()
    for entry in profile.tasks:
        cstat = profile.clusters.get(entry.cluster)
        f0 = _mean_mhz(cstat.freq_residency if cstat else None, base.freq_mhz)
        cycles = entry.cycles or 0.0
        stall = entry.stall_cycles
        if stall is None:
            no_stall.add(entry.task)
            stall = 0.0
        stall = min(stall, cycles)
        bc = _cluster(base, entry.cluster)
        out.setdefault(entry.task, []).append(_Demand(
            task=entry.task, core_cycles=cycles - stall, stall_ms=stall / (f0 * 1000.0) if f0 > 0 else 0.0,
            bus_bytes=entry.bus_bytes or 0.0, base_cluster=entry.cluster, base_ipc_rel=bc.ipc_rel if bc else 1.0,
            threads=dict(entry.threads) if getattr(entry, "threads", None) else None,
        ))
    if no_stall:
        warnings.append(f"no stall_cycles for {sorted(no_stall)}: all cycles scale with frequency")
    return out


def _task_ms(demand: list[_Demand], cluster: ClusterModel, mhz: float, growth: float) -> float:
    return sum(growth * (d.core_cycles * d.base_ipc_rel / cluster.ipc_rel / (mhz * 1000.0) + d.stall_ms)
               for d in demand)


def _cluster_power(cluster: ClusterModel, tasks: dict[str, float], mhz: float, period_ms: float,
                   model: CpuPowerModel, gating: float) -> dict[str, Any]:
    busy_ms = sum(tasks.values())
    mv = cluster.voltage_mv(mhz, model.fallback_mv)
    dynamic = busy_ms / period_ms * cluster.core_mw(mhz, model.fallback_mv) if period_ms > 0 else 0.0
    active = min(1.0, busy_ms / (cluster.cores * period_ms)) if period_ms > 0 else 0.0
    static = cluster.cores * cluster.leak_mw_per_core(mv) * (active + (1.0 - active) * (1.0 - gating))
    return {"mhz": mhz, "mv": mv, "util": round(active, 6), "busy_ms": round(busy_ms, 4),
            "dynamic_mw": round(dynamic, 6), "static_mw": round(static, 6),
            "total_mw": round(dynamic + static, 6), "tasks_ms": {t: round(v, 4) for t, v in sorted(tasks.items())}}


def evaluate_placement(
    placement: dict[str, str],
    need: dict[str, list[_Demand]],
    *,
    target: CpuPowerModel,
    fps: float,
    spec: WhatIfSpec,
    dsu_residency: dict[float, float] | None = None,
) -> dict[str, Any]:
    period = 1000.0 / fps
    clusters_out: dict[str, Any] = {}
    feasible = True
    slack: dict[str, float] = {}
    for cluster in target.clusters:
        assigned = [t for t, c in placement.items() if c == cluster.name]
        if not assigned:
            lowest = cluster.opps[0].mhz if cluster.opps else target.freq_mhz
            clusters_out[cluster.name] = _cluster_power(cluster, {}, lowest, period, target, spec.power_gating_eff)
            continue
        freqs = [o.mhz for o in cluster.opps] or [target.freq_mhz]
        best = None
        for mhz in freqs:
            times = {t: _task_ms(need[t], cluster, mhz, spec.growth.get(t, spec.default_growth)) for t in assigned}
            ok = (sum(times.values()) <= spec.util_cap * cluster.cores * period + 1e-9
                  and all(v <= period + 1e-9 for v in times.values())
                  and all(times[t] <= spec.budgets_ms[t] + 1e-9 for t in assigned if t in spec.budgets_ms))
            row = _cluster_power(cluster, times, mhz, period, target, spec.power_gating_eff)
            row["feasible"] = ok
            if best is None or (ok and (not best["feasible"] or row["total_mw"] < best["total_mw"])):
                best = row
            elif not best["feasible"] and not ok and mhz > best["mhz"]:
                best = row  # nothing fits: report the fastest level
        assert best is not None
        feasible = feasible and best["feasible"]
        for t in assigned:
            if t in spec.budgets_ms:
                slack[t] = round(spec.budgets_ms[t] - best["tasks_ms"][t], 4)
        clusters_out[cluster.name] = best
    dsu = None
    if target.dsu is not None and target.dsu.opps:
        active = max((c["util"] for c in clusters_out.values()), default=0.0)
        residency = dsu_residency or {target.dsu.opps[-1].mhz: 1.0}
        total = sum(residency.values())
        dyn = sum(s / total * target.dsu.core_mw(f, target.fallback_mv) for f, s in residency.items()) * active
        leak = sum(s / total * target.dsu.leak_mw_per_core(target.dsu.voltage_mv(f, target.fallback_mv))
                   for f, s in residency.items())
        static = leak * (active + (1 - active) * (1 - spec.power_gating_eff))
        dsu = {"active_ratio": round(active, 6), "dynamic_mw": round(dyn, 6), "static_mw": round(static, 6),
               "total_mw": round(dyn + static, 6)}
    bus = sum(d.bus_bytes * spec.growth.get(t, spec.default_growth) for t, ds in need.items() for d in ds)
    total = sum(c["total_mw"] for c in clusters_out.values()) + (dsu["total_mw"] if dsu else 0.0)
    return {
        "placement": dict(sorted(placement.items())),
        "clusters": clusters_out,
        "dsu": dsu,
        "total_mw": round(total, 4),
        "feasible": feasible,
        "min_slack_ms": min(slack.values()) if slack else None,
        "slack_ms": slack,
        "cpu_bw_mbs": round(bus * fps * spec.cpu_bw_scale / 1e6, 3),
    }


def cpu_whatif(
    profile: Any,
    *,
    target: CpuPowerModel,
    fps: float,
    spec: WhatIfSpec | None = None,
    base: CpuPowerModel | None = None,
) -> dict[str, Any]:
    """Evaluate the measured placement and every candidate placement on ``target``."""
    spec = spec or WhatIfSpec()
    warnings: list[str] = []
    base_model = base or target
    need = demands(profile, base=base_model, warnings=warnings)
    base_place: dict[str, str] = {}
    for task, ds in need.items():
        dominant = max(ds, key=lambda d: d.core_cycles + d.stall_ms).base_cluster
        base_place[task] = _map_to_target(dominant, base, target)
        if len({d.base_cluster for d in ds}) > 1:
            warnings.append(f"{task} ran on {sorted({d.base_cluster for d in ds})}; evaluated on one cluster")
    names = {c.name.lower(): c.name for c in target.clusters}
    options: dict[str, list[str]] = {}
    for task, clusters in spec.candidates.items():
        if task not in need:
            warnings.append(f"candidate task '{task}' is not in the profile; ignored")
            continue
        unknown = [c for c in clusters if c.lower() not in names]
        if unknown:
            raise ValueError(f"unknown target clusters for {task}: {unknown} (known {list(names.values())})")
        options[task] = [names[c.lower()] for c in clusters]
    count = 1
    for values in options.values():
        count *= len(values)
    if count > spec.max_cases:
        raise ValueError(f"{count} placements exceed max_cases {spec.max_cases}; narrow the candidates")
    dsu_res = profile.dsu.freq_residency if getattr(profile, "dsu", None) else None
    base_case = evaluate_placement(base_place, need, target=target, fps=fps, spec=spec, dsu_residency=dsu_res)
    cases = []
    keys = list(options)
    for combo in itertools.product(*(options[k] for k in keys)) if keys else [()]:
        placement = {**base_place, **dict(zip(keys, combo))}
        cases.append(evaluate_placement(placement, need, target=target, fps=fps, spec=spec, dsu_residency=dsu_res))
    cases.sort(key=lambda c: (not c["feasible"], c["total_mw"]))
    for rank, case in enumerate(cases, start=1):
        case["rank"] = rank
        case["delta_mw"] = round(case["total_mw"] - base_case["total_mw"], 4)
    # Pareto front on (power, -min_slack) among feasible cases.
    pareto, best_slack = [], None
    for case in (c for c in cases if c["feasible"]):
        slack = case["min_slack_ms"] if case["min_slack_ms"] is not None else float("inf")
        if best_slack is None or slack > best_slack:
            pareto.append(case["rank"])
            best_slack = slack
    measured = None
    if base is None or base is target:
        # Reference: the same profile with its measured residency / gating (no ideal DVFS).
        from scenario_db.sim.cpu_power import profile_cpu_power

        ref = profile_cpu_power(profile, model=base_model, period_ms=1000.0 / fps, warnings=[])
        measured = round(sum(c["total_mw"] for c in ref["clusters"].values())
                         + (ref["dsu"]["total_mw"] if ref["dsu"] else 0.0), 4)
    return {
        "target": target.describe()["clusters"],
        "measured_mw": measured,
        "fps": fps,
        "spec": {"util_cap": spec.util_cap, "power_gating_eff": spec.power_gating_eff,
                 "default_growth": spec.default_growth, "growth": spec.growth, "budgets_ms": spec.budgets_ms,
                 "cpu_bw_scale": spec.cpu_bw_scale},
        "tasks": sorted(t for t in need if t != OTHER_TASK) + ([OTHER_TASK] if OTHER_TASK in need else []),
        "base": base_case,
        "cases": cases[:200],
        "case_count": len(cases),
        "pareto_ranks": pareto,
        "warnings": warnings,
    }
