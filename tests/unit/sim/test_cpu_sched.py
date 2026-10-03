"""EAS + schedutil approximation and the automatic cpuset / uclamp knob sweep (Exynos2600 example)."""
from __future__ import annotations

import pathlib

import pytest
import yaml

from scenario_db.api.schemas.cpu import CpuSweepRequest
from scenario_db.api.services.cpu import run_cpu_sweep
from scenario_db.meas_import.meta import PmuSpec
from scenario_db.meas_import.pmu_digest import import_pmu_digest
from scenario_db.meas_import.table_adapter import TableSpec, table_samples
from scenario_db.models.capability.power_model import CpuSchedulerParams, PowerModelParams
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_profile import cpu_profile_from_observations
from scenario_db.sim import cpu_sched
from scenario_db.sim.cpu_sched import (
    SchedConfig,
    SweepSpec,
    Thread,
    _cluster_eval,
    _Ctx,
    capacities,
    cpu_sweep,
    eas_place,
    pelt_share,
    policy_from,
)
from scenario_db.sim.models import CpuClusterProfile, CpuProfile, CpuTaskProfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
E2600 = ROOT / "examples" / "cpu-topology" / "pmp-exynos2600-cpu-example.yaml"
SAMPLE = ROOT / "examples" / "measurement-import" / "cpu-profile-sample-e2600"


def _params(**cpu) -> PowerModelParams:
    return PowerModelParams.model_validate({
        "id": "pmp-t", "schema_version": "2.2", "kind": "power_model_params", "soc_ref": "soc-x", "cpu": cpu})


def _two(**sched) -> CpuPowerModel:
    return CpuPowerModel.from_params(_params(clusters=[
        {"name": "LITTLE", "core_type": "L", "cores": 2, "ipc_rel": 0.5, "opps": [
            {"mhz": 500, "mv": 600, "mw_per_core": 20}, {"mhz": 1000, "mv": 700, "mw_per_core": 50}]},
        {"name": "BIG", "core_type": "B", "cores": 2, "ipc_rel": 1.0, "opps": [
            {"mhz": 1000, "mv": 700, "mw_per_core": 150}, {"mhz": 2000, "mv": 850, "mw_per_core": 450}]}],
        default_cluster=0, **({"scheduler": sched} if sched else {})))


def _ctx(model: CpuPowerModel, fps: float = 30.0, budgets=None, **over) -> _Ctx:
    sched = SchedConfig.from_model(model, **over)
    return _Ctx(model, sched, 1000.0 / fps, capacities(model, sched), {c.name: c for c in model.clusters},
                dict(budgets or {}))


def test_pelt_share_average_vs_util_est_peak():
    assert pelt_share(10, 40, halflife_ms=32, peak=False) == pytest.approx(0.25)
    peak = pelt_share(10, 40, halflife_ms=32, peak=True)
    assert 0.25 < peak < 1.0
    assert pelt_share(10, 40, halflife_ms=8, peak=True) > peak     # faster PELT -> higher util
    assert pelt_share(50, 40, halflife_ms=32, peak=True) == 1.0


def test_capacity_from_ipc_fmax_or_sysfs_override():
    m = _two()
    assert capacities(m, SchedConfig.from_model(m)) == {"LITTLE": 256.0, "BIG": 1024.0}
    m2 = _two(capacity={"LITTLE": 300})
    assert capacities(m2, SchedConfig.from_model(m2))["LITTLE"] == 300.0
    with pytest.raises(ValueError):
        CpuSchedulerParams(capacity={"BIG": 2000})


def test_light_thread_stays_little_heavy_goes_big_and_threads_spread():
    m = _two()
    ctx = _ctx(m)
    light = Thread("ui", "ui", ref_cycles=1e6, stall_ms=0.0)          # 4 ms on LITTLE @500
    heavy = Thread("eis", "eis", ref_cycles=14e6, stall_ms=0.0)       # 28 ms on LITTLE @1000: does not fit
    slots, over = eas_place([light, heavy], ctx, {})
    assert [t.task for t in slots["LITTLE"][0] + slots["LITTLE"][1]] == ["ui"]
    assert any(t.task == "eis" for cpu in slots["BIG"] for t in cpu)
    assert over == []
    # two equal threads of one task use two CPUs (most spare capacity), not one
    a, b = Thread("enc", "0", 1e6, 0.0), Thread("enc", "1", 1e6, 0.0)
    slots, _ = eas_place([a, b], ctx, {})
    assert sorted(len(cpu) for cpu in slots["LITTLE"]) == [1, 1]


