"""CPU power: topology-driven cluster model shared by runner and timing budget.

The SoC's CPU composition is data (``power_model_params.cpu``): any number of
clusters with a core type, core count, logical CPU ids, an Energy-Model OPP
table (or a ``uW/MHz/V^2`` coefficient), leakage and the measured rail, plus
the DSU. Two estimation paths use the same cluster model:

1. SW-timing path (no PMU data): per SW task
   ``P = P_core(f_default) * active_ms / period`` with
   ``active = (wall - included HW) * count_per_frame * cpu_active_ratio``.
2. PMU-profile path (measured placement, ``cpu_profile``): per task x cluster
   dynamic energy ``E = cycles * sum_l r_l * e(f_l)`` where ``e(f) =
   P_core(f)/f`` [nJ/cycle] and ``r_l`` is the cluster's frequency residency,
   plus cluster leakage ``cores * leak(V) * (1 - power_gated_ratio)`` and the
   DSU ``P_dsu(f) * active_ratio + leak``. Cycles not attributed to a mapped
   task are reported as ``(other)`` instead of being dropped.

Units: P_core [mW] at 100% util of one core; f [MHz]; e [nJ/cycle];
per-frame energy [nJ] / period [ms] / 1000 = mW.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# Linux EM / exynos-cpu-profiler coefficients from ip-cpu-s5e9965 (uW per MHz per V^2).
PROFILER_COEFF: tuple[float, ...] = (449.0, 449.0, 505.0, 1127.0)
DEFAULT_CLUSTER_NAMES: tuple[str, ...] = ("little", "mid", "big", "prime")
OTHER_TASK = "(other)"


@dataclass(frozen=True)
class Opp:
    mhz: float
    mv: float
    mw_per_core: float | None = None


@dataclass(frozen=True)
class ClusterModel:
    name: str
    coeff_uw_per_mhz_v2: float | None = None
    core_type: str | None = None
    cores: int = 1
    cpus: tuple[int, ...] = ()
    opps: tuple[Opp, ...] = ()
    leak_mw_per_core_at_ref: float = 0.0
    leak_ref_mv: float = 0.0
    leak_exponent: float = 2.0
    rail: str | None = None
    ipc_rel: float = 1.0

    def opp_for(self, mhz: float) -> Opp | None:
        """The DVFS level that runs ``mhz`` (lowest OPP >= mhz; the top one if faster)."""
        if not self.opps:
            return None
        for opp in self.opps:
            if opp.mhz >= mhz - 1e-9:
                return opp
        return self.opps[-1]

    def voltage_mv(self, mhz: float, fallback_mv: float) -> float:
        opp = self.opp_for(mhz)
        return opp.mv if opp else fallback_mv

    def core_mw(self, mhz: float, fallback_mv: float) -> float:
        """Dynamic power of one core at 100% utilisation running at ``mhz``."""
        opp = self.opp_for(mhz)
        if opp is not None and opp.mw_per_core is not None:
            # EM rows are per OPP; a residency frequency between OPPs is scaled
            # linearly in f at that OPP's voltage.
            return opp.mw_per_core * (mhz / opp.mhz if opp.mhz > 0 else 1.0)
        if self.coeff_uw_per_mhz_v2 is None:
            raise ValueError(f"cluster {self.name}: no EM power at {mhz:g} MHz")
        volt_v = self.voltage_mv(mhz, fallback_mv) / 1000.0
        return self.coeff_uw_per_mhz_v2 * mhz * volt_v**2 / 1000.0

    def energy_nj_per_cycle(self, mhz: float, fallback_mv: float) -> float:
        return self.core_mw(mhz, fallback_mv) / mhz if mhz > 0 else 0.0

    def leak_mw_per_core(self, mv: float) -> float:
        if self.leak_mw_per_core_at_ref <= 0 or self.leak_ref_mv <= 0:
            return 0.0
        return self.leak_mw_per_core_at_ref * (mv / self.leak_ref_mv) ** self.leak_exponent

    def describe(self) -> dict[str, Any]:
        row: dict[str, Any] = {"name": self.name, "cores": self.cores}
        if self.core_type:
            row["core_type"] = self.core_type
        if self.coeff_uw_per_mhz_v2 is not None:
            row["coeff_uw_per_mhz_v2"] = self.coeff_uw_per_mhz_v2
        if self.opps:
            row["opps"] = len(self.opps)
        if self.rail:
            row["rail"] = self.rail
        return row


def _default_clusters() -> tuple[ClusterModel, ...]:
    return tuple(
        ClusterModel(name=name, coeff_uw_per_mhz_v2=coeff)
        for name, coeff in zip(DEFAULT_CLUSTER_NAMES, PROFILER_COEFF)
    )


def _cluster_from_params(raw: Any) -> ClusterModel:
    leak = raw.leakage
    return ClusterModel(
        name=raw.name,
        coeff_uw_per_mhz_v2=raw.coeff_uw_per_mhz_v2,
        core_type=raw.core_type,
        cores=raw.cores,
        cpus=tuple(raw.cpus),
        opps=tuple(Opp(o.mhz, o.mv, o.mw_per_core) for o in raw.opps),
        leak_mw_per_core_at_ref=leak.mw_per_core_at_ref if leak else 0.0,
        leak_ref_mv=leak.ref_mv if leak else 0.0,
        leak_exponent=leak.exponent if leak else 2.0,
        rail=raw.rail,
        ipc_rel=raw.ipc_rel or 1.0,
    )


@dataclass(frozen=True)
class CpuPowerModel:
    clusters: tuple[ClusterModel, ...] = field(default_factory=_default_clusters)
    default_cluster: int = 1
    freq_mhz: float = 2000.0
    volt_v: float = 0.80
    dsu: ClusterModel | None = None
    # cpu.dsu.vote: ((cluster name / core_type, ((cluster_mhz, dsu_min_mhz), ...)), ...) — see cpu_dsu
    dsu_vote: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = ()
    dsu_vote_source: str | None = None
    source: str = "ip-cpu-s5e9965 profiler coefficients; cluster/freq/volt assumed"
    model_id: str = "em-v1"
    # power_model_params.cpu.scheduler (CpuSchedulerParams) for the what-if sweep.
    scheduler: Any = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not self.clusters:
            raise ValueError("CPU model needs at least one cluster")
        if any(not math.isfinite(v) or v <= 0 for v in (self.freq_mhz, self.volt_v)):
            raise ValueError("CPU power parameters must be finite and positive")
        if not 0 <= self.default_cluster < len(self.clusters):
            raise ValueError("CPU default cluster index is out of range")

    # --- compatibility views (timing budget, older callers) -------------------
    @property
    def cluster_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.clusters)

    @property
    def coeff_uw_per_mhz_v2(self) -> tuple[float, ...]:
        return tuple(self.equivalent_coeff(i) for i in range(len(self.clusters)))

    def equivalent_coeff(self, index: int) -> float:
        """uW/MHz/V^2 at the default frequency (from the EM table when present)."""
        cluster = self.clusters[index]
        if cluster.coeff_uw_per_mhz_v2 is not None:
            return cluster.coeff_uw_per_mhz_v2
        mv = cluster.voltage_mv(self.freq_mhz, self.volt_v * 1000.0)
        return cluster.core_mw(self.freq_mhz, mv) * 1000.0 / (self.freq_mhz * (mv / 1000.0) ** 2)

    @property
    def fallback_mv(self) -> float:
        return self.volt_v * 1000.0

    @classmethod
    def from_params(cls, params: Any | None) -> CpuPowerModel:
        """Model from ``power_model_params.cpu`` (unset fields keep the defaults)."""
        if params is None:
            return cls()
        cpu = params.cpu
        values: dict[str, Any] = {}
        if cpu.clusters:
            values["clusters"] = tuple(_cluster_from_params(c) for c in cpu.clusters)
        if cpu.default_cluster is not None:
            values["default_cluster"] = cpu.default_cluster
        elif cpu.clusters:
            values["default_cluster"] = min(1, len(cpu.clusters) - 1)
        if cpu.freq_mhz is not None:
            values["freq_mhz"] = cpu.freq_mhz
        if cpu.volt_v is not None:
            values["volt_v"] = cpu.volt_v
        if cpu.dsu is not None and cpu.dsu.opps:
            dsu = cpu.dsu
            values["dsu"] = ClusterModel(
                name=dsu.name,
                opps=tuple(Opp(o.mhz, o.mv, o.mw_per_core) for o in dsu.opps),
                leak_mw_per_core_at_ref=dsu.leakage.mw_per_core_at_ref if dsu.leakage else 0.0,
                leak_ref_mv=dsu.leakage.ref_mv if dsu.leakage else 0.0,
                leak_exponent=dsu.leakage.exponent if dsu.leakage else 2.0,
                rail=dsu.rail,
            )
            if dsu.vote:
                values["dsu_vote"] = tuple((v.cluster, tuple((float(f), float(d)) for f, d in v.points)) for v in dsu.vote)
                values["dsu_vote_source"] = dsu.vote_source
        if cpu.scheduler is not None:
            values["scheduler"] = cpu.scheduler
        values["source"] = params.params_ref + (f" ({cpu.source})" if cpu.source else "")
        return cls(**values)

    def cluster_index(self, cluster: str | int | None) -> int:
        if cluster is None or cluster == "":
            return self.default_cluster
        if isinstance(cluster, int) or str(cluster).isdigit():
            index = int(cluster)
            if 0 <= index < len(self.clusters):
                return index
            raise ValueError(f"CPU cluster index {cluster} is out of range")
        names = [name.lower() for name in self.cluster_names]
        if str(cluster).lower() in names:
            return names.index(str(cluster).lower())
        raise ValueError(f"unknown CPU cluster '{cluster}' (known: {list(self.cluster_names)})")

    def rail_for(self, cluster: str) -> str:
        names = {c.name.lower(): c for c in self.clusters}
        if self.dsu is not None:
            names[self.dsu.name.lower()] = self.dsu
        found = names.get(cluster.lower())
        return found.rail if found and found.rail else f"CPU_{cluster.upper()}"

    def task_power_mw(self, busy_ms: float, period_ms: float, *, cluster: str | int | None = None) -> float:
        util = busy_ms / period_ms if period_ms > 0 else 0.0
        return self.clusters[self.cluster_index(cluster)].core_mw(self.freq_mhz, self.fallback_mv) * util

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.model_id,
            "clusters": [c.describe() for c in self.clusters],
            "coeff_uw_per_mhz_v2": [round(v, 3) for v in self.coeff_uw_per_mhz_v2],
            "cluster_names": list(self.cluster_names),
            "default_cluster": self.default_cluster,
            "freq_mhz": self.freq_mhz,
            "volt_v": self.volt_v,
            "source": self.source,
        }
        if self.dsu is not None:
            out["dsu"] = self.dsu.describe()
        return out


# ------------------------------------------------------------ SW-timing path
def sw_task_cpu_power(
    sw_task_timing: list[dict[str, Any]],
    *,
    statistic: str,
    period_ms: float,
    hw_time_ms: dict[str, float],
    model: CpuPowerModel,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """One row per SW task: wall, CPU-active ms per frame, cluster, util, power.

    An unrecognised ``cluster`` label (e.g. a raw perfetto CPU list) falls back
    to the default cluster with a warning instead of failing the run.
    """
    rows = []
    for profile in sw_task_timing:
        task = str(profile.get("task") or profile.get("node_id") or "")
        wall = float(profile.get(f"{statistic}_ms") or 0.0)
        included = sum(hw_time_ms.get(str(node), 0.0) for node in profile.get("includes_hw_nodes") or [])
        per_frame = 1.0
        if profile.get("sample_unit", "invocation") == "invocation" and profile.get("count_per_frame"):
            per_frame = float(profile["count_per_frame"])
        ratio = profile.get("cpu_active_ratio")
        ratio = 1.0 if ratio is None else float(ratio)
        active = max(0.0, wall - included) * per_frame * ratio
        try:
            index = model.cluster_index(profile.get("cluster"))
        except ValueError as exc:
            index = model.default_cluster
            if warnings is not None:
                warnings.append(f"{task}: {exc}; CPU power uses the default cluster")
        power = model.task_power_mw(active, period_ms, cluster=index)
        rows.append({
            "task": task,
            "source": "sw_timing",
            "statistic": statistic,
            "wall_ms": round(wall, 4),
            "included_hw_ms": round(included, 4),
            "invocations_per_frame": per_frame,
            "cpu_active_ratio": ratio,
            "active_ms": round(active, 4),
            "cluster": model.cluster_names[index],
            "util": round(active / period_ms, 6) if period_ms > 0 else 0.0,
            "power_mw": round(power, 6),
            "value_source": profile.get("value_source"),
        })
    return rows


# ---------------------------------------------------------- PMU-profile path
def _residency(model_cluster: ClusterModel, measured: dict[float, float] | None, default_mhz: float) -> dict[float, float]:
    if measured:
        total = sum(measured.values())
        if total > 0:
            return {f: share / total for f, share in measured.items() if share > 0}
    return {default_mhz: 1.0}


def profile_cpu_power(
    profile: Any,
    *,
    model: CpuPowerModel,
    period_ms: float,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """CPU power from a measured per-frame PMU profile (measured task placement).

    ``profile`` is a :class:`scenario_db.sim.models.CpuProfile`. Returns task
    rows plus per-cluster dynamic / static totals and the DSU.
    """
    notes = warnings if warnings is not None else []
    by_cluster: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    known = {c.name.lower(): c for c in model.clusters}
    for cluster_name, cstat in sorted(profile.clusters.items()):
        cluster = known.get(cluster_name.lower())
        if cluster is None:
            notes.append(f"CPU profile cluster '{cluster_name}' is not in the SoC topology; skipped")
            continue
        residency = _residency(cluster, cstat.freq_residency, model.freq_mhz)
        if not cstat.freq_residency:
            notes.append(f"{cluster.name}: no measured frequency residency; using {model.freq_mhz:g} MHz")
        running = _residency(cluster, cstat.freq_residency_active, model.freq_mhz) if cstat.freq_residency_active else None
        if running:
            # Cycles are executed at the running-time frequencies: weight energy/cycle by cycles (time x f).
            weight = {f: share * f for f, share in running.items()}
            total_w = sum(weight.values())
            e_cycle = sum(w * cluster.energy_nj_per_cycle(f, model.fallback_mv) for f, w in weight.items()) / total_w
        else:
            e_cycle = sum(share * cluster.energy_nj_per_cycle(f, model.fallback_mv) for f, share in residency.items())
        row_residency = running or residency
        tasks = sorted((t for t in profile.tasks if t.cluster.lower() == cluster_name.lower()), key=lambda t: t.task)
        attributed = 0.0
        for counters in tasks:
            task = counters.task
            cycles = counters.cycles or 0.0
            attributed += cycles
            power = cycles * e_cycle / period_ms / 1000.0 if period_ms > 0 else 0.0
            rows.append(_profile_row(task, cluster.name, counters, cycles, power, period_ms, row_residency))
        other = max(0.0, (cstat.cycles or 0.0) - attributed)
        if other > 1e-6 * max(1.0, cstat.cycles or 0.0):
            # Cluster cycles no mapped task accounts for (other threads, kernel, idle loops).
            power = other * e_cycle / period_ms / 1000.0 if period_ms > 0 else 0.0
            existing = next((r for r in rows if r["cluster"] == cluster.name and r["task"] == OTHER_TASK), None)
            if existing is not None:
                cycles_total = existing["cycles_per_frame"] + other
                existing.pop("ipc", None)
                existing.update(_profile_row(OTHER_TASK, cluster.name, None, cycles_total,
                                             existing["power_mw"] + power, period_ms, row_residency))
            else:
                rows.append(_profile_row(OTHER_TASK, cluster.name, None, other, power, period_ms, row_residency))
        dynamic = sum(r["power_mw"] for r in rows if r["cluster"] == cluster.name)
        leak = sum(share * cluster.leak_mw_per_core(cluster.voltage_mv(f, model.fallback_mv))
                   for f, share in residency.items())
        on_ratio = 1.0 - (cstat.power_gated_ratio or 0.0)
        static = cluster.cores * leak * on_ratio
        by_cluster[cluster.name] = {
            "dynamic_mw": round(dynamic, 6),
            "static_mw": round(static, 6),
            "total_mw": round(dynamic + static, 6),
            "mean_mhz": round(sum(f * s for f, s in residency.items()), 3),
            **({"mean_active_mhz": round(sum(f * s for f, s in running.items()), 3), "residency_basis": "active"}
               if running else {}),
            "power_gated_ratio": cstat.power_gated_ratio,
            "clock_gated_ratio": cstat.clock_gated_ratio,
        }
    dsu_row = None
    if model.dsu is not None:
        dstat = profile.dsu
        residency = _residency(model.dsu, dstat.freq_residency if dstat else None, model.dsu.opps[-1].mhz)
        if not (dstat and dstat.freq_residency):
            notes.append(f"{model.dsu.name}: no measured frequency residency; using the top OPP {model.dsu.opps[-1].mhz:g} MHz")
        active = dstat.active_ratio if dstat and dstat.active_ratio is not None else _union_active(profile)
        dyn_res = (_residency(model.dsu, dstat.freq_residency_active, model.dsu.opps[-1].mhz)
                   if dstat and dstat.freq_residency_active else residency)
        dynamic = sum(share * model.dsu.core_mw(f, model.fallback_mv) for f, share in dyn_res.items()) * active
        leak = sum(share * model.dsu.leak_mw_per_core(model.dsu.voltage_mv(f, model.fallback_mv))
                   for f, share in residency.items())
        gated = dstat.power_gated_ratio if dstat and dstat.power_gated_ratio is not None else 0.0
        static = leak * (1.0 - gated)
        dsu_row = {"name": model.dsu.name, "active_ratio": round(active, 6), "dynamic_mw": round(dynamic, 6),
                   "static_mw": round(static, 6), "total_mw": round(dynamic + static, 6)}
    return {"tasks": rows, "clusters": by_cluster, "dsu": dsu_row}


def _union_active(profile: Any) -> float:
    """DSU active share when not measured: the busiest cluster's non-idle share."""
    shares = [1.0 - (c.power_gated_ratio or 0.0) - (c.clock_gated_ratio or 0.0) for c in profile.clusters.values()]
    return max([0.0, *[min(1.0, max(0.0, s)) for s in shares]])


def _profile_row(task: str, cluster: str, counters: Any, cycles: float, power: float, period_ms: float,
                 residency: dict[float, float]) -> dict[str, Any]:
    mean_mhz = sum(f * s for f, s in residency.items())
    busy_ms = cycles / (mean_mhz * 1000.0) if mean_mhz > 0 else 0.0
    row: dict[str, Any] = {
        "task": task,
        "source": "pmu_profile",
        "cluster": cluster,
        "cycles_per_frame": round(cycles, 3),
        "active_ms": round(busy_ms, 4),
        "util": round(busy_ms / period_ms, 6) if period_ms > 0 else 0.0,
        "power_mw": round(power, 6),
    }
    if counters is not None:
        for key in ("instructions", "stall_cycles", "bus_bytes"):
            value = getattr(counters, key, None)
            if value is not None:
                row[f"{key}_per_frame"] = round(value, 3)
        if counters.instructions and cycles:
            row["ipc"] = round(counters.instructions / cycles, 4)
    return row
