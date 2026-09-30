"""CPU (SW task) power shared by the simulation runner and the timing budget.

Linux Energy-Model convention per cluster:

    P_task = coeff[uW/MHz/V^2] * f[MHz] * V^2 * util / 1000   [mW]
    util   = CPU-active ms per frame / frame period ms

CPU-active time per frame for one SW task (runner):

    active = (wall_ms - included HW time) * invocations_per_frame * cpu_active_ratio

- ``wall_ms``: the variant's sw_timing statistic (``sw_timing_case``).
- included HW time: ``includes_hw_nodes`` of an inclusive stage run on HW, not
  on the CPU (e.g. pre_me_rta includes LME).
- ``invocations_per_frame``: ``count_per_frame`` for per-invocation samples.
- ``cpu_active_ratio`` (sw_timing, default 1): wall time that is CPU work;
  I/O completion (storage_write) or waits are mostly not.
- cluster: sw_timing ``cluster`` (name matched to the params cluster names,
  or an index 0..3), else the model default.

The coefficients are catalog/profiler values until PMU cycles per task are
calibrated in; results are labelled with their source.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# Linux EM / exynos-cpu-profiler coefficients from ip-cpu-s5e9965 (uW per MHz per V^2).
PROFILER_COEFF: tuple[float, ...] = (449.0, 449.0, 505.0, 1127.0)
DEFAULT_CLUSTER_NAMES: tuple[str, ...] = ("little", "mid", "big", "prime")


@dataclass(frozen=True)
class CpuPowerModel:
    coeff_uw_per_mhz_v2: tuple[float, ...] = PROFILER_COEFF
    cluster_names: tuple[str, ...] = DEFAULT_CLUSTER_NAMES
    default_cluster: int = 1
    freq_mhz: float = 2000.0
    volt_v: float = 0.80
    source: str = "ip-cpu-s5e9965 profiler coefficients; cluster/freq/volt assumed"
    model_id: str = "em-v1"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = [self.freq_mhz, self.volt_v, *self.coeff_uw_per_mhz_v2]
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("CPU power parameters must be finite and positive")
        if not 0 <= self.default_cluster < len(self.coeff_uw_per_mhz_v2):
            raise ValueError("CPU default cluster index is out of range")

    @classmethod
    def from_params(cls, params: Any | None) -> CpuPowerModel:
        """Model from ``power_model_params.cpu`` (unset fields keep the defaults)."""
        if params is None:
            return cls()
        cpu = params.cpu
        values: dict[str, Any] = {}
        if cpu.clusters:
            values["coeff_uw_per_mhz_v2"] = tuple(c.coeff_uw_per_mhz_v2 for c in cpu.clusters)
            values["cluster_names"] = tuple(c.name for c in cpu.clusters)
        if cpu.default_cluster is not None:
            values["default_cluster"] = cpu.default_cluster
        if cpu.freq_mhz is not None:
            values["freq_mhz"] = cpu.freq_mhz
        if cpu.volt_v is not None:
            values["volt_v"] = cpu.volt_v
        values["source"] = params.params_ref + (f" ({cpu.source})" if cpu.source else "")
        return cls(**values)

    def cluster_index(self, cluster: str | int | None) -> int:
        if cluster is None or cluster == "":
            return self.default_cluster
        if isinstance(cluster, int) or str(cluster).isdigit():
            index = int(cluster)
            if 0 <= index < len(self.coeff_uw_per_mhz_v2):
                return index
            raise ValueError(f"CPU cluster index {cluster} is out of range")
        names = [name.lower() for name in self.cluster_names]
        if str(cluster).lower() in names:
            return names.index(str(cluster).lower())
        raise ValueError(f"unknown CPU cluster '{cluster}' (known: {list(self.cluster_names)})")

    def task_power_mw(self, busy_ms: float, period_ms: float, *, cluster: str | int | None = None) -> float:
        util = busy_ms / period_ms if period_ms > 0 else 0.0
        coeff = self.coeff_uw_per_mhz_v2[self.cluster_index(cluster)]
        return coeff * self.freq_mhz * self.volt_v**2 * util / 1000.0

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.model_id,
            "coeff_uw_per_mhz_v2": list(self.coeff_uw_per_mhz_v2),
            "cluster_names": list(self.cluster_names),
            "default_cluster": self.default_cluster,
            "freq_mhz": self.freq_mhz,
            "volt_v": self.volt_v,
            "source": self.source,
        }


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
            "statistic": statistic,
            "wall_ms": round(wall, 4),
            "included_hw_ms": round(included, 4),
            "invocations_per_frame": per_frame,
            "cpu_active_ratio": ratio,
            "active_ms": round(active, 4),
            "cluster": model.cluster_names[index] if index < len(model.cluster_names) else str(index),
            "util": round(active / period_ms, 6) if period_ms > 0 else 0.0,
            "power_mw": round(power, 6),
            "value_source": profile.get("value_source"),
        })
    return rows
