"""MID-tier rebalance: exact per-cluster decomposition, symmetry, search, constraints."""
from __future__ import annotations

import pathlib
from dataclasses import replace

import pytest
import yaml

from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_rebalance import RebalanceSpec, cpu_rebalance, default_pool
from scenario_db.sim.models import CpuClusterProfile, CpuDsuProfile, CpuProfile, CpuTaskProfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
TOPO = ROOT / "examples" / "cpu-topology"
VOTE = {"MID_LF": [[1000, 400], [1600, 900], [2000, 1500]], "MID_HF": [[1200, 400], [2000, 900], [2600, 1500]],
        "BIG_LF": [[2000, 900], [3000, 1500]], "BIG": [[2000, 900], [3600, 1500]]}
LOAD = [("eis", 17, 12.0), ("hal", 13, 10.0), ("aaa", 11, 8.0), ("isp", 9, 4.0), ("rend", 9, 10.0), ("enc", 8, 8.0),
        ("res", 7, 8.0), ("face", 6, 10.0)]


def _model(soc: str) -> CpuPowerModel:
    return CpuPowerModel.from_params(PowerModelParams.model_validate(
        yaml.safe_load((TOPO / f"pmp-exynos{soc}-cpu-example.yaml").read_text(encoding="utf-8"))))


def _profile(home: str, extra: dict[str, str] | None = None, n: int = len(LOAD)) -> CpuProfile:
    tasks = [CpuTaskProfile(task=t, cluster=home, cycles=c * 1e6, stall_cycles=c * 1.8e5,
                            threads={f"{t}.0": c * 6e5, f"{t}.1": c * 4e5}) for t, c, _ in LOAD[:n]]
    tasks += [CpuTaskProfile(task=t, cluster=cl, cycles=3e6, stall_cycles=5e5) for t, cl in (extra or {}).items()]
    return CpuProfile(tasks=tasks, clusters={c: CpuClusterProfile(cycles=sum(x.cycles for x in tasks if x.cluster == c))
                                             for c in {x.cluster for x in tasks}})


BUDGETS = {t: b for t, _, b in LOAD}


def _run(soc="2600", home="MID_LF0", **kw):
    prof = kw.pop("profile", None) or _profile(home, kw.pop("extra", None), kw.pop("n", len(LOAD)))
    return cpu_rebalance(prof, target=_model(soc), fps=30.0,
                         spec=RebalanceSpec(budgets_ms=BUDGETS, dsu_mode="vote", dsu_vote=VOTE, **kw))


def test_default_pool_excludes_big_family():
    assert default_pool(_model("2600")) == ["MID_LF0", "MID_LF1", "MID_HF"]
    assert default_pool(_model("2800")) == ["MID_HF0", "MID_HF1"]


def test_decomposition_matches_full_evaluate_and_beats_reference():
    r = _run()
    assert r["method"] == "exhaustive" and r["verified"] >= len(r["cases"]) > 0
    for c in [r["reference"], *r["cases"]]:
        assert c["verified"] and abs(c["model_err_mw"]) < 1e-3          # per-cluster memo == full evaluate
        assert c["mw"]["dsu"] == pytest.approx(c["dsu"]["total_mw"], abs=1e-3)
    best = r["best"]
    assert best["feasible"] and best["total_mw"] < r["reference"]["total_mw"]
    assert best["mhz"]["MID_LF0"] < r["reference"]["mhz"]["MID_LF0"]    # load left the hot cluster
    assert [c["total_mw"] for c in r["cases"]] == sorted(c["total_mw"] for c in r["cases"])
    # DSU follows the max vote of the busy clusters
    def vote(core: str, f: float) -> float:
        return next((d for x, d in VOTE[core] if x >= f), VOTE[core][-1][1])
    for c in (r["reference"], best):
        busy = [(n, cl["mhz"]) for n, cl in c["clusters"].items() if cl["busy_ms"] > 0]
        assert c["mhz"]["dsu"] == max(vote(n.rstrip("01"), f) for n, f in busy)
    assert best["mhz"]["dsu"] <= r["reference"]["mhz"]["dsu"]