def test_cpuset_pin_prefer_idle_and_overutilized():
    m = _two()
    ctx = _ctx(m)
    th = Thread("ui", "ui", 1e6, 0.0)
    slots, _ = eas_place([th], ctx, {"ui": policy_from({"allowed": ["B"]})})        # core type works too
    assert any(slots["BIG"])
    big = Thread("x", "x", 80e6, 0.0)                                                  # > 1 frame anywhere
    _, over = eas_place([big], ctx, {})
    assert over == ["x"]
    busy = Thread("bg", "bg", 1e6, 0.0)
    slots, _ = eas_place([busy, Thread("cam", "cam", 0.5e6, 0.0)], ctx, {"cam": policy_from({"prefer_idle": True})})
    assert all(len(cpu) == 1 for cpu in slots["LITTLE"])


def test_schedutil_frequency_and_deadline_boost():
    m = _two()
    th = Thread("eis", "eis", ref_cycles=4e6, stall_ms=0.0)         # LITTLE: 16 ms @500, 8 ms @1000
    plain = _cluster_eval(_ctx(m, deadline_boost=False, budgets={"eis": 10}), "LITTLE", [[th], []], {})
    assert plain["mhz"] == 500.0 and plain["boosted_by"] == []      # 8 ms busy at fmax: low util_est
    fast_pelt = _cluster_eval(_ctx(m, deadline_boost=False, pelt_halflife_ms=8), "LITTLE", [[th], []], {})
    assert fast_pelt["mhz"] == 1000.0                                 # pelt multiplier raises the request
    boosted = _cluster_eval(_ctx(m, budgets={"eis": 10}), "LITTLE", [[th], []], {})
    assert boosted["mhz"] == 1000.0 and boosted["sched_mhz"] == 500.0 and boosted["boosted_by"] == ["eis"]
    clamped = _cluster_eval(_ctx(m, deadline_boost=False, pelt_halflife_ms=8), "LITTLE", [[th], []],
                            {"eis": policy_from({"uclamp_max": 64})})
    assert clamped["mhz"] == 500.0                                    # uclamp_max caps the request


def _profile() -> CpuProfile:
    return CpuProfile(
        tasks=[CpuTaskProfile(task="eis", cluster="BIG", cycles=6e6, stall_cycles=1e6, threads={"a": 4e6, "b": 2e6}),
               CpuTaskProfile(task="ui", cluster="LITTLE", cycles=1e6)],
        clusters={"BIG": CpuClusterProfile(cycles=6e6, freq_residency={1000.0: 1.0}),
                  "LITTLE": CpuClusterProfile(cycles=1e6, freq_residency={500.0: 1.0})},
    )


def test_sweep_reference_ranking_and_dedupe():
    m = _two()
    r = cpu_sweep(_profile(), target=m, fps=30, spec=SweepSpec(budgets_ms={"eis": 12}))
    assert r["reference_kind"] == "measured"
    assert r["measured_placement"]["placement"] == {"eis": ["BIG"], "ui": ["LITTLE"]}
    rng = r["range"]
    assert rng["method"] == "exhaustive" and rng["space"] == rng["evaluated"]
    eis = next(t for t in rng["tasks"] if t["task"] == "eis")
    assert eis["thread_source"] == "measured" and {t["name"] for t in eis["threads"]} == {"a", "b"}
    assert eis["measured"] == ["BIG"] and set(eis["cells"]) == {"LITTLE", "BIG"}
    totals = [c["total_mw"] for c in r["cases"]]
    assert totals == sorted(totals)
    assert all(c["feasible"] and c["delta_mw"] < 0 for c in r["cases"])
    signatures = {(tuple((t, tuple(v)) for t, v in sorted(c["placement"].items())),
                   tuple((n, x["mhz"], tuple(tuple(cpu["threads"]) for cpu in x["cpus"])) for n, x in c["clusters"].items()))
                  for c in r["cases"] + r["others"]}
    assert len(signatures) == len(r["cases"]) + len(r["others"])     # identical schedules merged
    for c in r["cases"]:
        assert all(abs(e["total_mw"] - c["total_mw"]) <= r["equal_mw"] for e in c["equivalents"])
        assert all(len(e["knobs"]) >= len(c["knobs"]) for e in c["equivalents"])   # simplest knob set shown
    assert "MID" not in str(r["calibration"]) and set(r["calibration"]) == {"LITTLE", "BIG"}
    eas = cpu_sweep(_profile(), target=m, fps=30, spec=SweepSpec(budgets_ms={"eis": 12}, reference="eas"))
    assert eas["reference"]["knobs"] == {}


