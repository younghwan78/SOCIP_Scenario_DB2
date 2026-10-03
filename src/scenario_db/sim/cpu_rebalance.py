"""MID-tier task rebalance for the CPU what-if.

Question: camera SW runs on one MID cluster; how should its tasks be split over the tier's clusters
(E2600: MID_LF0 / MID_LF1 / MID_HF, next project: MID_HF0 / MID_HF1) so total CPU power — clusters + DSU —
is lowest within the task budgets? Moving load lowers the busy cluster's OPP (V^2 f) and the DSU vote at the
cost of the receiving cluster's power.

Every movable task (or co-move group) is pinned (cpuset) to one pool cluster; everything else is frozen where
EAS puts it in the measured placement. With pinned threads the EAS placement and schedutil frequency of a
cluster depend only on the threads pinned to it, so a cluster's state is computed once per subset of units
(memo) and an assignment's power is the sum over clusters plus the DSU (max of busy-cluster votes, union
activity of all CPUs). That decomposition is exact; the top candidates are re-evaluated with the full
``evaluate`` for the response. Identical pool clusters (same core type, cores, OPPs, no frozen load) are
interchangeable, so only one ordering of their contents is enumerated.

Search: exhaustive when the (symmetry-reduced) space is at most ``max_exhaustive``, else best-improvement
local search (move / swap) from the measured placement and from the greedy path.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

from scenario_db.sim import cpu_dsu
from scenario_db.sim.cpu_power import OTHER_TASK, CpuPowerModel
from scenario_db.sim.cpu_sched import (
    SweepSpec,
    TaskPolicy,
    Thread,
    _cluster_eval,
    _freqs,
    _map_to_target,
    _prepare,
    eas_place,
    evaluate,
    resolve_allowed,
)

BIG_HINT = ("big",)


@dataclass(frozen=True)
class RebalanceSpec(SweepSpec):
    pool: tuple[str, ...] = ()                    # clusters to split over; () = default (non-BIG clusters)
    movable: tuple[str, ...] | None = None        # None = every task measured on a pool cluster
    locks: dict[str, str] = field(default_factory=dict)   # task -> cluster | "exclude" (keep measured)
    co_move: tuple[tuple[str, ...], ...] = ()     # tasks that move together
    verify_k: int = 30
    max_exhaustive: int = 300_000
    top: int = 20


def default_pool(model: CpuPowerModel) -> list[str]:
    """Clusters other than the BIG family (core type / name containing 'BIG'); all when that leaves < 2."""
    pool = [c.name for c in model.clusters if not any(h in f"{c.core_type or ''} {c.name}".lower() for h in BIG_HINT)]
    return pool if len(pool) >= 2 else [c.name for c in model.clusters]


def _signature(model: CpuPowerModel, name: str) -> tuple:
    c = next(x for x in model.clusters if x.name == name)
    return (c.core_type, c.cores, c.ipc_rel, tuple((o.mhz, o.mv, o.mw_per_core) for o in c.opps),
            c.leak_mw_per_core_at_ref, c.leak_ref_mv, c.leak_exponent, c.coeff_uw_per_mhz_v2)


def cpu_rebalance(profile: Any, *, target: CpuPowerModel, fps: float, spec: RebalanceSpec | None = None,
                  base: CpuPowerModel | None = None) -> dict[str, Any]:
    spec = spec or RebalanceSpec()
    prep = _prepare(profile, target=target, fps=fps, spec=spec, base=base)
    ctx, threads, model, period = prep.ctx, prep.threads, target, prep.period
    every = prep.every
    pool = list(spec.pool) or default_pool(model)
    unknown = [c for c in pool if c not in every]
    if unknown or len(pool) < 2:
        raise ValueError(f"rebalance pool needs >= 2 known clusters (unknown: {unknown})" if unknown else "rebalance pool needs >= 2 clusters")
    pool = [c for c in every if c in pool]            # topology order
    warnings = list(prep.warnings)

    # ---- home (measured) cluster per task: largest measured demand, mapped to the target
    home: dict[str, str] = {}
    measured: dict[str, list[str]] = {}
    names_t = {c.name for c in target.clusters}
    types_t = {c.core_type for c in target.clusters if c.core_type}
    for task, ds in prep.need.items():
        acc: dict[str, float] = {}
        for d in ds:
            name = _map_to_target(d.base_cluster, base, target)
            src_type = next((c.core_type for c in (base or target).clusters if c.name == d.base_cluster), None)
            if base is not None and d.base_cluster not in names_t and src_type not in types_t:
                note = f"measured cluster {d.base_cluster} ({src_type}) has no same-name / same-core-type cluster on the target: mapped to default {name}"
                if note not in warnings:
                    warnings.append(note)
            acc[name] = acc.get(name, 0.0) + d.core_cycles * d.base_ipc_rel
        measured[task] = sorted(acc)
        home[task] = max(acc, key=lambda n: (acc[n], -every.index(n)))
    for task, where in spec.locks.items():
        if task not in prep.need:
            raise ValueError(f"lock for unknown task '{task}'")
        if where != "exclude" and where not in every:
            raise ValueError(f"lock '{task}': unknown cluster '{where}'")
    cand = [t for t in prep.tasks if t != OTHER_TASK and home[t] in pool and t not in spec.locks]
    movable = [t for t in (spec.movable if spec.movable is not None else cand) if t in cand]
    unknown_m = [t for t in (spec.movable or ()) if t not in prep.need]
    if unknown_m:
        raise ValueError(f"unknown movable tasks: {unknown_m}")
    # units = co-move groups (first member's home is the group's home)
    units: list[tuple[str, ...]] = []
    seen: set[str] = set()
    for group in spec.co_move:
        g = tuple(t for t in group if t in movable and t not in seen)
        if g:
            units.append(g)
            seen.update(g)
    units += [(t,) for t in movable if t not in seen]
    unit_of = {t: i for i, g in enumerate(units) for t in g}
    if not units:
        raise ValueError("no movable task on the pool clusters")

    # ---- frozen threads: locked tasks pinned; the rest placed by EAS once in the measured placement
    pinned: dict[str, TaskPolicy] = {}
    for task in prep.need:
        base_pol = prep.base_policies.get(task, TaskPolicy())
        if task in unit_of:
            continue
        lock = spec.locks.get(task)
        if lock and lock != "exclude":
            pinned[task] = TaskPolicy(allowed=(lock,), uclamp_min=base_pol.uclamp_min, uclamp_max=base_pol.uclamp_max,
                                      prefer_idle=base_pol.prefer_idle)
        else:
            pinned[task] = TaskPolicy(allowed=tuple(measured[task]), uclamp_min=base_pol.uclamp_min,
                                      uclamp_max=base_pol.uclamp_max, prefer_idle=base_pol.prefer_idle)
    ref_pol = dict(pinned)
    for task in unit_of:
        b = prep.base_policies.get(task, TaskPolicy())
        ref_pol[task] = TaskPolicy(allowed=(home[task],), uclamp_min=b.uclamp_min, uclamp_max=b.uclamp_max, prefer_idle=b.prefer_idle)
    slots, _ = eas_place(threads, ctx, ref_pol)
    frozen_at: dict[Thread, str] = {th: name for name, cpus in slots.items() for ths in cpus for th in ths if th.task not in unit_of}
    frozen: dict[str, list[Thread]] = {c: [th for th, n in frozen_at.items() if n == c] for c in every}
    # thread-level pin of frozen threads (EAS kept them where it put them)
    thread_pol = {th: n for th, n in frozen_at.items()}
    unit_threads = [[th for th in threads if th.task in g] for g in units]

    def policies_for(assign: tuple[int, ...]) -> dict[str, TaskPolicy]:
        pol = dict(ref_pol)
        for i, g in enumerate(units):
            for t in g:
                b = prep.base_policies.get(t, TaskPolicy())
                pol[t] = TaskPolicy(allowed=(pool[assign[i]],), uclamp_min=b.uclamp_min, uclamp_max=b.uclamp_max,
                                    prefer_idle=b.prefer_idle)
        return pol

    # ---- per-cluster state memo: (cluster, unit mask) -> state
    budgets = spec.budgets_ms
    memo: dict[tuple[str, int], dict[str, Any]] = {}

    def state(c: str, mask: int) -> dict[str, Any]:
        key = (c, mask)
        hit = memo.get(key)
        if hit is not None:
            return hit
        ths = list(frozen[c]) + [th for i, uts in enumerate(unit_threads) if mask >> i & 1 for th in uts]
        pol: dict[str, TaskPolicy] = {}
        for th in ths:
            b = prep.base_policies.get(th.task, TaskPolicy())
            pol[th.task] = TaskPolicy(allowed=(c,), uclamp_min=b.uclamp_min, uclamp_max=b.uclamp_max, prefer_idle=b.prefer_idle)
        sl, over = eas_place(ths, ctx, pol)
        row = _cluster_eval(ctx, c, sl[c], pol)
        cl = ctx.by_name[c]
        task_ms: dict[str, float] = {}
        for cpu in sl[c]:
            for th in cpu:
                task_ms[th.task] = max(task_ms.get(th.task, 0.0), th.ms(cl, row["mhz"]))
        idle = 1.0
        for r in row["cpus"]:
            idle *= 1.0 - min(1.0, r["busy_ms"] / period)
        overloaded = any(r["overloaded"] for r in row["cpus"])
        late = [t for t, ms in task_ms.items() if ms > period + 1e-9 or (t in budgets and ms > budgets[t] + 1e-9)]
        out = {"mhz": row["mhz"], "mw": row["total_mw"], "idle": idle, "busy": row["busy_ms"] > 0,
               "feasible": not overloaded and not late, "task_ms": task_ms, "peak_util": max((r["util"] for r in row["cpus"]), default=0.0),
               "overutilized": over}
        memo[key] = out
        return out

    fixed_clusters = [c for c in every if c not in pool]
    fixed_state = {c: state(c, 0) for c in fixed_clusters}
    fixed_mw = sum(s["mw"] for s in fixed_state.values())
    fixed_idle = math.prod(s["idle"] for s in fixed_state.values())
    fixed_ok = all(s["feasible"] for s in fixed_state.values())
    dsu_pol = prep.dsu_policy
    fmax = {c: ctx.fmax(c) for c in every}
    dsu_memo: dict[tuple, tuple[float, float, float]] = {}

    def dsu_of(mhz_busy: tuple[tuple[str, float], ...], active: float) -> tuple[float, float]:
        """(mhz, mW) of the DSU; per-frequency constants memoised, activity applied here."""
        if dsu_pol is None or model.dsu is None:
            return (0.0, 0.0)
        hit = dsu_memo.get(mhz_busy)
        if hit is None:
            res = cpu_dsu.residency(dsu_pol, model, dict(mhz_busy), fmax)
            a = cpu_dsu.power(model, res, 1.0, prep.sched.power_gating_eff)
            z = cpu_dsu.power(model, res, 0.0, prep.sched.power_gating_eff)
            hit = dsu_memo[mhz_busy] = (a["mhz"], a["dynamic_mw"] + a["static_mw"] - z["static_mw"], z["static_mw"])
        mhz, full_minus_idle, idle_static = hit
        # dyn and static are linear in active: P(a) = P(0) + a * (P(1) - P(0))
        return (mhz, idle_static + active * full_minus_idle)

    def total(masks: list[int]) -> tuple[float, bool, dict[str, Any]]:
        sts = [state(c, m) for c, m in zip(pool, masks)]
        idle = fixed_idle * math.prod(s["idle"] for s in sts)
        busy = tuple(sorted([(c, s["mhz"]) for c, s in zip(pool, sts) if s["busy"]]
                            + [(c, s["mhz"]) for c, s in fixed_state.items() if s["busy"]]))
        dmhz, dmw = dsu_of(busy, 1.0 - idle)
        mw = fixed_mw + sum(s["mw"] for s in sts) + dmw
        return mw, fixed_ok and all(s["feasible"] for s in sts), {"dsu_mhz": dmhz, "dsu_mw": dmw, "sts": sts}

    U, N = len(units), len(pool)
    full = (1 << U) - 1
    home_idx = tuple(pool.index(home[g[0]]) for g in units)

    def masks_of(assign: tuple[int, ...]) -> list[int]:
        m = [0] * N
        for i, a in enumerate(assign):
            m[a] |= 1 << i
        return m

    # symmetry classes: identical pool clusters without frozen load
    sig = {c: (_signature(model, c), bool(frozen[c])) for c in pool}
    classes: list[list[int]] = []
    for i, c in enumerate(pool):
        if sig[c][1]:
            continue
        for cl in classes:
            if sig[pool[cl[0]]] == sig[c]:
                cl.append(i)
                break
        else:
            classes.append([i])
    sym = [cl for cl in classes if len(cl) > 1]
    space = N ** U
    reduced = space
    for cl in sym:
        reduced //= math.factorial(len(cl))      # approximate count after removing orderings

    def canonical(masks: list[int]) -> bool:
        for cl in sym:
            lows = [(masks[i] & -masks[i]) if masks[i] else 1 << U for i in cl]
            if lows != sorted(lows):
                return False
        return True

    results: dict[tuple[int, ...], tuple[float, bool, float]] = {}   # canonical masks -> (mW, feasible, dsu MHz)

    def canon(masks: list[int]) -> tuple[int, ...]:
        out = list(masks)
        for cl in sym:
            vals = sorted((masks[i] for i in cl), key=lambda m: (m & -m) if m else 1 << U)
            for i, v in zip(cl, vals):
                out[i] = v
        return tuple(out)

    perms = [list(itertools.permutations(cl)) for cl in sym]

    def best_label(assign: tuple[int, ...]) -> tuple[int, ...]:
        """Among interchangeable clusters, the labelling that moves the fewest units from home."""
        best_a, best_n = assign, sum(1 for i, a in enumerate(assign) if a != home_idx[i])
        for combo in itertools.product(*perms):
            mp = {c: c for c in range(N)}
            for cl, perm in zip(sym, combo):
                mp.update(dict(zip(cl, perm)))
            a2 = tuple(mp[a] for a in assign)
            n = sum(1 for i, a in enumerate(a2) if a != home_idx[i])
            if n < best_n:
                best_a, best_n = a2, n
        return best_a

    def record(masks: list[int]) -> tuple[float, bool, dict[str, Any]]:
        key = canon(masks)
        mw, ok, info = total(masks)
        results[key] = (mw, ok, info["dsu_mhz"])
        return mw, ok, info

    method = "exhaustive" if reduced <= spec.max_exhaustive else "local"
    if method == "exhaustive":
        def rec(k: int, rest: int, acc: list[int]) -> None:
            if k == N - 1:
                masks = acc + [rest]
                if canonical(masks):
                    record(masks)
                return
            sub = rest
            while True:
                rec(k + 1, rest & ~sub, acc + [sub])
                if sub == 0:
                    break
                sub = (sub - 1) & rest
        rec(0, full, [])
    else:
        warnings.append(f"{space} splits > max_exhaustive {spec.max_exhaustive}: local search")

    def score(assign: tuple[int, ...]) -> tuple[bool, float]:
        mw, ok, _ = record(masks_of(assign))
        return (not ok, mw)

    # greedy path from the measured placement: move one unit at a time to the cluster that lowers power most
    cur = home_idx
    curve_assign = [cur]
    moved: set[int] = set()
    while len(moved) < U:
        best: tuple[tuple[bool, float], int, int] | None = None
        for i in range(U):
            if i in moved:
                continue
            for c in range(N):
                if c == home_idx[i]:
                    continue
                nxt = cur[:i] + (c,) + cur[i + 1:]
                key = score(nxt)
                if best is None or key < best[0]:
                    best = (key, i, c)
        if best is None:
            break
        _, i, c = best
        cur = cur[:i] + (c,) + cur[i + 1:]
        moved.add(i)
        curve_assign.append(cur)
    if method == "local":
        starts = [home_idx, min(curve_assign, key=score)]
        for start in starts:
            cur, cur_key = start, score(start)
            for _ in range(200):
                best_n: tuple[tuple[bool, float], tuple[int, ...]] | None = None
                for i in range(U):
                    for c in range(N):
                        if c != cur[i]:
                            n = cur[:i] + (c,) + cur[i + 1:]
                            k = score(n)
                            if best_n is None or k < best_n[0]:
                                best_n = (k, n)
                for i, j in itertools.combinations(range(U), 2):
                    if cur[i] != cur[j]:
                        n = list(cur); n[i], n[j] = n[j], n[i]
                        k = score(tuple(n))
                        if best_n is None or k < best_n[0]:
                            best_n = (k, tuple(n))
                if best_n is None or not best_n[0] < cur_key:
                    break
                cur, cur_key = best_n[1], best_n[0]

    def assign_of(masks: tuple[int, ...]) -> tuple[int, ...]:
        return best_label(tuple(next(c for c in range(N) if masks[c] >> i & 1) for i in range(U)))

    # ---- verify: full evaluate for the reference and the top-K feasible splits
    def full_eval(assign: tuple[int, ...]) -> dict[str, Any]:
        pol = policies_for(assign)
        case = evaluate(threads, ctx, pol, budgets_ms=budgets, dsu_residency=prep.dsu_res, bw_mbs=prep.bw_mbs,
                        dsu_policy=dsu_pol, pinned_threads=thread_pol)
        case.pop("_signature", None)
        return case

    ranked = sorted(results.items(), key=lambda kv: (not kv[1][1], kv[1][0], sum(1 for i, a in enumerate(assign_of(kv[0])) if a != home_idx[i])))
    feasible = [k for k, v in ranked if v[1]]
    ref_case = full_eval(home_idx)
    ref_mw = ref_case["total_mw"]

    def describe(assign: tuple[int, ...], case: dict[str, Any] | None = None, approx: tuple[float, bool, float] | None = None) -> dict[str, Any]:
        masks = masks_of(assign)
        mw, ok, info = total(masks)
        out: dict[str, Any] = {
            "assign": {"+".join(units[i]): pool[a] for i, a in enumerate(assign)},
            "moved": ["+".join(units[i]) for i, a in enumerate(assign) if a != home_idx[i]],
            "total_mw": round(case["total_mw"] if case else mw, 4),
            "delta_mw": round((case["total_mw"] if case else mw) - ref_mw, 4),
            "feasible": case["feasible"] if case else ok,
            "mw": {c: round(s["mw"], 4) for c, s in zip(pool, info["sts"])} | {"dsu": round(info["dsu_mw"], 4), "other": round(fixed_mw, 4)},
            "mhz": {c: s["mhz"] for c, s in zip(pool, info["sts"])} | {"dsu": info["dsu_mhz"]},
            "mv": {c: ctx.by_name[c].voltage_mv(s["mhz"], model.fallback_mv) for c, s in zip(pool, info["sts"])},
        }
        if case is not None:
            out |= {"task_ms": case["task_ms"], "slack_ms": case["slack_ms"], "min_slack_ms": case["min_slack_ms"],
                    "flags": case["flags"], "clusters": {n: {"mhz": r["mhz"], "busy_ms": r["busy_ms"], "total_mw": r["total_mw"], "util": r["util"]}
                                                         for n, r in case["clusters"].items()},
                    "dsu": case["dsu"], "verified": True}
            out["model_err_mw"] = round(case["total_mw"] - mw, 6)
        out["knobs"] = [{"tasks": list(units[i]), "kind": "cpuset", "clusters": [pool[a]]} for i, a in enumerate(assign) if a != home_idx[i]]
        return out

    top_keys = feasible[: max(spec.verify_k, spec.top)]
    verified = [(k, full_eval(assign_of(k))) for k in top_keys]
    verified.sort(key=lambda kv: (kv[1]["total_mw"], sum(1 for i, a in enumerate(assign_of(kv[0])) if a != home_idx[i])))
    cases = [describe(assign_of(k), case) | {"rank": i + 1} for i, (k, case) in enumerate(verified[: spec.top])]

    # OPP states: same pool-cluster OPPs (+ DSU) = within ~1 mW, fold them
    states: dict[tuple, list[tuple[tuple[int, ...], float]]] = {}
    for k, (mw, ok, dmhz) in results.items():
        if not ok:
            continue
        sts = [state(c, m) for c, m in zip(pool, k)]
        states.setdefault(tuple(s["mhz"] for s in sts) + (dmhz,), []).append((k, mw))
    opp_states = sorted(({"mhz": {c: f for c, f in zip(pool, key[:-1])} | {"dsu": key[-1]}, "count": len(v),
                          "min_mw": round(min(x[1] for x in v), 4), "max_mw": round(max(x[1] for x in v), 4),
                          "representative": describe(assign_of(min(v, key=lambda x: x[1])[0]))["assign"]}
                         for key, v in states.items()), key=lambda s: s["min_mw"])

    curve = []
    for step, a in enumerate(curve_assign):
        d = describe(a)
        d["step"] = step
        d["moved_unit"] = None if step == 0 else next("+".join(units[i]) for i in range(U) if a[i] != curve_assign[step - 1][i])
        util_home = sum(sum(ctx.util(th, home[units[i][0]]) for th in unit_threads[i]) for i in range(U))
        d["moved_util_pct"] = round(100 * sum(sum(ctx.util(th, home[units[i][0]]) for th in unit_threads[i])
                                              for i in range(U) if a[i] != home_idx[i]) / (util_home or 1.0), 1)
        curve.append(d)

    def boundaries(assign: tuple[int, ...]) -> list[dict[str, Any]]:
        masks = masks_of(assign)
        out = []
        for c, m in zip(pool, masks):
            s = state(c, m)
            fs = _freqs(ctx.by_name[c], model)
            row: dict[str, Any] = {"cluster": c, "mhz": s["mhz"], "mv": ctx.by_name[c].voltage_mv(s["mhz"], model.fallback_mv),
                                   "peak_cpu_util": s["peak_util"], "capacity": ctx.caps[c]}
            lower = [f for f in fs if f < s["mhz"]]
            if lower:
                f = lower[-1]
                limit = ctx.caps[c] * f / fs[-1] / prep.sched.freq_margin
                row |= {"next_lower_mhz": f, "next_lower_mv": ctx.by_name[c].voltage_mv(f, model.fallback_mv),
                        "delta_util_needed": round(max(0.0, s["peak_util"] - limit), 1),
                        "candidates": sorted(([ "+".join(units[i]), round(sum(ctx.util(th, c) for th in unit_threads[i]), 1)]
                                              for i in range(U) if m >> i & 1), key=lambda x: -x[1])}
            out.append(row)
        return out

    best_assign = assign_of(verified[0][0]) if verified else home_idx
    return {
        "fps": fps, "period_ms": round(period, 4), "pool": pool, "default_pool": default_pool(model),
        "clusters": [{"name": c.name, "core_type": c.core_type, "cores": c.cores, "in_pool": c.name in pool,
                      "opps_mhz": _freqs(c, model), "capacity": ctx.caps[c.name]} for c in model.clusters],
        "units": [{"unit": "+".join(g), "tasks": list(g), "home": home[g[0]],
                   "budget_ms": min((budgets[t] for t in g if t in budgets), default=None),
                   "threads": len(unit_threads[i]),
                   "util_fmax": {c: round(sum(ctx.util(th, c) for th in unit_threads[i]), 1) for c in pool},
                   "t_fmax_ms": {c: round(max(th.ms(ctx.by_name[c], ctx.fmax(c)) for th in unit_threads[i]), 3) for c in pool}}
                  for i, g in enumerate(units)],
        "frozen": sorted({th.task for th in frozen_at}),
        "symmetric": [[pool[i] for i in cl] for cl in sym],
        "space": space, "evaluated": len(results), "cluster_states": len(memo), "method": method,
        "feasible_count": len(feasible), "verified": len(verified),
        "reference": describe(home_idx, ref_case) | {"label": "현재 (측정 배치)"},
        "best": cases[0] if cases else None,
        "cases": cases, "opp_states": opp_states[:40], "opp_state_count": len(opp_states), "curve": curve,
        "boundaries": {"reference": boundaries(home_idx), "best": boundaries(best_assign)},
        "dsu_model": dsu_pol.describe() if dsu_pol else None,
        "dsu_params": cpu_dsu.params_view(model, prep.sched.power_gating_eff),
        "warnings": warnings,
    }
