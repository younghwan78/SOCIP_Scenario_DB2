"""RT chain order, RT placement (cpupri), per-CPU task time and the Timing Budget coupling of the CPU sweep.

The RT chain is whatever the variant's pipeline orders within one frame (``timing_budget._sw_order``), so a
next project with another chain structure needs no code change: its pipeline gives the order.
"""
from __future__ import annotations

import pytest

from scenario_db.api import schemas as _schemas  # noqa: F401  (package import for the service module)
from scenario_db.api.schemas.cpu import CpuSweepRequest
from scenario_db.api.services import cpu as svc
from scenario_db.api.services.cpu import _mark_serial, coupling_stages, scale_coupling
from scenario_db.models.capability.power_model import CpuSchedulerParams, PowerModelParams
from scenario_db.sim import cpu_sched
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_rebalance import RebalanceSpec, cpu_rebalance
from scenario_db.sim.cpu_sched import (SchedConfig, StageOrder, SweepSpec, Thread, TaskPolicy, _Ctx, beam_starts, capacities,
                                       cpu_sweep, eas_place, evaluate, longest_path, measured_task_ms, packed_ms)
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile
from scenario_db.sim.timing_budget import _sw_order


def _model(cores: int = 2, **sched) -> CpuPowerModel:
    return CpuPowerModel.from_params(PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x", "cpu": {
            "clusters": [{"name": "MID", "core_type": "M", "cores": cores, "ipc_rel": 1.0, "opps": [
                {"mhz": 1000, "mv": 700, "mw_per_core": 100}, {"mhz": 2000, "mv": 850, "mw_per_core": 300}]}],
            "default_cluster": 0, **({"scheduler": sched} if sched else {})}}))


def _ctx(model: CpuPowerModel, serial=()) -> _Ctx:
    sched = SchedConfig.from_model(model)
    return _Ctx(model, sched, 1000 / 30, capacities(model, sched), {c.name: c for c in model.clusters}, {},
                frozenset(frozenset(p) for p in serial))


RT = {"sched_class": "fifo", "rt_priority": 1}


# ---------------------------------------------------------------- pipeline order
def test_sw_order_follows_the_task_graph_through_hw_and_ignores_cross_frame_edges():
    sw = {"nrt": [{"task": t, "kind": "sw"} for t in ("crta", "me", "irta", "side")] + [{"task": "MCSC", "kind": "ip_overhead"}]}
    edges = [{"from": "crta", "to": "ISP"}, {"from": "ISP", "to": "me"}, {"from": "me", "to": "MTNR"},
             {"from": "MTNR", "to": "irta"},
             {"from": "irta", "to": "crta", "frame_offset": 1},       # next frame's input: not an in-frame order
             {"from": "ISP", "to": "side"}]                           # parallel branch after ISP
    order = _sw_order(sw, edges)["nrt"]
    assert ["crta", "me"] in order and ["me", "irta"] in order and ["crta", "irta"] in order
    assert ["crta", "side"] in order                                   # side waits for crta through ISP
    assert not any("side" in p and ("me" in p or "irta" in p) for p in order)   # parallel: unordered
    assert all(p[1] != "crta" for p in order)
    # a same-frame cycle leaves the pair unordered instead of ordering both ways
    assert _sw_order({"x": [{"task": "a", "kind": "sw"}, {"task": "b", "kind": "sw"}]},
                     [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}])["x"] == []


def test_stage_order_is_serial_only_while_the_stage_chain_fits_one_period():
    coupling = {"period_ms": 33.3, "runtime_scale": 1.0, "stretch": {}, "stages": [
        {"stage": "nrt", "sw_ms": 10.0, "hw_ms": 18.0, "overhead_ms": 0.0, "room_ms": 15.3, "tasks": [], "order": [["a", "b"]]},
        {"stage": "post", "sw_ms": 6.0, "hw_ms": 30.0, "overhead_ms": 0.0, "room_ms": 3.3, "tasks": [], "order": [["c", "d"]]}]}
    out = _mark_serial(coupling)
    assert [s["serial"] for s in out["stages"]] == [True, False]       # post: 36 ms > 33.3 ms overlaps the next frame
    stages = coupling_stages(out)
    assert [(st.stage, st.holds({}, {})) for st in stages] == [("nrt", True), ("post", False)]
    # more SW at a higher growth can push a stage over the period: its order no longer counts
    assert not any(st.holds({}, {}) for st in coupling_stages(scale_coupling(out, 1.6)))


