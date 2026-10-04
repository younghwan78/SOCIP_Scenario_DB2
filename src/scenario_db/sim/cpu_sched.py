"""Android CPU scheduling approximation (EAS + schedutil) and an automatic knob sweep.

On a device a task runs where Energy-Aware Scheduling (EAS) puts it unless a
cpuset / affinity / uclamp knob says otherwise, and the cluster frequency
follows schedutil. This module reproduces that per frame in steady state from a
measured per-frame profile (no time series needed).

Threads
    A task's per-frame demand (``cpu_whatif.demands``) is split into threads:
    measured per-thread cycles (``CpuTaskProfile.threads``) when imported, else
    ``threads`` from the request / ``scheduler.task_policy`` (equal split),
    else one thread. Demand = reference cycles (IPC 1.0) + frequency-invariant
    stall time.

Utilisation (PELT, frequency and capacity invariant, one activation per frame)
    t_c(f)    = g * (ref_cycles / ipc_c / f + stall_ms)              [ms]
    r         = t_c(f) * f / fmax_c                                   [invariant running ms]
    util_c(f) = cap_c * (1 - y^r) / (1 - y^P),  y = 0.5^(1/halflife)  ("util_est": PELT peak)
              = cap_c * r / P                                         ("pelt_avg")
    cap_c     = scheduler.capacity[c] or 1024 * ipc_c*fmax_c / max(ipc*fmax)

Placement (find_energy_efficient_cpu; threads woken in decreasing demand)
    candidates = allowed clusters (cpuset / affinity) where
    clamp(util, uclamp_min, uclamp_max) * fits_margin <= cap, and in each the
    CPU with the most spare capacity that still fits; pick the cluster with the
    smallest power increase (Linux EM: dynamic only; ``energy_includes_static``
    adds leakage). prefer_idle takes an idle CPU first (smallest fitting
    cluster, the biggest when uclamp_min > 0). Nothing fits -> overutilized:
    the CPU with the most spare capacity (EAS off, load balance).

Frequency (schedutil)
    f_c = lowest OPP >= freq_margin * max_cpu(clamp(sum util)) / cap_c * fmax_c,
    a fixed point because the stall time makes util depend on f. With
    ``deadline_boost`` (ADPF performance hint / HAL uclamp_min) a task with a
    time budget raises its cluster to the lowest OPP that meets the budget.

Power per cluster = sum_cpu busy(f)/period * P_core(f) + sum_cpu leak(V) *
(active + idle * (1 - power_gating_eff)); the DSU is active when any CPU is
(union of independent CPU activity) at its measured residency, else at the
busiest cluster's relative frequency.

Sweep
    Knobs per task: EAS default, cpuset pin to one cluster, cpuset "up to"
    cluster X (bigger clusters excluded), uclamp_max levels. Exhaustive when the
    space <= max_cases, else a coordinate-descent beam. Cases are ranked against
    the all-EAS reference: feasible and lower power first.

Calibrate in-house (vendor scheduler / governor differ): freq_margin,
fits_margin, util_model / pelt_halflife_ms (pelt multiplier), capacity (sysfs
cpu_capacity), energy_includes_static, task_policy (cpuset / uclamp of the
camera / media threads). ``calibration`` in the result compares the EAS
frequency / activity with the measured residency for that purpose.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace
from typing import Any

from scenario_db.sim.cpu_power import OTHER_TASK, ClusterModel, CpuPowerModel
from scenario_db.sim import cpu_dsu
from scenario_db.sim.cpu_whatif import _Demand, _map_to_target, _mean_mhz, demands

SCALE = 1024.0
MAX_THREADS_PER_TASK = 8


# ------------------------------------------------------------------ config
@dataclass(frozen=True)
class TaskPolicy:
    allowed: tuple[str, ...] | None = None       # cluster names / core types; None = all
    uclamp_min: float = 0.0
    uclamp_max: float = SCALE
    prefer_idle: bool = False
    threads: int | None = None

    def clamp(self, util: float) -> float:
        return min(max(util, self.uclamp_min), self.uclamp_max)

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.allowed:
            out["allowed"] = list(self.allowed)
        if self.uclamp_min:
            out["uclamp_min"] = self.uclamp_min
        if self.uclamp_max < SCALE:
            out["uclamp_max"] = self.uclamp_max
        if self.prefer_idle:
            out["prefer_idle"] = True
        if self.threads:
            out["threads"] = self.threads
        return out


_DEFAULT_POLICY = TaskPolicy()


def policy_from(raw: Any) -> TaskPolicy:
    """TaskPolicy from a CpuTaskPolicy model, a dict or a TaskPolicy."""
    if raw is None:
        return TaskPolicy()
    if isinstance(raw, TaskPolicy):
        return raw
    data = raw if isinstance(raw, dict) else raw.model_dump()
    allowed = data.get("allowed")
    umax = data.get("uclamp_max")
    return TaskPolicy(
        allowed=tuple(str(a) for a in allowed) if allowed else None,
        uclamp_min=float(data.get("uclamp_min") or 0.0),
        uclamp_max=float(umax) if umax is not None else SCALE,
        prefer_idle=bool(data.get("prefer_idle") or False),
        threads=int(data["threads"]) if data.get("threads") else None,
    )


@dataclass(frozen=True)
class SchedConfig:
    model: str = "eas"
    freq_margin: float = 1.25
    fits_margin: float = 1.25
    util_model: str = "util_est"
    pelt_halflife_ms: float = 32.0
    deadline_boost: bool = True
    capacity: dict[str, float] = field(default_factory=dict)
    energy_includes_static: bool = False
    task_policy: dict[str, TaskPolicy] = field(default_factory=dict)
    power_gating_eff: float = 0.9
    source: str | None = None

    @classmethod
    def from_model(cls, model: CpuPowerModel, **overrides: Any) -> SchedConfig:
        raw = model.scheduler
        values: dict[str, Any] = {}
        if raw is not None:
            values = {
                "model": raw.model, "freq_margin": raw.freq_margin, "fits_margin": raw.fits_margin,
                "util_model": raw.util_model, "pelt_halflife_ms": raw.pelt_halflife_ms,
                "deadline_boost": raw.deadline_boost,
                "capacity": dict(raw.capacity), "energy_includes_static": raw.energy_includes_static,
                "task_policy": {t: policy_from(p) for t, p in raw.task_policy.items()}, "source": raw.source,
            }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)


# ------------------------------------------------------------------ threads
@dataclass(frozen=True)
class Thread:
    task: str
    name: str
    ref_cycles: float     # core cycles per frame at IPC 1.0
    stall_ms: float       # frequency-invariant memory time per frame
    growth: float = 1.0

    def __post_init__(self) -> None:
        # memo keys hash threads millions of times per sweep; the fields never change
        object.__setattr__(self, "_hash", hash((self.task, self.name, self.ref_cycles, self.stall_ms, self.growth)))

    def __hash__(self) -> int:
        return self._hash  # type: ignore[attr-defined]

    def ms(self, cluster: ClusterModel, mhz: float) -> float:
        return self.growth * (self.ref_cycles / cluster.ipc_rel / (mhz * 1000.0) + self.stall_ms)

    @property
    def label(self) -> str:
        return self.task if self.name == self.task else f"{self.task}#{self.name}"


def build_threads(
    need: dict[str, list[_Demand]],
    *,
    policies: dict[str, TaskPolicy],
    threads_override: dict[str, int],
    growth: dict[str, float],
    default_growth: float,
) -> tuple[list[Thread], dict[str, str]]:
    """Threads per task and where their split came from (measured / given / single)."""
    out: list[Thread] = []
    source: dict[str, str] = {}
    for task, ds in need.items():
        g = growth.get(task, default_growth)
        count = threads_override.get(task) or policies.get(task, TaskPolicy()).threads
        ref_total = sum(d.core_cycles * d.base_ipc_rel for d in ds)
        stall_total = sum(d.stall_ms for d in ds)
        if count:
            source[task] = "given"
            out += [Thread(task, f"{i}" if count > 1 else task, ref_total / count, stall_total / count, g)
                    for i in range(count)]
            continue
        shares: dict[str, list[float]] = {}
        for d in ds:
            ref = d.core_cycles * d.base_ipc_rel
            total = sum(d.threads.values()) if d.threads else 0.0
            if d.threads and total > 0:
                for name, cycles in d.threads.items():
                    acc = shares.setdefault(str(name), [0.0, 0.0])
                    acc[0] += ref * cycles / total
                    acc[1] += d.stall_ms * cycles / total
            else:
                acc = shares.setdefault(task, [0.0, 0.0])
                acc[0] += ref
                acc[1] += d.stall_ms
        if len(shares) > MAX_THREADS_PER_TASK:   # keep the heavy threads, merge the tail
            ranked = sorted(shares.items(), key=lambda kv: -(kv[1][0]))
            head, tail = ranked[: MAX_THREADS_PER_TASK - 1], ranked[MAX_THREADS_PER_TASK - 1:]
            shares = dict(head)
            shares["(rest)"] = [sum(v[0] for _, v in tail), sum(v[1] for _, v in tail)]
        source[task] = "measured" if len(shares) > 1 or next(iter(shares)) != task else "single"
        out += [Thread(task, name, ref, stall, g) for name, (ref, stall) in shares.items()]
    return out, source


# ------------------------------------------------------------------ helpers
def _freqs(cluster: ClusterModel, model: CpuPowerModel) -> list[float]:
    return [o.mhz for o in cluster.opps] or [model.freq_mhz]


def _fmax(cluster: ClusterModel, model: CpuPowerModel) -> float:
    return _freqs(cluster, model)[-1]


def capacities(model: CpuPowerModel, sched: SchedConfig) -> dict[str, float]:
    perf = {c.name: c.ipc_rel * _fmax(c, model) for c in model.clusters}
    top = max(perf.values()) if perf else 1.0
    given = {k.lower(): v for k, v in sched.capacity.items()}
    return {name: float(given.get(name.lower()) or round(SCALE * p / top, 1)) for name, p in perf.items()}


def resolve_allowed(names: tuple[str, ...] | list[str] | None, model: CpuPowerModel) -> list[str]:
    """Cluster names (target order) from cluster names or core types; None = all."""
    if not names:
        return [c.name for c in model.clusters]
    wanted = {n.lower() for n in names}
    known = {c.name.lower() for c in model.clusters} | {c.core_type.lower() for c in model.clusters if c.core_type}
    if wanted - known:
        raise ValueError(f"unknown target clusters or core types: {sorted(wanted - known)}")
    out = [c.name for c in model.clusters
           if c.name.lower() in wanted or (c.core_type and c.core_type.lower() in wanted)]
    return out


def pelt_share(run_ms: float, period_ms: float, *, halflife_ms: float, peak: bool) -> float:
    """PELT util (0..1) of a task running ``run_ms`` once every ``period_ms``."""
    if period_ms <= 0 or run_ms <= 0:
        return 0.0
    if run_ms >= period_ms:
        return 1.0
    if not peak:
        return run_ms / period_ms
    y = 0.5 ** (1.0 / halflife_ms)
    return (1.0 - y**run_ms) / (1.0 - y**period_ms)


def _util(th: Thread, cluster: ClusterModel, mhz: float, *, period: float, fmax: float, cap: float,
          sched: SchedConfig) -> float:
    run = th.ms(cluster, mhz) * (mhz / fmax)
    return cap * pelt_share(run, period, halflife_ms=sched.pelt_halflife_ms, peak=sched.util_model == "util_est")


@dataclass
class _Ctx:
    model: CpuPowerModel
    sched: SchedConfig
    period: float
    caps: dict[str, float]
    by_name: dict[str, ClusterModel]
    budgets_ms: dict[str, float] = field(default_factory=dict)
    # Pure-function memos for one sweep (model / scheduler / period / budgets are fixed per context).
    # The sweep evaluates thousands of placements that share most per-cluster states.
    _fmax_memo: dict[str, float] = field(default_factory=dict, repr=False, compare=False)
    _util_memo: dict[tuple[Thread, str, float], float] = field(default_factory=dict, repr=False, compare=False)
    _energy_memo: dict[Any, float] = field(default_factory=dict, repr=False, compare=False)

    def fmax(self, name: str) -> float:
        value = self._fmax_memo.get(name)
        if value is None:
            value = self._fmax_memo[name] = _fmax(self.by_name[name], self.model)
        return value

    def util(self, th: Thread, name: str, mhz: float | None = None) -> float:
        f = self.fmax(name) if mhz is None else mhz
        key = (th, name, f)
        value = self._util_memo.get(key)
        if value is None:
            value = self._util_memo[key] = _util(th, self.by_name[name], f, period=self.period, fmax=self.fmax(name),
                                                 cap=self.caps[name], sched=self.sched)
        return value

    def energy(self, name: str, cpus: list[list[Thread]], policies: dict[str, TaskPolicy],
               clamped: dict[str, tuple[float, float]]) -> float:
        """``_cluster_eval(...)["energy_mw"]`` memoised on (cluster, thread -> CPU assignment, uclamp of
        the tasks on it): the only inputs it depends on besides the fixed context. ``clamped`` = tasks
        whose policy has a non-default uclamp (usually none)."""
        state = tuple(tuple(ths) for ths in cpus)
        clamps = tuple((t.task, clamped[t.task]) for ths in cpus for t in ths if t.task in clamped) if clamped else ()
        key = (name, state, clamps)
        value = self._energy_memo.get(key)
        if value is None:
            value = self._energy_memo[key] = _cluster_eval(self, name, cpus, policies)["energy_mw"]
        return value


def _cluster_eval(ctx: _Ctx, name: str, cpus: list[list[Thread]], policies: dict[str, TaskPolicy]) -> dict[str, Any]:
    """schedutil frequency + power of one cluster for a given thread -> CPU assignment."""
    c = ctx.by_name[name]
    freqs = _freqs(c, ctx.model)
    fmax, cap, period = freqs[-1], ctx.caps[name], ctx.period
    pg = ctx.sched.power_gating_eff

    def request(mhz: float) -> float:
        req = 0.0
        for ths in cpus:
            if not ths:
                continue
            total = sum(ctx.util(t, name, mhz) for t in ths)
            umin = max(policies.get(t.task, TaskPolicy()).uclamp_min for t in ths)
            umax = max(policies.get(t.task, TaskPolicy()).uclamp_max for t in ths)
            req = max(req, min(max(total, umin), umax))
        return req

    if any(cpus):
        mhz = fmax
        for _ in range(16):
            target = ctx.sched.freq_margin * request(mhz) / cap * fmax
            nxt = next((f for f in freqs if f >= target - 1e-9), freqs[-1])
            if nxt == mhz:
                break
            mhz = nxt
    else:
        mhz = freqs[0]
    sched_mhz = mhz
    boosted: list[str] = []
    if ctx.sched.deadline_boost and ctx.budgets_ms:
        need = [t for ths in cpus for t in ths if t.task in ctx.budgets_ms]
        late = [t for t in need if t.ms(c, mhz) > ctx.budgets_ms[t.task] + 1e-9]
        if late:
            for f in freqs:
                if f > mhz and all(t.ms(c, f) <= ctx.budgets_ms[t.task] + 1e-9 for t in need):
                    mhz = f
                    break
            else:
                mhz = freqs[-1]
            boosted = sorted({t.task for t in late})
    mv = c.voltage_mv(mhz, ctx.model.fallback_mv)
    p_core = c.core_mw(mhz, ctx.model.fallback_mv)
    leak = c.leak_mw_per_core(mv)
    ids = list(c.cpus) + [None] * max(0, c.cores - len(c.cpus))
    rows, dynamic, static, busy_total = [], 0.0, 0.0, 0.0
    tasks_ms: dict[str, float] = {}
    for index, ths in enumerate(cpus):
        busy = sum(t.ms(c, mhz) for t in ths)
        active = min(1.0, busy / period) if period > 0 else 0.0
        dynamic += active * p_core
        static += leak * (active + (1.0 - active) * (1.0 - pg))
        busy_total += busy
        for t in ths:
            tasks_ms[t.task] = tasks_ms.get(t.task, 0.0) + t.ms(c, mhz)
        rows.append({
            "cpu": ids[index] if ids[index] is not None else f"{name}.{index}",
            "util": round(sum(ctx.util(t, name, mhz) for t in ths), 1),
            "busy_ms": round(busy, 4),
            "overloaded": busy > period + 1e-9,
            "threads": [t.label for t in ths],
        })
    energy = dynamic + (static if ctx.sched.energy_includes_static else 0.0)
    return {
        "mhz": mhz, "mv": mv, "capacity": cap, "sched_mhz": sched_mhz, "boosted_by": boosted,
        "util": round(min(1.0, busy_total / (c.cores * period)) if period > 0 else 0.0, 6),
        "busy_ms": round(busy_total, 4),
        "dynamic_mw": round(dynamic, 6), "static_mw": round(static, 6), "total_mw": round(dynamic + static, 6),
        "energy_mw": energy, "cpus": rows, "tasks_ms": {t: round(v, 4) for t, v in sorted(tasks_ms.items())},
    }


# ------------------------------------------------------------------ EAS placement
def eas_place(threads: list[Thread], ctx: _Ctx, policies: dict[str, TaskPolicy],
              thread_allowed: dict[Thread, str] | None = None) -> tuple[dict[str, list[list[Thread]]], list[str]]:
    """``thread_allowed`` pins single threads to one cluster (rebalance: threads frozen where EAS put them)."""
    slots: dict[str, list[list[Thread]]] = {c.name: [[] for _ in range(c.cores)] for c in ctx.model.clusters}
    # running util sum per CPU at fmax (same accumulation order as summing the CPU's thread list)
    loads: dict[str, list[float]] = {c.name: [0.0] * c.cores for c in ctx.model.clusters}
    clamped = {t: (p.uclamp_min, p.uclamp_max) for t, p in policies.items()
               if (p.uclamp_min, p.uclamp_max) != (_DEFAULT_POLICY.uclamp_min, _DEFAULT_POLICY.uclamp_max)}

    def put(name: str, index: int, th: Thread) -> None:
        slots[name][index].append(th)
        loads[name][index] += ctx.util(th, name)

    overutilized: list[str] = []
    biggest = max(ctx.caps, key=lambda n: (ctx.caps[n], n))
    order = sorted(threads, key=lambda t: (-ctx.util(t, biggest), t.task, t.name))
    for th in order:
        pol = policies.get(th.task, TaskPolicy())
        allowed = [thread_allowed[th]] if thread_allowed and th in thread_allowed else resolve_allowed(pol.allowed, ctx.model)
        fitting: list[tuple[str, int]] = []
        for name in allowed:
            cap = ctx.caps[name]
            u = pol.clamp(ctx.util(th, name))
            if u * ctx.sched.fits_margin > cap + 1e-9:
                continue
            best, spare_best = None, -math.inf
            for index, cur in enumerate(loads[name]):
                if (cur + u) * ctx.sched.fits_margin > cap + 1e-9:
                    continue
                if cap - cur > spare_best:
                    best, spare_best = index, cap - cur
            if best is not None:
                fitting.append((name, best))
        if not fitting:
            overutilized.append(th.label)
            name, index = max(
                ((n, i) for n in allowed for i in range(len(slots[n]))),
                key=lambda ni: (ctx.caps[ni[0]] - loads[ni[0]][ni[1]], ctx.caps[ni[0]]))
            put(name, index, th)
            continue
        if pol.prefer_idle:
            idle = [(n, i) for n, i in fitting if not slots[n][i]]
            if idle:
                idle.sort(key=lambda ni: ctx.caps[ni[0]], reverse=pol.uclamp_min > 0)
                n, i = idle[0]
                put(n, i, th)
                continue
        choice: tuple[tuple[float, float], str, int] | None = None
        for name, index in fitting:
            before = ctx.energy(name, slots[name], policies, clamped)
            trial = [list(x) for x in slots[name]]
            trial[index].append(th)
            after = ctx.energy(name, trial, policies, clamped)
            key = (round(after - before, 9), ctx.caps[name])
            if choice is None or key < choice[0]:
                choice = (key, name, index)
        assert choice is not None
        put(choice[1], choice[2], th)
    return slots, overutilized


def evaluate(
    threads: list[Thread],
    ctx: _Ctx,
    policies: dict[str, TaskPolicy],
    *,
    budgets_ms: dict[str, float],
    dsu_residency: dict[float, float] | None = None,
    bw_mbs: float,
    dsu_policy: cpu_dsu.DsuPolicy | None = None,
    pinned_threads: dict[Thread, str] | None = None,
) -> dict[str, Any]:
    slots, overutilized = eas_place(threads, ctx, policies, pinned_threads)
    clusters_out: dict[str, Any] = {}
    task_ms: dict[str, float] = {}
    where: dict[str, set[str]] = {}
    signature: list[tuple[str, str, int]] = []
    shared: set[str] = set()
    overloaded = False
    for c in ctx.model.clusters:
        row = _cluster_eval(ctx, c.name, slots[c.name], policies)
        row.pop("energy_mw")
        clusters_out[c.name] = row
        for index, ths in enumerate(slots[c.name]):
            if len({t.task for t in ths}) > 1:
                shared.update(t.task for t in ths)
            for th in ths:
                task_ms[th.task] = max(task_ms.get(th.task, 0.0), th.ms(c, row["mhz"]))
                where.setdefault(th.task, set()).add(c.name)
                signature.append((th.label, c.name, index))
        overloaded = overloaded or any(r["overloaded"] for r in row["cpus"])
    period = ctx.period
    slack = {t: round(budgets_ms[t] - task_ms.get(t, 0.0), 4) for t in budgets_ms if t in task_ms}
    misses = sorted(t for t, s in slack.items() if s < -1e-9)
    late = sorted(t for t, ms in task_ms.items() if ms > period + 1e-9)
    feasible = not overloaded and not misses and not late
    dsu = None
    model = ctx.model
    if model.dsu is not None and model.dsu.opps:
        idle_all = 1.0
        for row in clusters_out.values():
            for cpu in row["cpus"]:
                idle_all *= 1.0 - min(1.0, cpu["busy_ms"] / period)
        active = 1.0 - idle_all
        if dsu_policy is not None:
            busy = {n: r["mhz"] for n, r in clusters_out.items() if r["busy_ms"] > 0}
            residency = cpu_dsu.residency(dsu_policy, model, busy, {n: ctx.fmax(n) for n in busy})
        elif dsu_residency:
            residency = dsu_residency
        else:   # no measured DSU residency: follow the busiest cluster's relative frequency
            rel = max((r["mhz"] / ctx.fmax(n) for n, r in clusters_out.items() if r["busy_ms"] > 0), default=0.0)
            dsu_f = [o.mhz for o in model.dsu.opps]
            residency = {next((f for f in dsu_f if f >= rel * dsu_f[-1] - 1e-9), dsu_f[-1]): 1.0}
        dsu = cpu_dsu.power(model, residency, active, ctx.sched.power_gating_eff)
    total_mw = sum(r["total_mw"] for r in clusters_out.values()) + (dsu["total_mw"] if dsu else 0.0)
    freqs = tuple((n, r["mhz"]) for n, r in clusters_out.items())
    return {
        "placement": {t: sorted(v) for t, v in sorted(where.items())},
        "clusters": clusters_out,
        "dsu": dsu,
        "total_mw": round(total_mw, 4),
        "feasible": feasible,
        "task_ms": {t: round(v, 4) for t, v in sorted(task_ms.items())},
        "slack_ms": slack,
        "min_slack_ms": min(slack.values()) if slack else None,
        "flags": {k: v for k, v in {"overutilized": sorted(set(overutilized)), "budget_miss": misses,
                                    "over_period": late, "shared_cpu": sorted(shared),
                                    "overloaded_cpu": overloaded}.items() if v},
        "cpu_bw_mbs": round(bw_mbs, 3),
        "_signature": (tuple(sorted(signature)), freqs),
    }


# ------------------------------------------------------------------ sweep
@dataclass(frozen=True)
class SweepSpec:
    growth: dict[str, float] = field(default_factory=dict)
    default_growth: float = 1.0
    budgets_ms: dict[str, float] = field(default_factory=dict)
    threads: dict[str, int] = field(default_factory=dict)
    sweep_clusters: dict[str, list[str]] = field(default_factory=dict)   # task -> clusters; missing = auto
    knobs: tuple[str, ...] = ("pin", "upto")
    uclamp_max_levels: tuple[int, ...] = ()
    uclamp_min_levels: tuple[int, ...] = ()
    task_policy: dict[str, Any] = field(default_factory=dict)            # request overrides
    fixed_tasks: tuple[str, ...] = (OTHER_TASK,)
    power_gating_eff: float = 0.9
    cpu_bw_scale: float = 1.0
    freq_margin: float | None = None
    fits_margin: float | None = None
    util_model: str | None = None
    pelt_halflife_ms: float | None = None
    deadline_boost: bool | None = None
    energy_includes_static: bool | None = None
    max_cases: int = 3000
    beam_width: int = 12
    top: int = 60
    reference: str = "measured"     # measured = measured clusters + schedutil ("현재"), eas = EAS default
    dsu_mode: str = "auto"          # cpu_dsu.MODES
    dsu_vote: Any = None            # request vote table (experiment) — overrides the topology's
    dsu_fixed_mhz: float | None = None
    equal_mw: float = 0.1           # cases within this power and with the same OPPs are folded together


def _apply(policy: TaskPolicy, option: dict[str, Any]) -> TaskPolicy:
    kind = option["kind"]
    if kind in ("pin", "upto"):
        return replace(policy, allowed=tuple(option["clusters"]))
    if kind == "uclamp_max":
        return replace(policy, uclamp_max=float(option["value"]))
    if kind == "uclamp_min":
        return replace(policy, uclamp_min=float(option["value"]))
    return policy


def _options(task: str, clusters: list[str], spec: SweepSpec, caps: dict[str, float], every: list[str]) -> list[dict[str, Any]]:
    opts: list[dict[str, Any]] = [{"kind": "eas"}]
    ordered = sorted(clusters, key=lambda n: (caps[n], every.index(n)))
    seen: set[tuple[str, ...]] = set()
    if "pin" in spec.knobs:
        for name in ordered:
            seen.add((name,))
            opts.append({"kind": "pin", "clusters": [name]})
    if "upto" in spec.knobs:
        for k in range(2, len(ordered) + 1):
            prefix = tuple(ordered[:k])
            if prefix in seen or set(prefix) == set(every):
                continue
            seen.add(prefix)
            opts.append({"kind": "upto", "clusters": list(prefix),
                         "excluded": [n for n in every if n not in prefix]})
    if "uclamp_max" in spec.knobs:
        opts += [{"kind": "uclamp_max", "value": int(v)} for v in spec.uclamp_max_levels]
    if "uclamp_min" in spec.knobs:
        opts += [{"kind": "uclamp_min", "value": int(v)} for v in spec.uclamp_min_levels]
    return opts


def _merge_equivalent(cases: list[dict[str, Any]], tol_mw: float, kind: dict[str, str]) -> list[dict[str, Any]]:
    """Fold cases with the same feasibility, cluster frequencies and power (within ``tol_mw``)
    into the one with the fewest knobs; the folded knob sets are listed as ``equivalents``.
    Clusters of the same core type and size (e.g. MID_LF0 / MID_LF1) are interchangeable."""
    out: list[dict[str, Any]] = []
    for case in cases:
        freqs = tuple(sorted((kind.get(n, n), r["mhz"]) for n, r in case["clusters"].items()))
        home = next((c for c in out if c["feasible"] == case["feasible"] and c["_freqs"] == freqs
                     and abs(c["total_mw"] - case["total_mw"]) <= tol_mw), None)
        if home is None:
            case["_freqs"] = freqs
            case["equivalents"] = []
            out.append(case)
            continue
        keep, fold = (home, case) if len(home["knobs"]) <= len(case["knobs"]) else (case, home)
        if keep is case:   # the simpler variant becomes the representative
            case["_freqs"], case["equivalents"] = freqs, home["equivalents"]
            out[out.index(home)] = case
        keep["equivalents"].append({"knobs": fold["knobs"], "total_mw": fold["total_mw"], "placement": fold["placement"]})
        keep["equivalents"].extend(fold.get("equivalents", []) if fold is home else [])
    for case in out:
        case.pop("_freqs", None)
        case["equivalents"] = case["equivalents"][:20]
    return out


@dataclass
class _Prepared:
    """Context shared by the sweep and the rebalance: scheduler, demands, threads, DSU rule."""
    warnings: list[str]
    sched: SchedConfig
    need: dict[str, list[_Demand]]
    period: float
    caps: dict[str, float]
    ctx: _Ctx
    every: list[str]
    base_policies: dict[str, TaskPolicy]
    threads: list[Thread]
    thread_source: dict[str, str]
    bw_mbs: float
    dsu_res: dict[float, float] | None
    dsu_policy: cpu_dsu.DsuPolicy | None
    tasks: list[str]
    base_model: CpuPowerModel


def _prepare(profile: Any, *, target: CpuPowerModel, fps: float, spec: SweepSpec, base: CpuPowerModel | None) -> _Prepared:
    warnings: list[str] = []
    sched = SchedConfig.from_model(
        target, power_gating_eff=spec.power_gating_eff, freq_margin=spec.freq_margin,
        fits_margin=spec.fits_margin, energy_includes_static=spec.energy_includes_static,
        util_model=spec.util_model, pelt_halflife_ms=spec.pelt_halflife_ms, deadline_boost=spec.deadline_boost)
    if sched.model != "eas":
        warnings.append(f"scheduler.model '{sched.model}' — the sweep always uses the EAS approximation")
    base_model = base or target
    need = demands(profile, base=base_model, warnings=warnings)
    if not need:
        raise ValueError("the CPU profile has no task cycles")
    period = 1000.0 / fps
    caps = capacities(target, sched)
    ctx = _Ctx(target, sched, period, caps, {c.name: c for c in target.clusters}, dict(spec.budgets_ms))
    every = [c.name for c in target.clusters]
    base_policies = dict(sched.task_policy)
    for task, raw in spec.task_policy.items():
        base_policies[task] = policy_from(raw)
    threads, thread_source = build_threads(need, policies=base_policies, threads_override=spec.threads,
                                           growth=spec.growth, default_growth=spec.default_growth)
    bus = sum(d.bus_bytes * spec.growth.get(t, spec.default_growth) for t, ds in need.items() for d in ds)
    bw_mbs = bus * fps * spec.cpu_bw_scale / 1e6
    dsu_res = profile.dsu.freq_residency if getattr(profile, "dsu", None) else None
    dsu_policy = cpu_dsu.resolve(target, mode=spec.dsu_mode, vote=spec.dsu_vote, fixed_mhz=spec.dsu_fixed_mhz,
                                 measured=dsu_res) if target.dsu is not None and target.dsu.opps else None
    tasks = sorted(t for t in need if t != OTHER_TASK) + ([OTHER_TASK] if OTHER_TASK in need else [])
    return _Prepared(warnings, sched, need, period, caps, ctx, every, base_policies, threads, thread_source, bw_mbs,
                     dsu_res, dsu_policy, tasks, base_model)


def cpu_sweep(
    profile: Any,
    *,
    target: CpuPowerModel,
    fps: float,
    spec: SweepSpec | None = None,
    base: CpuPowerModel | None = None,
) -> dict[str, Any]:
    """EAS reproduction of the measured profile on ``target`` + automatic knob sweep."""
    spec = spec or SweepSpec()
    prep = _prepare(profile, target=target, fps=fps, spec=spec, base=base)
    warnings, sched, need, period, caps, ctx = prep.warnings, prep.sched, prep.need, prep.period, prep.caps, prep.ctx
    every, base_policies, threads, thread_source = prep.every, prep.base_policies, prep.threads, prep.thread_source
    bw_mbs, dsu_res, dsu_policy, tasks, base_model = prep.bw_mbs, prep.dsu_res, prep.dsu_policy, prep.tasks, prep.base_model

    # ---- sweep range: per task x cluster, alone at fmax
    range_tasks: list[dict[str, Any]] = []
    sweep_sets: dict[str, list[str]] = {}
    for task in tasks:
        ths = [t for t in threads if t.task == task]
        measured = sorted({_map_to_target(d.base_cluster, base, target) for d in need[task]})
        cells: dict[str, dict[str, Any]] = {}
        for name in every:
            c = ctx.by_name[name]
            t_max = max(th.ms(c, ctx.fmax(name)) for th in ths)
            u_max = max(ctx.util(th, name) for th in ths)
            limit = min(period, spec.budgets_ms.get(task, period))
            cells[name] = {"t_fmax_ms": round(t_max, 4), "util_fmax": round(u_max, 1),
                           "fits": u_max * sched.fits_margin <= caps[name] + 1e-9, "meets": t_max <= limit + 1e-9}
        if task in spec.fixed_tasks:
            chosen: list[str] = []
        elif task in spec.sweep_clusters:
            chosen = resolve_allowed(spec.sweep_clusters[task], target) if spec.sweep_clusters[task] else []
        else:
            chosen = [n for n in every if cells[n]["meets"]]
        sweep_sets[task] = chosen
        for name in every:
            cells[name]["in_sweep"] = name in chosen
        range_tasks.append({
            "task": task, "threads": [{"name": th.name, "t_fmax_ms": round(max(th.ms(ctx.by_name[n], ctx.fmax(n)) for n in every), 4)} for th in ths],
            "thread_source": thread_source.get(task, "single"), "measured": measured,
            "policy": base_policies.get(task, TaskPolicy()).describe(), "budget_ms": spec.budgets_ms.get(task),
            "growth": spec.growth.get(task, spec.default_growth), "cells": cells,
        })
    options = {t: (_options(t, sweep_sets[t], spec, caps, every) if sweep_sets[t] else [{"kind": "eas"}]) for t in tasks}
    for row in range_tasks:
        row["options"] = options[row["task"]]
    swept = [t for t in tasks if len(options[t]) > 1]
    space = 1
    for t in swept:
        space *= len(options[t])

    memo: dict[tuple[int, ...], dict[str, Any]] = {}

    def run(assign: tuple[int, ...]) -> dict[str, Any]:
        if assign not in memo:
            policies = dict(base_policies)
            for task, index in zip(swept, assign):
                if index:
                    policies[task] = _apply(policies.get(task, TaskPolicy()), options[task][index])
            case = evaluate(threads, ctx, policies, budgets_ms=spec.budgets_ms, dsu_residency=dsu_res, bw_mbs=bw_mbs,
                            dsu_policy=dsu_policy)
            case["knobs"] = {task: options[task][index] for task, index in zip(swept, assign) if index}
            memo[assign] = case
        return memo[assign]

    zero = tuple(0 for _ in swept)
    eas_default = run(zero)
    measured_where: dict[str, list[str]] = {str(row["task"]): list(row["measured"]) for row in range_tasks}
    measured_policies = dict(base_policies)
    for task, where in measured_where.items():
        measured_policies[task] = replace(measured_policies.get(task, TaskPolicy()), allowed=tuple(where))
    measured_case = evaluate(threads, ctx, measured_policies, budgets_ms=spec.budgets_ms, dsu_residency=dsu_res,
                             bw_mbs=bw_mbs, dsu_policy=dsu_policy)
    measured_case["knobs"] = {t: {"kind": "measured", "clusters": w} for t, w in measured_where.items() if t in swept}
    reference = measured_case if spec.reference == "measured" else eas_default
    if space <= spec.max_cases:
        method = "exhaustive"
        for assign in itertools.product(*(range(len(options[t])) for t in swept)):
            run(tuple(assign))
    else:
        method = "beam"
        rank = sorted(range(len(swept)), key=lambda i: -max(eas_default["task_ms"].get(swept[i], 0.0), 0.0))
        beam = [zero]
        for _ in range(2):
            for i in rank:
                pool = set(beam)
                for state in beam:
                    for j in range(len(options[swept[i]])):
                        nxt = state[:i] + (j,) + state[i + 1:]
                        if nxt not in memo and len(memo) >= spec.max_cases:
                            continue
                        run(nxt)
                        pool.add(nxt)
                beam = sorted(pool, key=lambda a: (not memo[a]["feasible"], memo[a]["total_mw"], sum(1 for x in a if x)))
                beam = beam[: spec.beam_width]
        warnings.append(f"{space} knob combinations > max_cases {spec.max_cases}: beam search evaluated {len(memo)}")

    # ---- dedupe identical schedules (keep the fewest knobs), rank vs the EAS reference
    unique: dict[Any, dict[str, Any]] = {}
    for assign, case in memo.items():
        key = case["_signature"]
        keep = unique.get(key)
        if keep is None or len(case["knobs"]) < len(keep["knobs"]):
            unique[key] = case
    ref_key = reference["_signature"]
    ref_total = reference["total_mw"]
    better: list[dict[str, Any]] = []
    others: list[dict[str, Any]] = []
    for key, case in unique.items():
        if key == ref_key:
            continue
        case["delta_mw"] = round(case["total_mw"] - ref_total, 4)
        case["moved"] = sorted(t for t in tasks if case["placement"].get(t) != reference["placement"].get(t))
        # vs a reference that misses its budget every feasible case is an improvement
        lower = case["delta_mw"] < -1e-6 or not reference["feasible"]
        (better if case["feasible"] and lower else others).append(case)
    better.sort(key=lambda c: (c["total_mw"], len(c["knobs"])))
    others.sort(key=lambda c: (not c["feasible"], c["total_mw"]))
    kind = {c.name: f"{c.core_type or c.name}x{c.cores}" for c in target.clusters}
    better, others = _merge_equivalent(better, spec.equal_mw, kind), _merge_equivalent(others, spec.equal_mw, kind)
    for rank_no, case in enumerate(better, start=1):
        case["rank"] = rank_no
    for case in (eas_default, measured_case):
        case["delta_mw"] = round(case["total_mw"] - ref_total, 4)
        case["moved"] = sorted(t for t in tasks if case["placement"].get(t) != reference["placement"].get(t))
    for case in [eas_default, measured_case, *unique.values()]:
        case.pop("_signature", None)

    # ---- measured reference and model check (same SoC only)
    measured_mw = None
    calibration: dict[str, Any] = {}
    if base is None or base is target:
        from scenario_db.sim.cpu_power import profile_cpu_power

        ref = profile_cpu_power(profile, model=base_model, period_ms=period, warnings=[])
        measured_mw = round(sum(c["total_mw"] for c in ref["clusters"].values())
                            + (ref["dsu"]["total_mw"] if ref["dsu"] else 0.0), 4)
        for name, row in reference["clusters"].items():
            prof = profile.clusters.get(name)
            if prof is None:
                continue
            entry: dict[str, Any] = {"eas_mhz": row["mhz"], "eas_util": row["util"]}
            if prof.freq_residency:
                entry["measured_mean_mhz"] = round(_mean_mhz(prof.freq_residency, 0.0), 1)
            gated = (prof.clock_gated_ratio or 0.0) + (prof.power_gated_ratio or 0.0)
            if prof.clock_gated_ratio is not None or prof.power_gated_ratio is not None:
                entry["measured_active"] = round(max(0.0, 1.0 - gated), 4)
            calibration[name] = entry

    return {
        "scheduler": {"model": "eas", "freq_margin": sched.freq_margin, "fits_margin": sched.fits_margin,
                      "util_model": sched.util_model, "pelt_halflife_ms": sched.pelt_halflife_ms,
                      "deadline_boost": sched.deadline_boost,
                      "energy_includes_static": sched.energy_includes_static, "capacity": caps,
                      "power_gating_eff": sched.power_gating_eff,
                      "from_params": target.scheduler is not None, "source": sched.source},
        "fps": fps,
        "period_ms": round(period, 4),
        "range": {
            "clusters": [{"name": c.name, "core_type": c.core_type, "cores": c.cores, "cpus": list(c.cpus),
                          "capacity": caps[c.name], "ipc_rel": c.ipc_rel,
                          "opp_min_mhz": _freqs(c, target)[0], "opp_max_mhz": _freqs(c, target)[-1],
                          "opp_count": len(_freqs(c, target)), "opps_mhz": _freqs(c, target)} for c in target.clusters],
            "tasks": range_tasks,
            "knobs": list(spec.knobs),
            "space": space,
            "evaluated": len(memo),
            "unique": len(unique),
            "method": method,
        },
        "measured_mw": measured_mw,
        "calibration": calibration,
        "dsu_model": dsu_policy.describe() if dsu_policy else None,
        "dsu_params": cpu_dsu.params_view(target, sched.power_gating_eff),
        "dsu_measured": {str(f): v for f, v in dsu_res.items()} if dsu_res else None,
        "dsu_check": ({"measured_mean_mhz": round(_mean_mhz(dsu_res, 0.0), 1),
                       "model_mhz": (measured_case.get("dsu") or {}).get("mhz")} if dsu_res and dsu_policy else None),
        "reference_kind": spec.reference,
        "reference": reference,
        "eas_default": eas_default,
        "measured_placement": measured_case,
        "cases": better[: spec.top],
        "better_count": len(better),
        "equal_mw": spec.equal_mw,
        "others": others[:30],
        "other_count": len(others),
        "tasks": tasks,
        "warnings": warnings,
    }