def test_sweep_beam_when_space_is_large():
    m = _two()
    r = cpu_sweep(_profile(), target=m, fps=30, spec=SweepSpec(max_cases=2, uclamp_max_levels=(256, 512),
                                                               knobs=("pin", "upto", "uclamp_max")))
    assert r["range"]["method"] == "beam" and r["range"]["evaluated"] < r["range"]["space"] * 1 + 1
    assert any("beam search" in w for w in r["warnings"])
    assert r["range"]["evaluated"] <= 2


@pytest.mark.parametrize("field,value", [
    ("growth", {"ui": -1}), ("growth", {"ui": float("nan")}),
    ("budgets_ms", {"ui": 0}), ("threads", {"ui": -2}), ("threads", {"ui": 65}),
    ("uclamp_min_levels", [-1]), ("uclamp_max_levels", [1025]),
])
def test_sweep_rejects_invalid_task_controls(field, value):
    with pytest.raises(ValueError):
        CpuSweepRequest(power_params_ref="pmp-t", **{field: value})


def test_sweep_rejects_unknown_cluster_instead_of_allowing_all():
    with pytest.raises(ValueError, match="unknown target"):
        cpu_sweep(_profile(), target=_two(), fps=30, spec=SweepSpec(sweep_clusters={"ui": ["typo"]}))


def test_profile_rejects_negative_or_nonfinite_thread_cycles():
    for value in (-1, float("inf")):
        with pytest.raises(ValueError):
            CpuTaskProfile(task="ui", cluster="BIG", cycles=1e6, threads={"main": value})


def test_exynos2600_sample_import_threads_and_sweep():
    meta = yaml.safe_load((SAMPLE / "meta.yaml").read_text(encoding="utf-8"))
    warnings: list[str] = []
    rows = table_samples(SAMPLE, TableSpec.model_validate(meta["pmu"]["table"]), warnings)
    assert any(r["metric"] == "cpu_thread_cycles" for r in rows)
    digest = import_pmu_digest(SAMPLE, PmuSpec.model_validate(meta["pmu"]))
    profile = cpu_profile_from_observations(digest.observations)
    assert profile is not None
    eis = next(t for t in profile.tasks if t.task == "eis")
    assert eis.cluster == "MID_HF" and set(eis.threads or {}) == {"2067", "2068"}
    assert sum((eis.threads or {}).values()) == pytest.approx(eis.cycles)
    params = PowerModelParams.model_validate(yaml.safe_load(E2600.read_text(encoding="utf-8")))
    assert params.cpu.scheduler is not None and params.cpu.scheduler.model == "eas"
    model = CpuPowerModel.from_params(params)
    r = cpu_sweep(profile, target=model, fps=30, spec=SweepSpec(budgets_ms={"eis": 10, "post_irta": 12}))
    assert [c["name"] for c in r["range"]["clusters"]] == ["MID_LF0", "MID_LF1", "MID_HF", "BIG"]
    assert r["measured_mw"] and r["measured_placement"]["feasible"]
    assert r["better_count"] >= 1 and r["cases"][0]["total_mw"] < r["reference"]["total_mw"]
    hf = r["calibration"]["MID_HF"]
    assert hf["measured_mean_mhz"] > 0 and "eas_mhz" in hf


def test_scheduler_absent_keeps_dump_and_api_service():
    plain = _params(clusters=[{"name": "A", "opps": [{"mhz": 1000, "mv": 700, "mw_per_core": 50}]}])
    assert "scheduler" not in plain.model_dump()["cpu"]
    model = _two()

    class _Db:
        def get(self, _cls, _id):
            return None

    import scenario_db.api.services.cpu as svc

    orig = svc._model
    svc._model = lambda _db, _ref: model  # type: ignore[assignment]
    try:
        out = run_cpu_sweep(_Db(), CpuSweepRequest(cpu_profile=_profile(), power_params_ref="pmp-t",  # type: ignore[arg-type]
                                                   budgets_ms={"eis": 12}, threads={"ui": 2}))
    finally:
        svc._model = orig  # type: ignore[assignment]
    ui = next(t for t in out.result["range"]["tasks"] if t["task"] == "ui")
    assert ui["thread_source"] == "given" and len(ui["threads"]) == 2


