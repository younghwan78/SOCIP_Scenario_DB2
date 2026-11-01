"""Exact scheduler equivalence against the cluster evaluator before its fast energy path.

The reference is intentionally frozen: sharing the new frequency/power helpers
would let a matching regression in the report and trial energy escape detection.
"""
from __future__ import annotations

import random
from dataclasses import replace

import pytest

from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim import cpu_sched as sched
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile


def _legacy_cluster_eval(ctx, name, cpus, policies):
    """Frozen cluster evaluator from 01bc705, before performance-only changes."""
    c = ctx.by_name[name]
    freqs = sched._freqs(c, ctx.model)
    fmax, cap, period = freqs[-1], ctx.caps[name], ctx.period
    pg = ctx.sched.power_gating_eff

    def request(mhz):
        req = 0.0
        for ths in cpus:
            if not ths:
                continue
            total = sum(ctx.util(t, name, mhz) for t in ths)
            umin = max(policies.get(t.task, sched.TaskPolicy()).uclamp_min for t in ths)
            umax = max(policies.get(t.task, sched.TaskPolicy()).uclamp_max for t in ths)
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
    boosted = []
    if ctx.sched.deadline_boost and ctx.budgets_ms:
        # deliberate model change (2026-11): a task's threads on one CPU run one after another, so the budget
        # bounds their sum on that CPU (it bounded each thread alone before)
        need = {}
        for index, ths in enumerate(cpus):
            for t in ths:
                if t.task in ctx.budgets_ms:
                    need.setdefault((index, t.task), []).append(t)
        late = [k for k, ts in need.items() if sum(t.ms(c, mhz) for t in ts) > ctx.budgets_ms[k[1]] + 1e-9]
        if late:
            for f in freqs:
                if f > mhz and all(sum(t.ms(c, f) for t in ts) <= ctx.budgets_ms[k[1]] + 1e-9 for k, ts in need.items()):
                    mhz = f
                    break
            else:
                mhz = freqs[-1]
            boosted = sorted({k[1] for k in late})
    mv = c.voltage_mv(mhz, ctx.model.fallback_mv)
    p_core = c.core_mw(mhz, ctx.model.fallback_mv)
    leak = c.leak_mw_per_core(mv)
    ids = list(c.cpus) + [None] * max(0, c.cores - len(c.cpus))
    rows, dynamic, static, busy_total = [], 0.0, 0.0, 0.0
    tasks_ms = {}
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
            "busy_ms": round(busy, 4), "overloaded": busy > period + 1e-9,
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


def _model(with_opps=True):
    model = CpuPowerModel.from_params(PowerModelParams.model_validate({
        "id": "pmp-scheduler-equivalence", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-test",
        "cpu": {"clusters": [
            {"name": "LITTLE", "core_type": "L", "cores": 2, "cpus": [0, 1], "ipc_rel": 0.5,
             "leakage": {"mw_per_core_at_ref": 5.75, "ref_mv": 700, "exponent": 2.5},
             "opps": [{"mhz": 500, "mv": 600, "mw_per_core": 20}, {"mhz": 1000, "mv": 700, "mw_per_core": 50}]},
            {"name": "BIG", "core_type": "B", "cores": 2, "ipc_rel": 1.0,
             "leakage": {"mw_per_core_at_ref": 12.25, "ref_mv": 800, "exponent": 1.5},
             "opps": [{"mhz": 1000, "mv": 700, "mw_per_core": 150}, {"mhz": 2000, "mv": 850, "mw_per_core": 450}]}],
            "default_cluster": 0}}))
    if not with_opps:
        model = replace(model, clusters=tuple(replace(c, opps=(), coeff_uw_per_mhz_v2=449.0)
                                              for c in model.clusters))
    return model


def _ctx(model, period=1000 / 30, **overrides):
    config = sched.SchedConfig.from_model(model, **overrides)
    return sched._Ctx(model, config, period, sched.capacities(model, config),
                      {c.name: c for c in model.clusters}, {"eis": 9.25, "background": 3.0})


@pytest.mark.parametrize("util_model", ["util_est", "pelt_avg"])
@pytest.mark.parametrize("energy_includes_static", [False, True])
@pytest.mark.parametrize("deadline_boost", [False, True])
@pytest.mark.parametrize("with_opps", [False, True])
def test_cluster_energy_and_report_match_frozen_reference(util_model, energy_includes_static, deadline_boost, with_opps):
    model = _model(with_opps)
    rng = random.Random(2600)
    policies = {"eis": sched.TaskPolicy(uclamp_min=128, uclamp_max=768),
                "background": sched.TaskPolicy(uclamp_max=256)}
    overrides = dict(util_model=util_model, energy_includes_static=energy_includes_static,
                     deadline_boost=deadline_boost)
    for period in [0.0, 1000 / 240, 1000 / 30]:
        for cluster in model.clusters:
            for count in [0, 1, 2, 7, 12]:
                cpus = [[] for _ in range(cluster.cores)]
                for i in range(count):
                    task = ["eis", "background", "default"][i % 3]
                    cpus[rng.randrange(cluster.cores)].append(sched.Thread(
                        task, str(i), rng.choice([0.0, 0.7e6, 4e6, 30e6]), rng.choice([0.0, 0.15, 2.0]),
                        growth=rng.choice([0.5, 1.0, 1.2])))
                expected = _legacy_cluster_eval(_ctx(model, period, **overrides), cluster.name, cpus, policies)
                actual = sched._cluster_eval(_ctx(model, period, **overrides), cluster.name, cpus, policies)
                energy = sched._cluster_energy(_ctx(model, period, **overrides), cluster.name, cpus, policies)
                assert actual == expected
                assert energy == expected["energy_mw"]  # no tolerance: EAS uses energy differences to break ties


@pytest.mark.parametrize("util_model", ["util_est", "pelt_avg"])
@pytest.mark.parametrize("max_cases,method", [(12, "beam"), (1000, "exhaustive")])
def test_complete_sweep_matches_frozen_reference(monkeypatch, util_model, max_cases, method):
    model = _model()
    profile = CpuProfile(tasks=[
        CpuTaskProfile(task="eis", cluster="LITTLE", cycles=8e6, stall_cycles=1e6,
                       threads={"a": 5e6, "b": 3e6}),
        CpuTaskProfile(task="ui", cluster="BIG", cycles=2e6),
    ], clusters={"LITTLE": CpuClusterProfile(cycles=8e6), "BIG": CpuClusterProfile(cycles=2e6)})
    spec = sched.SweepSpec(max_cases=max_cases, util_model=util_model, energy_includes_static=True,
                           budgets_ms={"eis": 12}, growth={"eis": 1.2},
                           task_policy={"ui": {"uclamp_min": 128, "prefer_idle": True}},
                           knobs=("pin", "upto", "uclamp_min", "uclamp_max"),
                           uclamp_min_levels=(256,), uclamp_max_levels=(128, 768))
    actual = sched.cpu_sweep(profile, target=model, fps=30, spec=spec)
    assert actual["range"]["method"] == method
    monkeypatch.setattr(sched, "_cluster_eval", _legacy_cluster_eval)
    monkeypatch.setattr(sched, "_cluster_energy", lambda ctx, name, cpus, policies:
                        _legacy_cluster_eval(ctx, name, cpus, policies)["energy_mw"])
    assert sched.cpu_sweep(profile, target=model, fps=30, spec=spec) == actual