def test_identical_clusters_are_enumerated_once_and_labelled_with_fewest_moves():
    r = _run("2800", home="MID_HF0")
    assert r["symmetric"] == [["MID_HF0", "MID_HF1"]]
    assert r["evaluated"] == 2 ** len(LOAD) // 2                         # one ordering of HF0 / HF1
    for c in r["cases"]:
        assert len(c["moved"]) <= len(LOAD) // 2                          # HF0 <-> HF1 relabelled to move the fewest
    # frozen load on one of them breaks the symmetry
    r2 = _run("2800", home="MID_HF0", extra={"sf": "MID_HF1"}, locks={"sf": "exclude"})
    assert r2["symmetric"] == [] and r2["evaluated"] == 2 ** len(LOAD)


def test_local_search_close_to_exhaustive():
    exact = _run(max_exhaustive=10 ** 7)
    local = _run(max_exhaustive=1)
    assert exact["method"] == "exhaustive" and local["method"] == "local"
    assert local["best"]["total_mw"] <= exact["best"]["total_mw"] * 1.01
    assert local["evaluated"] < exact["evaluated"]


def test_locks_movable_and_co_move():
    r = _run(locks={"eis": "MID_LF0", "isp": "exclude"}, movable=["hal", "aaa", "rend", "enc", "res", "face", "eis"],
             co_move=[["hal", "res"]])
    units = {u["unit"] for u in r["units"]}
    assert "eis" not in units and "isp" not in units and "hal+res" in units
    for c in r["cases"]:
        assert c["assign"]["hal+res"] in r["pool"]
    assert {"eis", "isp"} <= set(r["frozen"])
    with pytest.raises(ValueError):
        _run(pool=["MID_LF0", "NOPE"])
    with pytest.raises(ValueError):
        _run(locks={"nope": "MID_LF0"})
    with pytest.raises(ValueError):
        _run(pool=["MID_LF0"])


def test_curve_opp_states_and_boundaries():
    r = _run()
    curve = r["curve"]
    assert curve[0]["step"] == 0 and curve[0]["moved_unit"] is None and curve[0]["moved_util_pct"] == 0
    assert len(curve) == len(r["units"]) + 1 and curve[-1]["moved_util_pct"] == 100.0
    assert min(p["total_mw"] for p in curve) < curve[0]["total_mw"]
    st = r["opp_states"]
    assert st[0]["min_mw"] == pytest.approx(r["best"]["total_mw"], abs=1e-2)
    assert sum(s["count"] for s in st) <= r["feasible_count"]
    lf0 = next(b for b in r["boundaries"]["reference"] if b["cluster"] == "MID_LF0")
    assert lf0["next_lower_mhz"] < lf0["mhz"] and lf0["delta_util_needed"] >= 0 and lf0["candidates"]


def test_cross_soc_mapping_warns_on_default_fallback():
    prof = _profile("MID_LF0")
    r = cpu_rebalance(prof, target=_model("2800"), base=_model("2600"), fps=30.0,
                      spec=RebalanceSpec(budgets_ms=BUDGETS, dsu_mode="vote", dsu_vote=VOTE))
    assert any("no same-name / same-core-type" in w for w in r["warnings"])


def test_api_service(monkeypatch):
    from scenario_db.api.schemas.cpu import CpuRebalanceRequest
    import scenario_db.api.services.cpu as svc

    monkeypatch.setattr(svc, "_model", lambda _db, _ref: _model("2600"))
    req = CpuRebalanceRequest(cpu_profile=_profile("MID_LF0", n=5), power_params_ref="p", budgets_ms=BUDGETS,  # type: ignore[arg-type]
                              pool=["MID_LF0", "MID_HF"], dsu_vote=VOTE, top=5)
    out = svc.run_cpu_rebalance(object(), req)  # type: ignore[arg-type]
    assert out.result["pool"] == ["MID_LF0", "MID_HF"] and len(out.result["cases"]) <= 5
    with pytest.raises(svc.UnprocessableError):
        svc.run_cpu_rebalance(object(), CpuRebalanceRequest(cpu_profile=_profile("MID_LF0"), power_params_ref="p", pool=["X", "Y"]))  # type: ignore[arg-type]