def test_energy_memo_matches_cluster_eval_and_separates_uclamp():
    """The sweep memoises per-cluster energy; uclamp changes the schedutil request and must not alias."""
    m = _two()
    ctx = _ctx(m)
    a, b = Thread("eis", "a", ref_cycles=30e6, stall_ms=0.5), Thread("ui", "ui", ref_cycles=1e6, stall_ms=0.0)
    cpus = [[a], [b]]
    plain = {}
    capped = {"eis": policy_from({"uclamp_max": 128})}
    e_plain = ctx.energy("BIG", cpus, plain, {})
    e_capped = ctx.energy("BIG", cpus, capped, {"eis": (0.0, 128.0)})
    assert e_plain == _cluster_eval(_ctx(m), "BIG", cpus, plain)["energy_mw"]
    assert e_capped == _cluster_eval(_ctx(m), "BIG", cpus, capped)["energy_mw"]
    assert e_capped < e_plain                         # capped request -> lower OPP; a shared memo entry would hide it
    assert hash(Thread("eis", "a", 30e6, 0.5)) == hash(a) and Thread("eis", "a", 30e6, 0.5) == a


def test_sweep_with_many_threads_is_bounded(monkeypatch):
    """Bound search work and verify cache reuse independently of host speed or coverage overhead."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bench_cpu_sweep", ROOT / "scripts" / "bench_cpu_sweep.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    model = CpuPowerModel.from_params(PowerModelParams.model_validate(yaml.safe_load(E2600.read_text(encoding="utf-8"))))
    prof = bench.profile(21, 60, [c.name for c in model.clusters])
    requests = evaluations = 0
    direct_eval, cached_energy = _cluster_eval, _Ctx.energy

    def count_eval(*args, **kwargs):
        nonlocal evaluations
        evaluations += 1
        return direct_eval(*args, **kwargs)

    def count_energy(*args, **kwargs):
        nonlocal requests
        requests += 1
        return cached_energy(*args, **kwargs)

    monkeypatch.setattr(cpu_sched, "_cluster_eval", count_eval)
    monkeypatch.setattr(_Ctx, "energy", count_energy)
    r = cpu_sweep(prof, target=model, fps=30, spec=SweepSpec())
    assert 1000 < r["range"]["evaluated"] <= SweepSpec().max_cases
    assert evaluations < requests / 2  # catches removing the memo without a hardware-dependent timeout


@pytest.mark.parametrize("util_model", ["util_est", "pelt_avg"])
@pytest.mark.parametrize("max_cases", [12, 1000])
def test_sweep_memo_preserves_complete_results(monkeypatch, util_model, max_cases):
    """Compare cached sweeps with direct energy evaluation across policies and search modes."""
    model = _two()
    prof = CpuProfile(tasks=[
        CpuTaskProfile(task="eis", cluster="LITTLE", cycles=8e6, stall_cycles=1e6,
                       threads={"a": 5e6, "b": 3e6}),
        CpuTaskProfile(task="ui", cluster="BIG", cycles=2e6),
    ], clusters={"LITTLE": CpuClusterProfile(cycles=8e6), "BIG": CpuClusterProfile(cycles=2e6)})
    spec = SweepSpec(
        max_cases=max_cases, util_model=util_model, energy_includes_static=True,
        budgets_ms={"eis": 12.0}, growth={"eis": 1.2},
        task_policy={"ui": {"uclamp_min": 128, "prefer_idle": True}},
        knobs=("pin", "upto", "uclamp_min", "uclamp_max"),
        uclamp_min_levels=(256,), uclamp_max_levels=(128, 768),
    )
    cached = cpu_sweep(prof, target=model, fps=30, spec=spec)
    monkeypatch.setattr(_Ctx, "energy", lambda ctx, name, cpus, policies, clamped:
                        _cluster_eval(ctx, name, cpus, policies)["energy_mw"])
    assert cpu_sweep(prof, target=model, fps=30, spec=spec) == cached