def test_a_candidate_that_slows_the_chain_past_the_period_loses_the_order():
    """Measured: chain 10 + 20 ms in a 33.3 ms frame -> ordered. Twice the SW time on a slower placement: 40 ms."""
    st = StageOrder(stage="nrt", pairs=(("a", "b"),), sw_ms=10.0, fixed_ms=20.0, items=(("a", 4.0), ("b", 6.0)), period_ms=33.3)
    anchor = {"a": 1.0, "b": 1.5}
    assert st.holds({"a": 1.0, "b": 1.5}, anchor)
    assert not st.holds({"a": 2.0, "b": 3.0}, anchor)
    one = _model(cores=1)
    profile = CpuProfile(tasks=[CpuTaskProfile(task=t, cluster="MID", cycles=4e6) for t in ("a", "b")],
                         clusters={"MID": CpuClusterProfile(freq_residency={2000: 1})})
    tight = StageOrder(stage="nrt", pairs=(("a", "b"),), sw_ms=10.0, fixed_ms=20.0, items=(("a", 5.0), ("b", 5.0)), period_ms=33.3)
    ref = cpu_sweep(profile, target=one, fps=30, spec=SweepSpec(serial_stages=(tight,)))["reference"]
    assert ref["chain_serial"] == ["nrt"] and ref["response_ms"]["a"] == pytest.approx(ref["task_ms"]["a"], abs=1e-3)
    # a candidate is judged on its own task times against the measured placement (the anchor)
    ctx = _ctx(one)
    ctx.stages, ctx.anchor_ms = (tight,), {"a": 1.0, "b": 1.0}
    held, names = ctx.serial_for({"a": 1.0, "b": 1.0})
    assert frozenset(("a", "b")) in held and names == ["nrt"]
    slower, names = ctx.serial_for({"a": 1.5, "b": 1.5})       # 20 + 10 + 5 x 0.5 x 2 = 35 ms > 33.3 ms
    assert frozenset(("a", "b")) not in slower and names == []


# ---------------------------------------------------------------- wait (response) model
def test_ordered_chain_members_never_wait_for_each_other():
    ths = [Thread(t, t, 1e6, 0.0) for t in ("crta", "me", "other_rt")]
    pol = {t.task: TaskPolicy(sched_class="fifo", rt_priority=1) for t in ths}
    free = cpu_sched.priority_response(ths, [1.0, 2.0, 4.0], pol)
    chain = cpu_sched.priority_response(ths, [1.0, 2.0, 4.0], pol, frozenset({frozenset(("crta", "me"))}))
    assert free == [pytest.approx(7.0), pytest.approx(7.0), pytest.approx(7.0)]   # equal FIFO: everyone ahead
    assert chain == [pytest.approx(5.0), pytest.approx(6.0), pytest.approx(7.0)]  # the chain pair drops out


def test_task_time_on_a_cpu_sums_its_threads_there_and_the_bound_skips_ordered_co_runners():
    one = _model(cores=1)
    profile = CpuProfile(tasks=[CpuTaskProfile(task="a", cluster="MID", cycles=8e6, threads={"1": 4e6, "2": 4e6}),
                                CpuTaskProfile(task="b", cluster="MID", cycles=2e6)],
                         clusters={"MID": CpuClusterProfile(freq_residency={2000: 1})})
    ref = cpu_sweep(profile, target=one, fps=30, spec=SweepSpec())["reference"]
    mhz = ref["clusters"]["MID"]["mhz"]
    assert ref["task_ms"]["a"] == pytest.approx(8e6 / (mhz * 1000), abs=1e-3)       # both threads, one CPU
    assert ref["response_ms"]["b"] == pytest.approx(ref["task_ms"]["a"] + ref["task_ms"]["b"], abs=1e-3)
    chained = cpu_sweep(profile, target=one, fps=30, spec=SweepSpec(serial_pairs=(("a", "b"),)))["reference"]
    assert chained["response_ms"]["b"] == pytest.approx(chained["task_ms"]["b"], abs=1e-3)
    assert chained["response_ms"]["a"] == pytest.approx(chained["task_ms"]["a"], abs=1e-3)