@pytest.mark.parametrize("difference", ["capacity", "vote"])
def test_symmetry_respects_capacity_and_named_dsu_votes(difference):
    model = _model("2800")
    if difference == "capacity":
        from scenario_db.sim.cpu_sched import SchedConfig
        model = replace(model, scheduler=SchedConfig(capacity={"MID_HF0": 300, "MID_HF1": 600}))
    vote = {"MID_HF0": [[2600, 1500]], "MID_HF1": [[2600, 400]]} if difference == "vote" else VOTE
    r = cpu_rebalance(_profile("MID_HF0", n=3), target=model, fps=30,
                      spec=RebalanceSpec(dsu_mode="vote", dsu_vote=vote))
    assert r["symmetric"] == [] and r["evaluated"] == 2 ** 3
    assert all(abs(c["model_err_mw"]) < 1e-3 for c in [r["reference"], *r["cases"]])


def test_rebalance_rejects_duplicate_pool_and_mixed_home_co_move():
    with pytest.raises(ValueError, match="pool needs"):
        _run(pool=["MID_LF0", "MID_LF0"])
    with pytest.raises(ValueError, match="share a measured home"):
        _run(profile=_profile("MID_LF0", {"sf": "MID_LF1"}, n=2), co_move=[["eis", "sf"]])
    r = _run(n=2, movable=["eis", "eis", "hal"])
    assert [u["tasks"] for u in r["units"]] == [["eis"], ["hal"]]


def test_rebalance_exports_measured_dsu_residency_for_client_experiments():
    prof = _profile("MID_LF0", n=3).model_copy(update={"dsu": CpuDsuProfile(freq_residency={400.0: 0.3, 900.0: 0.7})})
    r = cpu_rebalance(prof, target=_model("2600"), fps=30, spec=RebalanceSpec(dsu_mode="measured"))
    assert r["dsu_measured"] == {400.0: 0.3, 900.0: 0.7}
    assert r["dsu_model"]["mode"] == "measured"


def test_ratio_curves_move_units_onto_one_target_and_leave_search_unchanged():
    r = _run()
    curves = {c["target"]: c for c in r["ratio_curves"]}
    assert set(curves) == set(r["pool"]) - {"MID_LF0"}       # every unit already lives on MID_LF0
    lf1 = curves["MID_LF1"]
    pts = lf1["points"]
    assert pts[0]["moved_unit"] is None and pts[0]["total_mw"] == pytest.approx(r["reference"]["total_mw"], abs=0.01)
    assert lf1["start_util_pct"] == 0.0 and pts[-1]["util_pct"] == pytest.approx(100.0)
    assert [p["util_pct"] for p in pts] == sorted(p["util_pct"] for p in pts)       # share on the target only grows
    assert lf1["best_index"] is not None and pts[lf1["best_index"]]["feasible"]
    off = _run(ratio_curves=False)
    assert off["ratio_curves"] == []
    assert off["best"]["total_mw"] == r["best"]["total_mw"] and off["evaluated"] == r["evaluated"]


def test_task_priorities_survive_the_per_split_policies():
    """scheduler.task_policy sched_class reaches every verified split (policies are rebuilt per cluster assignment)."""
    raw = yaml.safe_load((TOPO / "pmp-exynos2600-cpu-example.yaml").read_text(encoding="utf-8"))
    raw["cpu"].setdefault("scheduler", {})["task_policy"] = {"isp": {"sched_class": "fifo", "rt_priority": 50}}
    prio = cpu_rebalance(_profile("MID_LF0"), target=CpuPowerModel.from_params(PowerModelParams.model_validate(raw)), fps=30.0,
                         spec=RebalanceSpec(budgets_ms=BUDGETS, dsu_mode="vote", dsu_vote=VOTE))
    plain = _run()
    assert [c["total_mw"] for c in prio["cases"]] == [c["total_mw"] for c in plain["cases"]]   # placement / power unchanged
    assert "isp" in prio["reference"]["response_prio_ms"]       # isp shares a CPU in the measured placement
    for c in [prio["reference"], *prio["cases"]]:
        assert "response_prio_ms" in c and "min_slack_prio_ms" in c
        if "isp" in c["response_prio_ms"]:                       # the RT task never waits behind normal co-runners
            assert c["response_prio_ms"]["isp"] == pytest.approx(c["task_ms"]["isp"], abs=1e-3)
    assert all("response_prio_ms" not in c for c in plain["cases"])
    assert prio["task_sched"] == {"isp": {"sched_class": "fifo", "rt_priority": 50}} and "task_sched" not in plain
