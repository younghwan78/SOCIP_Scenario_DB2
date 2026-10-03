"""DSU (DynamIQ Shared Unit) frequency policy for the CPU what-if.

The DSU clock follows the clusters: each busy cluster *votes* a minimum DSU frequency
for its own frequency and the DSU runs at the highest vote. In the architecture phase
the vote table is an assumption, so the sweep takes it from the topology
(``cpu.dsu.vote``) or from the request (experiments) and reports which one it used.

Modes
- ``vote``: max over busy clusters of the vote table (rounded up to a DSU OPP)
- ``proportional``: busiest cluster's f / fmax mapped onto the DSU OPP range (legacy fallback)
- ``measured``: the measured DSU residency for every placement (legacy; placement-insensitive)
- ``fixed``: one DSU frequency for every placement
- ``auto``: vote when a table exists, else measured when the profile has a residency, else proportional
  (= the behaviour before vote tables existed)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scenario_db.sim.cpu_power import ClusterModel, CpuPowerModel

MODES = ("auto", "vote", "proportional", "measured", "fixed")
VoteTable = dict[str, tuple[tuple[float, float], ...]]


@dataclass(frozen=True)
class DsuPolicy:
    mode: str                                  # effective mode (never "auto")
    vote: VoteTable = field(default_factory=dict)
    fixed_mhz: float | None = None
    measured: dict[float, float] | None = None
    source: str | None = None                  # topology vote_source / "request" / None
    requested: str = "auto"

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {"mode": self.mode, "requested": self.requested, "source": self.source}
        if self.mode == "vote":
            out["vote"] = {k: [list(p) for p in v] for k, v in self.vote.items()}
        if self.mode == "fixed":
            out["fixed_mhz"] = self.fixed_mhz
        return out


def _table(raw: Any) -> VoteTable:
    """{cluster: [[cluster_mhz, dsu_mhz], ...]} or [{cluster, points}] -> normalised, validated table."""
    items = raw.items() if isinstance(raw, dict) else ((v["cluster"] if isinstance(v, dict) else v.cluster,
                                                         v["points"] if isinstance(v, dict) else v.points) for v in raw)
    out: VoteTable = {}
    for name, points in items:
        pts = tuple((float(f), float(d)) for f, d in points)
        if not pts:
            raise ValueError(f"DSU vote '{name}' has no points")
        fs = [f for f, _ in pts]
        if any(f <= 0 or d <= 0 for f, d in pts) or fs != sorted(fs) or len(set(fs)) != len(fs):
            raise ValueError(f"DSU vote '{name}': cluster_mhz must be positive and strictly ascending")
        if [d for _, d in pts] != sorted(d for _, d in pts):
            raise ValueError(f"DSU vote '{name}': dsu_min_mhz must not decrease")
        out[str(name)] = pts
    return out


def resolve(model: CpuPowerModel, *, mode: str = "auto", vote: Any = None, fixed_mhz: float | None = None,
            measured: dict[float, float] | None = None) -> DsuPolicy:
    if mode not in MODES:
        raise ValueError(f"unknown DSU mode '{mode}' (use {', '.join(MODES)})")
    table, source = ({}, None)
    if vote:
        table, source = _table(vote), "request"
    elif model.dsu_vote:
        table, source = dict(model.dsu_vote), model.dsu_vote_source or "topology"
    eff = mode
    if mode == "auto":
        eff = "vote" if table else "measured" if measured else "proportional"
    if eff == "vote" and not table:
        raise ValueError("DSU mode 'vote' needs a vote table (topology cpu.dsu.vote or request dsu_vote)")
    if eff == "measured" and not measured:
        raise ValueError("DSU mode 'measured' needs a measured DSU residency in the profile")
    if eff == "fixed" and not (fixed_mhz and fixed_mhz > 0):
        raise ValueError("DSU mode 'fixed' needs dsu_fixed_mhz > 0")
    return DsuPolicy(mode=eff, vote=table if eff == "vote" else {}, fixed_mhz=fixed_mhz if eff == "fixed" else None,
                     measured=measured if eff == "measured" else None,
                     source=source if eff == "vote" else ("profile" if eff == "measured" else None), requested=mode)


def _snap(dsu: ClusterModel, mhz: float) -> float:
    return next((o.mhz for o in dsu.opps if o.mhz >= mhz - 1e-9), dsu.opps[-1].mhz)


def cluster_vote(policy: DsuPolicy, cluster: ClusterModel, mhz: float) -> float | None:
    """DSU MHz this cluster requests at ``mhz`` (None = the table has no entry for it)."""
    pts = policy.vote.get(cluster.name)
    if pts is None:
        pts = next((v for k, v in policy.vote.items() if k.lower() == cluster.name.lower()), None)
    if pts is None and cluster.core_type:
        pts = next((v for k, v in policy.vote.items() if k.lower() == cluster.core_type.lower()), None)
    if pts is None:
        return None
    return next((d for f, d in pts if f >= mhz - 1e-9), pts[-1][1])


def residency(policy: DsuPolicy, model: CpuPowerModel, busy: dict[str, float], fmax: dict[str, float]) -> dict[float, float]:
    """DSU frequency residency for one placement. ``busy`` = {cluster: MHz} of clusters with work."""
    dsu = model.dsu
    assert dsu is not None and dsu.opps
    if policy.mode == "measured":
        return dict(policy.measured or {})
    if policy.mode == "fixed":
        return {_snap(dsu, float(policy.fixed_mhz or 0.0)): 1.0}
    if policy.mode == "vote":
        by = {c.name: c for c in model.clusters}
        votes = [v for n, f in busy.items() if (v := cluster_vote(policy, by[n], f)) is not None]
        return {_snap(dsu, max(votes)) if votes else dsu.opps[0].mhz: 1.0}
    rel = max((f / fmax[n] for n, f in busy.items()), default=0.0)
    return {_snap(dsu, rel * dsu.opps[-1].mhz): 1.0}


def power(model: CpuPowerModel, res: dict[float, float], active: float, power_gating_eff: float) -> dict[str, Any]:
    """DSU power for a frequency residency and the union activity of all CPUs."""
    dsu = model.dsu
    assert dsu is not None
    total = sum(res.values())
    dyn = sum(s / total * dsu.core_mw(f, model.fallback_mv) for f, s in res.items()) * active
    leak = sum(s / total * dsu.leak_mw_per_core(dsu.voltage_mv(f, model.fallback_mv)) for f, s in res.items())
    static = leak * (active + (1 - active) * (1 - power_gating_eff))
    return {"mhz": round(sum(f * v for f, v in res.items()) / total, 1), "active_ratio": round(active, 6),
            "dynamic_mw": round(dyn, 6), "static_mw": round(static, 6), "total_mw": round(dyn + static, 6)}


def params_view(model: CpuPowerModel, power_gating_eff: float) -> dict[str, Any] | None:
    """What a client needs to recompute DSU power for another vote table (cluster OPPs stay fixed)."""
    dsu = model.dsu
    if dsu is None or not dsu.opps:
        return None
    return {"opps": [{"mhz": o.mhz, "mv": o.mv, "mw_per_core": o.mw_per_core} for o in dsu.opps],
            "leak_mw_per_core_at_ref": dsu.leak_mw_per_core_at_ref, "leak_ref_mv": dsu.leak_ref_mv,
            "leak_exponent": dsu.leak_exponent, "fallback_mv": model.fallback_mv, "power_gating_eff": power_gating_eff,
            "clusters": [{"name": c.name, "core_type": c.core_type, "opps_mhz": [o.mhz for o in c.opps]} for c in model.clusters]}