# ---------------------------------------------------------------- RT placement
def test_cpupri_spreads_rt_threads_chain_members_included():
    model = _model(cores=2, rt_placement="cpupri", task_policy={"x": RT, "y": RT, "cfs": {}})
    eas = _model(cores=2, task_policy={"x": RT, "y": RT})
    big = [Thread("cfs", "cfs", 9e6, 0.0)]
    rts = [Thread("x", "x", 1e6, 0.0), Thread("y", "y", 1e6, 0.0)]
    pol = {t: cpu_sched.policy_from(RT) for t in ("x", "y")}

    def cpus(m, serial=()):
        slots, _ = eas_place(big + rts, _ctx(m, serial), pol)
        return [sorted(t.task for t in c) for c in slots["MID"]]

    # EAS: both RT threads join the CPU with the most spare capacity
    assert sorted(cpus(eas)) == [["cfs"], ["x", "y"]]
    # cpupri: the second RT thread avoids the CPU that runs the first one (CFS does not block an RT thread)
    assert sorted(cpus(model)) == [["cfs", "y"], ["x"]]
    # ordered RT chain members count too: the placement never depends on a candidate's chain verdict
    assert sorted(cpus(model, serial=[("x", "y")])) == [["cfs", "y"], ["x"]]
    with pytest.raises(ValueError):
        CpuSchedulerParams(rt_placement="push")


def test_rt_chain_member_without_a_class_is_reported():
    model = _model(cores=2, task_policy={"crta": RT})
    profile = CpuProfile(tasks=[CpuTaskProfile(task=t, cluster="MID", cycles=2e6) for t in ("crta", "me")],
                         clusters={"MID": CpuClusterProfile(freq_residency={2000: 1})})
    out = cpu_sweep(profile, target=model, fps=30, spec=SweepSpec(serial_pairs=(("crta", "me"),)))
    assert any("RT chain: 'me'" in w for w in out["warnings"])
    assert not any("RT chain" in w for w in cpu_sweep(profile, target=model, fps=30, spec=SweepSpec())["warnings"])


# ---------------------------------------------------------------- Timing Budget coupling of the sweep
def test_sweep_applies_stage_budgets_anchored_on_the_measured_placement():
    two = CpuPowerModel.from_params(PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x", "cpu": {"clusters": [
            {"name": "LITTLE", "core_type": "L", "cores": 2, "ipc_rel": 0.5, "opps": [
                {"mhz": 500, "mv": 600, "mw_per_core": 20}, {"mhz": 1000, "mv": 700, "mw_per_core": 50}]},
            {"name": "BIG", "core_type": "B", "cores": 2, "ipc_rel": 1.0, "opps": [
                {"mhz": 1000, "mv": 700, "mw_per_core": 150}, {"mhz": 2000, "mv": 850, "mw_per_core": 450}]}],
            "default_cluster": 0}}))
    profile = CpuProfile(tasks=[CpuTaskProfile(task="eis", cluster="BIG", cycles=6e6),
                                CpuTaskProfile(task="ui", cluster="LITTLE", cycles=1e6)],
                         clusters={"BIG": CpuClusterProfile(freq_residency={2000: 1}),
                                   "LITTLE": CpuClusterProfile(freq_residency={1000: 1})})
    free = cpu_sweep(profile, target=two, fps=30, spec=SweepSpec())
    tied = cpu_sweep(profile, target=two, fps=30, spec=SweepSpec(stretch_budgets={"eis": 1.2}))
    ms = free["measured_placement"]["task_ms"]["eis"]
    assert tied["budgets_ms"]["eis"] == pytest.approx(ms * 1.2, rel=1e-5) and tied["budget_source"] == {"eis": "stretch"}
    assert tied["measured_placement"]["feasible"] and tied["measured_placement"]["slack_ms"]["eis"] >= 0
    # without the stage budget, moving eis to LITTLE (much slower) looks like a saving; with it, it misses
    slow = lambda r: [c for c in r["cases"] + r["others"] if c["placement"].get("eis") == ["LITTLE"]]   # noqa: E731
    assert any(c["feasible"] for c in slow(free))
    assert slow(tied) and not any(c["feasible"] for c in slow(tied))
    assert next(t for t in tied["range"]["tasks"] if t["task"] == "eis")["budget_source"] == "stretch"
    # an explicit tighter budget wins over the stretch
    user = cpu_sweep(profile, target=two, fps=30, spec=SweepSpec(budgets_ms={"eis": ms * 1.05}, stretch_budgets={"eis": 1.2}))
    assert user["budget_source"] == {"eis": "user"}


