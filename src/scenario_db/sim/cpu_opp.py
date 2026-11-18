"""CPU OPP as a timing input: SW runtime and CPU power at a chosen cluster frequency (review finding S-05, step 1).

SW task runtimes are declared at the CPU model's frequency (``TimingBudgetOptions.cpu.freq_mhz``, the reference).
A variant that declares ``design_conditions.cpu_opp_mhz`` runs its CPU SW tasks at that OPP instead::

    runtime(f) = runtime_ref x ((1 - mem_bound) x f_ref / f + mem_bound)
    CPU power  = coeff x f x V(f)^2 x busy(f) / period

``mem_bound`` = the share of the runtime that does not follow the CPU clock (memory stalls, waits): the task's
``sw_timing.mem_bound``, else ``design_conditions.cpu_mem_bound``, else ``DEFAULT_MEM_BOUND`` (assumed).
``V(f)`` = ``design_conditions.cpu_opp_mv``, else the OPP table ``ASSUMED_CPU_OPPS`` (the E2600 MID cluster
sample of ``pmp-exynos2600-v2``; assumed). Only CPU tasks (``hw_name`` CPU) move; GPU / DSP tasks timed by
``sw_timing`` keep their runtime.

So the CPU clock becomes an exploration axis (lever ``cpu_opp``): a lower OPP lowers V and power per cycle but
stretches the SW, which eats the NRT / Post budget and the SW growth tolerance. Opt-in: a variant without
``cpu_opp_mhz`` computes exactly as before.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULT_MEM_BOUND = 0.3
ASSUMED_CPU_OPPS: tuple[tuple[float, float], ...] = ((400.0, 600.0), (1000.0, 650.0), (1600.0, 720.0), (2000.0, 800.0))


def _number(value: Any, what: str, lo: float, hi: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a number")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number, got {value!r}") from None
    if not math.isfinite(x) or x < lo or x > hi:
        raise ValueError(f"{what} = {x:g} is out of range [{lo:g}, {hi:g}]")
    return x


def opp_mv(mhz: float, table: tuple[tuple[float, float], ...] = ASSUMED_CPU_OPPS) -> float:
    """Voltage of the lowest OPP at or above ``mhz`` (refused above the table)."""
    for f, mv in table:
        if f >= mhz - 1e-9:
            return mv
    raise ValueError(f"cpu_opp_mhz {mhz:g} is above the OPP table (max {table[-1][0]:g} MHz)")


def cpu_opp_condition(design: dict[str, Any] | None) -> dict[str, Any] | None:
    """The declared OPP condition, or None when the variant does not opt in."""
    design = design or {}
    if design.get("cpu_opp_mhz") in (None, ""):
        return None
    mhz = _number(design["cpu_opp_mhz"], "cpu_opp_mhz", 100.0, 5000.0)
    mv = _number(design["cpu_opp_mv"], "cpu_opp_mv", 300.0, 1500.0) if design.get("cpu_opp_mv") not in (None, "") else opp_mv(mhz)
    mem = (_number(design["cpu_mem_bound"], "cpu_mem_bound", 0.0, 1.0)
           if design.get("cpu_mem_bound") not in (None, "") else DEFAULT_MEM_BOUND)
    return {"mhz": mhz, "mv": mv, "mem_bound": mem,
            "mv_source": "design_conditions" if design.get("cpu_opp_mv") not in (None, "") else "assumed OPP table"}


def factor(ref_mhz: float, mhz: float, mem_bound: float) -> float:
    return (1.0 - mem_bound) * ref_mhz / mhz + mem_bound


def apply_cpu_opp(options, tasks: dict[str, dict[str, Any]], profiles: dict[str, Any], cond: dict[str, Any]):
    """(options at the OPP, trace): CPU SW tasks scaled by :func:`factor`, CPU power evaluated at (f, V(f))."""
    from scenario_db.sim.timing_budget import SwTaskAdjustment

    ref = float(options.cpu.freq_mhz)
    adjustments = dict(options.task_adjustments)
    scaled: dict[str, dict[str, float]] = {}
    for tid, task in tasks.items():
        if task.get("task_type") != "sw" or not str(task.get("hw_name") or "").upper().startswith("CPU"):
            continue
        row = profiles.get(tid) or {}
        mem = (_number(row["mem_bound"], f"{tid}: sw_timing.mem_bound", 0.0, 1.0)
               if row.get("mem_bound") is not None else cond["mem_bound"])
        k = factor(ref, cond["mhz"], mem)
        old = adjustments.get(tid)
        if old is not None and old.scale is None:
            raise ValueError(f"{tid}: a delta_ms adjustment cannot be combined with cpu_opp_mhz (use a scale)")
        adjustments[tid] = SwTaskAdjustment(scale=k * (old.scale if old is not None else 1.0))
        scaled[tid] = {"mem_bound": mem, "factor": round(k, 4)}
    cpu = options.cpu.model_copy(update={"freq_mhz": cond["mhz"], "volt_v": cond["mv"] / 1000.0,
                                         "source": f"{options.cpu.source}; OPP {cond['mhz']:g} MHz / {cond['mv']:g} mV ({cond['mv_source']})"})
    trace = {"mhz": cond["mhz"], "mv": cond["mv"], "mv_source": cond["mv_source"], "ref_mhz": ref,
             "ref_mv": round(float(options.cpu.volt_v) * 1000.0, 1), "mem_bound_default": cond["mem_bound"],
             "tasks": scaled, "value_source": "assumed"}
    return options.model_copy(update={"task_adjustments": adjustments, "cpu": cpu}), trace
