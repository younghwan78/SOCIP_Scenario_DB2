"""Measured CPU profile (per frame) from ``metric_observations``.

``meas_import/pmu_digest.py`` (neutral samples) and ``meas_import/table_adapter.py``
(any perfetto / simpleperf table export, mapped by configuration) produce:

- ``cpu.cycles_pf`` / ``cpu.instructions_pf`` / ``cpu.stall_cycles_pf`` /
  ``cpu.bus_bytes_pf``: per frame; scope ``task_cluster`` (ref ``task@cluster``)
  or ``cluster``.
- ``cpu.freq_residency``: scope ``cluster_freq`` (ref ``cluster@MHz``), time share.
- ``cpu.clock_gated_ratio`` / ``cpu.power_gated_ratio`` / ``cpu.active_ratio``:
  scope ``cluster``, time share.

A cluster named like the topology's DSU (default ``DSU``) becomes the DSU entry.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from scenario_db.sim.models import CpuClusterProfile, CpuDsuProfile, CpuProfile, CpuTaskProfile

_COUNTERS = {
    "cpu.cycles_pf": "cycles",
    "cpu.instructions_pf": "instructions",
    "cpu.stall_cycles_pf": "stall_cycles",
    "cpu.bus_bytes_pf": "bus_bytes",
}
_RATIOS = {
    "cpu.clock_gated_ratio": "clock_gated_ratio",
    "cpu.power_gated_ratio": "power_gated_ratio",
    "cpu.active_ratio": "active_ratio",
}


def _value(item: dict[str, Any]) -> float | None:
    value = item.get("value")
    if value is None:
        value = (item.get("stats") or {}).get("mean")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def cpu_profile_from_observations(
    observations: Iterable[dict[str, Any]],
    *,
    evidence_ref: str | None = None,
    dsu_name: str = "DSU",
) -> CpuProfile | None:
    """CpuProfile from observations, or None when they carry no per-frame CPU data."""
    tasks: dict[tuple[str, str], dict[str, float]] = {}
    clusters: dict[str, dict[str, Any]] = {}
    for item in observations:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric_id") or "")
        scope = item.get("scope") or {}
        kind, ref = scope.get("kind"), str(scope.get("ref") or "")
        value = _value(item)
        if value is None or not ref:
            continue
        if metric in _COUNTERS and kind == "task_cluster":
            task, _, cluster = ref.rpartition("@")
            if task and cluster:
                tasks.setdefault((task, cluster), {})[_COUNTERS[metric]] = value
        elif metric in _COUNTERS and kind == "cluster":
            clusters.setdefault(ref, {})[_COUNTERS[metric]] = value
        elif metric == "cpu.freq_residency" and kind == "cluster_freq":
            cluster, _, freq = ref.rpartition("@")
            try:
                mhz = float(freq)
            except ValueError:
                continue
            if cluster and mhz > 0 and value > 0:
                clusters.setdefault(cluster, {}).setdefault("freq_residency", {})[mhz] = value
        elif metric in _RATIOS and kind == "cluster":
            clusters.setdefault(ref, {})[_RATIOS[metric]] = value
    if not tasks and not clusters:
        return None
    dsu = None
    cluster_rows: dict[str, CpuClusterProfile] = {}
    for name, raw in clusters.items():
        if name.lower() == dsu_name.lower():
            dsu = CpuDsuProfile(
                freq_residency=raw.get("freq_residency"),
                active_ratio=raw.get("active_ratio"),
                power_gated_ratio=raw.get("power_gated_ratio"),
            )
            continue
        raw.pop("active_ratio", None)
        cluster_rows[name] = CpuClusterProfile(**raw)
    # A cluster seen only through its tasks still needs an entry (cycles = task sum).
    for (_, cluster), counters in tasks.items():
        row = cluster_rows.setdefault(cluster, CpuClusterProfile())
        if row.cycles is None:
            row.cycles = sum(v.get("cycles", 0.0) for (_, c), v in tasks.items() if c == cluster)
    return CpuProfile(
        evidence_ref=evidence_ref,
        tasks=[CpuTaskProfile(task=t, cluster=c, **v) for (t, c), v in sorted(tasks.items())],
        clusters=cluster_rows,
        dsu=dsu,
    )


def cpu_profile_from_evidence(evidence: Any, *, evidence_ref: str | None = None, dsu_name: str = "DSU") -> CpuProfile | None:
    """Profile from a measurement evidence (row or dict).

    Per-frame counters and gating come from ``metric_observations``; a cluster
    without ``cpu.freq_residency`` observations takes the perfetto residency in
    ``cpu_breakdown[].freq_residency`` ({freq_mhz, ratio}) when present.
    """
    get = evidence.get if isinstance(evidence, dict) else lambda key: getattr(evidence, key, None)
    profile = cpu_profile_from_observations(get("metric_observations") or [], evidence_ref=evidence_ref,
                                            dsu_name=dsu_name)
    if profile is None:
        return None
    for entry in get("cpu_breakdown") or []:
        if not isinstance(entry, dict) or not entry.get("cluster"):
            continue
        name = str(entry["cluster"])
        bins = entry.get("freq_residency") or []
        residency = {float(b["freq_mhz"]): float(b["ratio"]) for b in bins
                     if isinstance(b, dict) and b.get("freq_mhz") and b.get("ratio")}
        if not residency:
            continue
        if name.lower() == dsu_name.lower():
            if profile.dsu is None:
                profile.dsu = CpuDsuProfile(freq_residency=residency)
            elif not profile.dsu.freq_residency:
                profile.dsu.freq_residency = residency
            continue
        row = profile.clusters.get(name)
        if row is not None and not row.freq_residency:
            row.freq_residency = residency
    # Assignments above bypass field validators; validate imported fallback bins
    # before they can reach the power model.
    return CpuProfile.model_validate(profile.model_dump())