def test_rebalance_uses_the_chain_order_for_the_wait_and_keeps_feasibility():
    mid2 = CpuPowerModel.from_params(PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x", "cpu": {"clusters": [
            {"name": n, "core_type": "M", "cores": 1, "ipc_rel": 1.0, "opps": [
                {"mhz": 1000, "mv": 700, "mw_per_core": 100}, {"mhz": 2000, "mv": 850, "mw_per_core": 300}]} for n in ("A", "B")],
            "default_cluster": 0, "scheduler": {"task_policy": {"crta": RT, "me": RT}}}}))
    profile = CpuProfile(tasks=[CpuTaskProfile(task=t, cluster="A", cycles=2e6) for t in ("crta", "me")],
                         clusters={"A": CpuClusterProfile(freq_residency={2000: 1})})
    spec = RebalanceSpec(pool=("A", "B"), budgets_ms={"crta": 1.5, "me": 1.5})
    free = cpu_rebalance(profile, target=mid2, fps=30, spec=spec)
    chained = cpu_rebalance(profile, target=mid2, fps=30, spec=RebalanceSpec(pool=("A", "B"), budgets_ms={"crta": 1.5, "me": 1.5},
                                                                             serial_pairs=(("crta", "me"),)))
    assert free["reference"]["min_slack_prio_ms"] < 0 <= chained["reference"]["min_slack_prio_ms"]
    assert [c["assign"] for c in free["cases"]] == [c["assign"] for c in chained["cases"]]     # ranking unchanged


def test_range_packs_a_tasks_threads_on_the_cluster_cores():
    assert packed_ms([2.0, 2.0], 1) == pytest.approx(4.0)
    assert packed_ms([2.0, 2.0], 2) == pytest.approx(2.0)
    assert packed_ms([3.0, 2.0, 2.0, 3.0, 2.0], 2) == pytest.approx(6.0)     # a bound: a real 6 ms split exists
    one = _model(cores=1)
    profile = CpuProfile(tasks=[CpuTaskProfile(task="a", cluster="MID", cycles=8e6, threads={"1": 4e6, "2": 4e6})],
                         clusters={"MID": CpuClusterProfile(freq_residency={2000: 1})})
    cell = cpu_sweep(profile, target=one, fps=30, spec=SweepSpec(budgets_ms={"a": 3.0}))["range"]["tasks"][0]["cells"]["MID"]
    assert cell["t_fmax_ms"] == pytest.approx(4.0, abs=1e-3) and not cell["meets"]      # 2 x 2 ms on one core > 3 ms


def test_growth_of_a_cpu_only_task_does_not_reach_the_timing_budget(monkeypatch):
    seen = {}

    def fake_tb(db, req):
        seen["adjust"] = sorted(req.options.task_adjustments)
        return type("R", (), {"report": {"period_ms": 33.3, "stages": []}})()

    monkeypatch.setattr("scenario_db.api.services.timing_budget.analyze_timing_budget_request", fake_tb)
    monkeypatch.setattr(svc, "_sw_tasks", lambda db, s, v: {"eis"})
    svc.timing_stretch(None, "uc", "v", growth={"eis": 1.2, "(other)": 1.5})
    assert seen["adjust"] == ["eis"]


