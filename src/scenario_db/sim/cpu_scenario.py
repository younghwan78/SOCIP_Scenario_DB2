"""Profile-based CPU term for the timing budget / architecture exploration (opt-in, ``cpu_model: profile``).

The default (``flat``) CPU power of the timing budget is ``coeff * f * V^2 * util`` at one assumed cluster
OPP, so a SW-growth axis scales CPU power linearly. With a measured per-frame CPU profile the same growth
is replayed through the EAS + schedutil model (``cpu_sched``): per-task demand x growth on the measured
placement -> cluster OPPs (V^2 f), leakage, DSU vote. CPU memory traffic comes from the measured bus
bytes (``cpu.bus_bytes_pf`` x growth x fps x ``cpu_bw_scale``) instead of the modelled ``cpu.*`` DMA.

``apply_profile_cpu`` rewrites the timing-budget report's ``power`` / ``bw`` CPU parts and keeps the
flat numbers next to them (``cpu_mw_flat``, ``sw_mbs_model``) so the change stays explainable.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from scenario_db.sim.cpu_power import OTHER_TASK, CpuPowerModel
from scenario_db.sim.cpu_sched import SweepSpec, TaskPolicy, _prepare, evaluate


def profile_cpu_terms(profile: Any, *, model: CpuPowerModel, fps: float, growth: float = 1.0,
                      cpu_bw_scale: float = 1.0) -> dict[str, Any]:
    """CPU power / OPPs / bandwidth of the measured placement with every task's demand x ``growth``."""
    spec = SweepSpec(default_growth=growth, cpu_bw_scale=cpu_bw_scale)
    prep = _prepare(profile, target=model, fps=fps, spec=spec, base=None)
    policies = dict(prep.base_policies)
    names = {c.name for c in model.clusters}
    for task, demands in prep.need.items():
        where = tuple(sorted({d.base_cluster for d in demands if d.base_cluster in names}))
        if where:
            policies[task] = replace(policies.get(task, TaskPolicy()), allowed=where)
    case = evaluate(prep.threads, prep.ctx, policies, budgets_ms={}, dsu_residency=prep.dsu_res, bw_mbs=prep.bw_mbs,
                    dsu_policy=prep.dsu_policy)
    # per-task share of each cluster's power by busy time on that cluster
    by_task: dict[str, float] = {}
    for name, row in case["clusters"].items():
        tasks = [t for t, w in case["placement"].items() if name in w]
        weight = {t: case["task_ms"].get(t, 0.0) for t in tasks}
        total_w = sum(weight.values())
        for t in tasks:
            if total_w > 0:
                by_task[t] = by_task.get(t, 0.0) + row["total_mw"] * weight[t] / total_w
    dsu_mw = case["dsu"]["total_mw"] if case["dsu"] else 0.0
    if dsu_mw:
        by_task["(dsu)"] = dsu_mw
    idle = case["total_mw"] - sum(by_task.values())     # leakage of clusters no task runs on
    if idle > 1e-6:
        by_task["(idle clusters)"] = idle
    return {
        "total_mw": case["total_mw"], "dsu_mw": round(dsu_mw, 4), "growth": growth, "fps": fps,
        "clusters": {n: {"mhz": r["mhz"], "total_mw": round(r["total_mw"], 4), "busy_ms": round(r["busy_ms"], 4)}
                     for n, r in case["clusters"].items()},
        "dsu_mhz": case["dsu"]["mhz"] if case["dsu"] else None,
        "by_task": {k: round(v, 4) for k, v in sorted(by_task.items(), key=lambda kv: -kv[1]) if k != OTHER_TASK or v},
        "cpu_bw_mbs": case["cpu_bw_mbs"], "feasible": case["feasible"], "flags": case["flags"],
        "warnings": prep.warnings,
    }


def apply_profile_cpu(report: dict[str, Any], *, profile: Any, model: CpuPowerModel, growth: float,
                      bw_source: str = "measured", cpu_bw_scale: float = 1.0, profile_ref: str | None = None) -> dict[str, Any]:
    """Replace the CPU parts of a timing-budget report with the profile-based terms (in place, returned)."""
    terms = profile_cpu_terms(profile, model=model, fps=float(report["fps"]), growth=growth, cpu_bw_scale=cpu_bw_scale)
    power, bw = report["power"], report["bw"]
    power["cpu_mw_flat"] = power["cpu_mw"]
    power["cpu_by_task_flat"] = power.get("cpu_by_task", {})
    power["cpu_mw"] = round(terms["total_mw"], 2)
    power["cpu_by_task"] = {k: round(v, 3) for k, v in terms["by_task"].items()}
    power["cpu_profile"] = {"kind": "profile", "profile_ref": profile_ref or getattr(profile, "evidence_ref", None),
                            "growth": growth, "clusters": terms["clusters"], "dsu_mhz": terms["dsu_mhz"], "dsu_mw": terms["dsu_mw"],
                            "feasible": terms["feasible"], "flags": terms["flags"], "cpu_mw_flat": power["cpu_mw_flat"],
                            "bw_source": bw_source, "warnings": terms["warnings"][:10]}
    if bw_source == "measured":
        model_mbs = float(bw.get("sw_mbs") or 0.0)
        hw_mbs = float(bw.get("hw_mbs") or 0.0)
        # mW per MB/s of the BW model: the CPU's own when it had traffic, else the HW average
        k = (power["bw_sw_mw"] / model_mbs if model_mbs > 0 else power["bw_hw_mw"] / hw_mbs if hw_mbs > 0 else 0.0)
        measured = float(terms["cpu_bw_mbs"])
        bw["sw_mbs_model"] = bw.get("sw_mbs")
        bw["sw_by_task_model"] = bw.get("sw_by_task", {})
        bw["sw_mbs"] = round(measured, 1)
        # keep the modelled SW DMA nodes (compression deltas are keyed by them), scaled to the measured total
        by_task = bw.get("sw_by_task") or {}
        bw["sw_by_task"] = ({k: round(v * measured / model_mbs, 1) for k, v in by_task.items()} if model_mbs > 0 and by_task
                            else {"cpu (measured bus)": round(measured, 1)})
        bw["total_mbs"] = round(hw_mbs + measured, 1)
        total_b = bw["total_mbs"]
        bw["share_pct"] = {"hw": round(100 * hw_mbs / total_b, 1) if total_b else 0.0,
                           "sw": round(100 * measured / total_b, 1) if total_b else 0.0}
        bw["cpu_bw_source"] = "measured"
        power["bw_sw_mw_model"] = power["bw_sw_mw"]
        power["bw_sw_mw"] = round(measured * k, 2)
        power["bw_mw"] = round(power["bw_hw_mw"] + power["bw_sw_mw"], 2)
        power["cpu_profile"]["bw_mw_per_mbs"] = round(k, 6)
    total = power["cpu_mw"] + power["hw_mw"] + power["bw_mw"]
    power["total_mw"] = round(total, 2)
    power["share_pct"] = {key: (round(100 * v / total, 1) if total else 0.0)
                          for key, v in (("cpu", power["cpu_mw"]), ("hw", power["hw_mw"]), ("bw", power["bw_mw"]))}
    return report