def test_sweep_timing_impact_stays_on_the_measured_placement_with_an_eas_reference(monkeypatch):
    two = CpuPowerModel.from_params(PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x", "cpu": {"clusters": [
            {"name": "LITTLE", "core_type": "L", "cores": 2, "ipc_rel": 0.5, "opps": [
                {"mhz": 500, "mv": 600, "mw_per_core": 20}, {"mhz": 1000, "mv": 700, "mw_per_core": 50}]},
            {"name": "BIG", "core_type": "B", "cores": 2, "ipc_rel": 1.0, "opps": [
                {"mhz": 1000, "mv": 700, "mw_per_core": 150}, {"mhz": 2000, "mv": 850, "mw_per_core": 450}]}],
            "default_cluster": 0}}))
    # measured on BIG; EAS alone puts the light task on LITTLE (slower), so the EAS reference stretches its SW time
    profile = CpuProfile(tasks=[CpuTaskProfile(task="a", cluster="BIG", cycles=1e6)],
                         clusters={"BIG": CpuClusterProfile(freq_residency={2000: 1})})
    data = svc._RebalanceData(profile, two, None, ("uc", "v"))
    coupling = {"mode": "stage_slack", "period_ms": 1000 / 30, "runtime_scale": 1.0, "stretch": {"a": 2.0}, "serial_pairs": [],
                "stages": [{"stage": "nrt", "sw_ms": 5.0, "hw_ms": 10.0, "overhead_ms": 0.0, "room_ms": 23.3, "slack_ms": 18.3,
                            "stretch": 4.6, "tasks": [{"task": "a", "ms": 5.0}], "order": []}]}
    monkeypatch.setattr(svc, "_rebalance_data", lambda db, req: data)
    monkeypatch.setattr(svc, "_timing_coupling", lambda db, req, d, base=None: (coupling, True))
    monkeypatch.setattr(svc, "release_read_connection", lambda db: None)
    out = svc.run_cpu_sweep(None, CpuSweepRequest(power_params_ref="p", cpu_profile_ref="x", reference="eas",
                                                  timing_coupling="stage_slack")).result
    m, eas = out["measured_placement"], out["eas_default"]
    assert eas["placement"]["a"] != m["placement"]["a"]
    impact = out["timing_coupling"]["impact"]["reference"][0]
    # the EAS reference's stage SW change, scaled from the measured placement (it read 0 when anchored on itself)
    assert impact["delta_sw_ms"] == pytest.approx(5.0 * (eas["task_ms"]["a"] / m["task_ms"]["a"] - 1.0), abs=2e-3)
    assert impact["delta_sw_ms"] > 0
    assert out["timing_coupling"]["matched_tasks"] == ["a"]


def test_beam_also_starts_from_the_measured_placement():
    options = {"a": [{"kind": "eas"}, {"kind": "pin", "clusters": ["L"]}, {"kind": "pin", "clusters": ["B"]}],
               "b": [{"kind": "eas"}, {"kind": "pin", "clusters": ["L"]}],
               "c": [{"kind": "eas"}, {"kind": "upto", "clusters": ["L", "M"]}]}
    starts = beam_starts(["a", "b", "c"], options, {"a": ["B"], "b": ["L", "B"], "c": ["L"]})
    # a pinned to its measured B; b measured on two clusters and c without a pin option stay on EAS
    assert starts == [(0, 0, 0), (2, 0, 0)]
    assert beam_starts(["b"], options, {"b": ["L", "B"]}) == [(0,)]       # no second start when it equals EAS


def test_parallel_branches_use_the_critical_path_not_the_sum():
    """PIP-like stage: rear chain r1 -> r2 next to front f (parallel). Rear x2, front x0.5 must lengthen the chain."""
    pairs = (("r1", "r2"),)
    base = {"r1": 3.0, "r2": 3.0, "f": 5.0}
    assert longest_path(base, pairs) == pytest.approx(6.0)
    assert longest_path({"r1": 6.0, "r2": 6.0, "f": 2.5}, pairs) == pytest.approx(12.0)
    st = StageOrder(stage="nrt", pairs=pairs, sw_ms=6.0, fixed_ms=24.0, items=tuple(base.items()), period_ms=33.3)
    anchor = {"r1": 1.0, "r2": 1.0, "f": 1.0}
    assert st.holds(anchor, anchor)
    # the sum of changes (+6 -2.5 = +3.5) would read 33.5 -> still over; make it tight: the critical path says +6
    tight = StageOrder(stage="nrt", pairs=pairs, sw_ms=6.0, fixed_ms=22.0, items=tuple(base.items()), period_ms=33.3)
    assert not tight.holds({"r1": 2.0, "r2": 2.0, "f": 0.5}, anchor)     # 22 + 12 = 34 > 33.3 (sum rule: 31.5)
    # the stage timing impact follows the same path
    coupling = {"period_ms": 33.3, "stages": [{"stage": "nrt", "sw_ms": 6.0, "hw_ms": 22.0, "overhead_ms": 0.0, "room_ms": 11.3,
                                              "tasks": [{"task": t, "ms": ms} for t, ms in base.items()], "order": [list(pairs[0])]}]}
    row = svc.timing_impact(coupling, {"task_ms": anchor}, {"task_ms": {"r1": 2.0, "r2": 2.0, "f": 0.5}})[0]
    assert row["delta_sw_ms"] == pytest.approx(6.0)


def test_placement_is_the_same_whether_or_not_the_candidate_keeps_the_chain_order():
    model = _model(cores=2, rt_placement="cpupri", task_policy={"x": RT, "y": RT})
    ths = [Thread("cfs", "cfs", 9e6, 0.0), Thread("x", "x", 1e6, 0.0), Thread("y", "y", 1e6, 0.0)]
    pol = {t: cpu_sched.policy_from(RT) for t in ("x", "y")}
    st = StageOrder(stage="nrt", pairs=(("x", "y"),), sw_ms=2.0, fixed_ms=30.0, items=(("x", 1.0), ("y", 1.0)), period_ms=33.3)

    def run(anchor):
        sched = SchedConfig.from_model(model)
        ctx = _Ctx(model, sched, 1000 / 30, capacities(model, sched), {c.name: c for c in model.clusters}, {},
                   frozenset({frozenset(("x", "y"))}), frozenset(), (st,), anchor)
        case = evaluate(ths, ctx, pol, budgets_ms={}, bw_mbs=0.0)
        return [sorted(cpu["threads"]) for cpu in case["clusters"]["MID"]["cpus"]], case

    kept, a = run({"x": 10.0, "y": 10.0})          # chain fits: x and y never wait for each other
    lost, b = run({"x": 0.1, "y": 0.1})            # far slower than measured: the chain overruns, they may overlap
    assert kept == lost and a["chain_serial"] == ["nrt"] and b["chain_serial"] == []


def test_an_overloaded_cpu_is_infeasible_even_when_each_task_fits_the_period():
    one = _model(cores=1)
    profile = CpuProfile(tasks=[CpuTaskProfile(task=t, cluster="MID", cycles=40e6) for t in ("a", "b")],
                         clusters={"MID": CpuClusterProfile(freq_residency={2000: 1})})
    ref = cpu_sweep(profile, target=one, fps=30, spec=SweepSpec())["reference"]
    assert all(ms < 1000 / 30 for ms in ref["task_ms"].values())     # 20 ms each at 2 GHz
    assert ref["clusters"]["MID"]["cpus"][0]["overloaded"]
    assert ref["flags"].get("overloaded_cpu") and not ref["feasible"]


def test_release_latency_stays_on_the_critical_path():
    """runtime 3 + latency 10 next to runtime 8 (parallel): SW 13 ms; the first twice as slow -> 16 ms."""
    st = StageOrder(stage="nrt", pairs=(), sw_ms=13.0, fixed_ms=18.0, items=(("a", 3.0), ("b", 8.0)), period_ms=33.3,
                    latency_ms=(("a", 10.0),))
    assert st.holds({"a": 1.0, "b": 1.0}, {"a": 1.0, "b": 1.0})                  # 18 + 13 = 31
    assert not st.holds({"a": 2.0, "b": 1.0}, {"a": 1.0, "b": 1.0})              # 18 + 16 = 34 > 33.3 (runtime only: 31)
    assert longest_path({"a": 6.0, "b": 8.0}, (), {"a": 10.0}) == pytest.approx(16.0)
    coupling = {"period_ms": 33.3, "stages": [{"stage": "nrt", "sw_ms": 13.0, "hw_ms": 17.0, "overhead_ms": 0.0, "room_ms": 16.3,
                                              "tasks": [{"task": "a", "ms": 3.0, "latency_ms": 10.0}, {"task": "b", "ms": 8.0}],
                                              "order": []}]}
    row = svc.timing_impact(coupling, {"task_ms": {"a": 1.0, "b": 1.0}}, {"task_ms": {"a": 2.0, "b": 1.0}})[0]
    assert row["delta_sw_ms"] == pytest.approx(3.0)


def test_the_variant_sw_tasks_load_once_for_any_number_of_growths(monkeypatch):
    calls = []
    monkeypatch.setattr("scenario_db.api.services.timing_budget.analyze_timing_budget_request",
                        lambda db, req: type("R", (), {"report": {"period_ms": 33.3, "stages": []}})())
    monkeypatch.setattr(svc, "_sw_tasks", lambda db, s, v: calls.append(1) or {"t0"})
    svc.timing_stretch(None, "uc", "v", growth={f"t{i}": 1.1 for i in range(20)})
    assert len(calls) == 1


def test_longest_path_is_iterative_and_order_independent():
    n = 600
    names = [f"t{i}" for i in range(n)]
    pairs = [(names[i], names[i + 1]) for i in range(n - 1)]
    ms = {t: 1.0 for t in reversed(names)}                 # items not in topological order
    assert longest_path(ms, pairs) == pytest.approx(float(n))
    assert longest_path({"a": 1.0, "b": 2.0}, [("a", "b"), ("b", "a")]) == pytest.approx(2.0)   # a cycle does not hang


def test_sw_task_lookup_errors_are_domain_errors(monkeypatch):
    from scenario_db.exceptions import NotFoundError, UnprocessableError

    class Broken:
        def __init__(self, exc):
            self.exc = exc

        def load(self, db):
            raise self.exc

    for exc, mapped in ((ValueError("bad configured clock"), UnprocessableError), (LookupError("no variant"), NotFoundError)):
        monkeypatch.setattr("scenario_db.api.services.analysis_inputs.resolve_analysis_selection", lambda db, req, e=exc: Broken(e))
        with pytest.raises(mapped):
            svc._sw_tasks(None, "uc", "v")


def test_a_chain_through_hw_counts_both_sw_items_even_if_the_timing_budget_sw_misses_one():
    """a (8 ms) -> HW (20 ms) -> b (8 ms): the Timing Budget direct-SW path says 8 ms, the ordered chain is 36 ms."""
    st = StageOrder(stage="nrt", pairs=(("a", "b"),), sw_ms=8.0, fixed_ms=20.0, items=(("a", 8.0), ("b", 8.0)), period_ms=33.3)
    assert st.chain_ms({}, {}) == pytest.approx(36.0) and not st.holds({}, {})
    # when the Timing Budget SW holds more than the ordered items (other SW on its path), that part stays
    more = StageOrder(stage="nrt", pairs=(("a", "b"),), sw_ms=12.0, fixed_ms=10.0, items=(("a", 4.0), ("b", 4.0)), period_ms=33.3)
    assert more.chain_ms({}, {}) == pytest.approx(22.0)


def _mid(ipc: float) -> CpuPowerModel:
    return CpuPowerModel.from_params(PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x", "cpu": {"clusters": [
            {"name": "MID", "core_type": "M", "cores": 2, "ipc_rel": ipc, "opps": [{"mhz": 2000, "mv": 850, "mw_per_core": 300}]}],
            "default_cluster": 0}}))


def test_chain_anchor_is_unrounded_and_on_the_measured_soc():
    profile = CpuProfile(tasks=[CpuTaskProfile(task=t, cluster="MID", cycles=6666667.0) for t in ("a", "b")],
                         clusters={"MID": CpuClusterProfile(freq_residency={2000: 1})})
    raw = measured_task_ms(profile, model=_mid(1.0), fps=30, spec=SweepSpec())
    assert raw["a"] == pytest.approx(6666667.0 / 2e6, rel=1e-12) and raw["a"] != round(raw["a"], 4)
    # measured on a fast SoC, applied to one 4x slower: the chain grows 4x and overruns the period
    st = StageOrder(stage="nrt", pairs=(("a", "b"),), sw_ms=10.0, fixed_ms=15.0, items=(("a", 5.0), ("b", 5.0)), period_ms=1000 / 30)
    same = cpu_sweep(profile, target=_mid(1.0), fps=30, spec=SweepSpec(serial_stages=(st,)))["reference"]
    slow = cpu_sweep(profile, target=_mid(0.25), base=_mid(1.0), fps=30, spec=SweepSpec(serial_stages=(st,)))["reference"]
    assert same["chain_serial"] == ["nrt"] and slow["chain_serial"] == []
