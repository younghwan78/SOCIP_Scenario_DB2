"""CPU what-if / exploration extensions: MID concentrate-vs-spread strategies + BIG check, profile-based
CPU term for the timing budget (C1/C2), PMU 3-pass counter merge (E6), GPU power from residency (E7)."""
from __future__ import annotations

import pathlib

import pytest
import yaml

from scenario_db.meas_import import pmu_passes
from scenario_db.meas_import.meta import PmuSpec
from scenario_db.meas_import.pmu_digest import PmuSample, build_pmu_digest, import_pmu_digest
from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.sim.cpu_power import CpuPowerModel, profile_cpu_power
from scenario_db.sim.cpu_profile import cpu_profile_from_evidence
from scenario_db.sim.cpu_rebalance import RebalanceSpec, cpu_rebalance
from scenario_db.sim.cpu_scenario import apply_profile_cpu, profile_cpu_terms
from scenario_db.sim.domain_power import DomainPowerModel, measured_rail_mw, models_from_ip_catalog

ROOT = pathlib.Path(__file__).resolve().parents[3]
DB = ROOT / "db_Exynos2600_SM-S947B"
EXAMPLE = ROOT / "examples" / "measurement-import" / "clock-residency-e2600"


@pytest.fixture(scope="module")
def model() -> CpuPowerModel:
    return CpuPowerModel.from_params(PowerModelParams.model_validate(yaml.safe_load((DB / "00_hw" / "pmp-exynos2600-v2.yaml").read_text(encoding="utf-8"))))


def _profile(variant: str):
    ev = yaml.safe_load((DB / "03_evidence" / f"meas-synth-baseline-cam-rec-{variant}-evt1-20261004.yaml").read_text(encoding="utf-8"))
    return cpu_profile_from_evidence(ev, evidence_ref=ev["id"])


# ------------------------------------------------------------------ MID concentrate vs spread
def test_strategies_cover_every_pool_combination(model):
    r = cpu_rebalance(_profile("f1-uhd60"), target=model, fps=60, spec=RebalanceSpec())
    s = r["strategies"]
    pats = {"+".join(row["clusters"]) for row in s["rows"]}
    assert {"MID_LF0", "MID_LF1", "MID_HF", "MID_LF0+MID_LF1", "MID_LF0+MID_HF", "MID_LF1+MID_HF",
            "MID_LF0+MID_LF1+MID_HF"} <= pats                      # local search still fills every subset
    assert all(row["kind"] == ("concentrate" if row["ways"] == 1 else "spread") for row in s["rows"])
    assert s["winner"] == "spread" and s["spread_gain_mw"] > 0
    assert s["best_spread"]["total_mw"] < s["best_concentrate"]["total_mw"]
    big = s["big_check"]
    assert big["clusters"] == ["BIG"] and not big["gain"]           # BIG never pays off for camera SW here
    assert big["best"]["delta_mw"] > 0 and big["moves"] and big["base_mw"] == pytest.approx(s["best_spread"]["total_mw"], rel=0.02)
    assert "BIG" not in r["pool"]


def test_symmetric_concentrate_is_reported_once(model):
    r = cpu_rebalance(_profile("r1-uhd30-vdis"), target=model, fps=30, spec=RebalanceSpec())
    conc = [row for row in r["strategies"]["rows"] if row["kind"] == "concentrate"]
    assert ["MID_LF0", "MID_LF1"] in r["symmetric"]
    assert sum(1 for row in conc if row["clusters"][0] in ("MID_LF0", "MID_LF1")) == 1


def test_big_in_pool_disables_big_check(model):
    r = cpu_rebalance(_profile("r1-uhd30-vdis"), target=model, fps=30,
                      spec=RebalanceSpec(pool=("MID_LF0", "MID_HF", "BIG"), max_exhaustive=20_000))
    assert r["strategies"]["big_check"] is None


# ------------------------------------------------------------------ C1 / C2 profile CPU term
def test_profile_terms_grow_nonlinearly(model):
    prof = _profile("f1-uhd60")
    a = profile_cpu_terms(prof, model=model, fps=60, growth=1.0)
    b = profile_cpu_terms(prof, model=model, fps=60, growth=1.5)
    ref = profile_cpu_power(prof, model=model, period_ms=1000 / 60)
    assert a["total_mw"] > 0 and b["total_mw"] > a["total_mw"]
    assert b["cpu_bw_mbs"] == pytest.approx(1.5 * a["cpu_bw_mbs"], rel=1e-6)
    assert sum(a["by_task"].values()) == pytest.approx(a["total_mw"], rel=1e-3)
    assert set(a["clusters"]) == set(ref["clusters"])
    assert a["total_mw"] == pytest.approx(cpu_rebalance(prof, target=model, fps=60, spec=RebalanceSpec())["reference"]["total_mw"], rel=1e-3)


def test_apply_profile_cpu_rewrites_report(model):
    report = {"fps": 60.0,
              "power": {"total_mw": 500.0, "cpu_mw": 90.0, "hw_mw": 300.0, "bw_mw": 110.0, "bw_hw_mw": 100.0, "bw_sw_mw": 10.0,
                        "cpu_by_task": {"eis": 90.0}, "share_pct": {}},
              "bw": {"total_mbs": 1100.0, "hw_mbs": 1000.0, "sw_mbs": 100.0, "sw_by_task": {"cpu.eis": 100.0}}}
    out = apply_profile_cpu(report, profile=_profile("f1-uhd60"), model=model, growth=1.0)
    p, b = out["power"], out["bw"]
    assert p["cpu_mw_flat"] == 90.0 and p["cpu_profile"]["kind"] == "profile"
    assert p["total_mw"] == pytest.approx(p["cpu_mw"] + p["hw_mw"] + p["bw_mw"], abs=0.02)
    assert b["sw_mbs_model"] == 100.0 and b["cpu_bw_source"] == "measured"
    assert list(b["sw_by_task"]) == ["cpu.eis"]                     # modelled SW DMA nodes kept, scaled
    assert p["bw_sw_mw"] == pytest.approx(b["sw_mbs"] * 0.1, rel=1e-3)   # model mW per MB/s of the CPU traffic


# ------------------------------------------------------------------ E6 PMU passes
def test_pass_merge_uses_anchors_and_ratios():
    s = []
    for g, c, i, st in (("p1", 1000.0, 800.0, 300.0), ("p2", 1100.0, 820.0, None), ("p3", 1050.0, 790.0, None)):
        s += [PmuSample("cpu_cycles", "task_cluster", "eis@MID_LF0", c, group=g),
              PmuSample("cpu_instructions", "task_cluster", "eis@MID_LF0", i, group=g)]
        if st:
            s.append(PmuSample("cpu_stall_cycles", "task_cluster", "eis@MID_LF0", st, group=g))
    d = build_pmu_digest(s, frames=10)
    by = {(o["metric_id"], o["scope"]["ref"]): o["value"] for o in d.observations}
    assert by[("cpu.cycles_pf", "eis@MID_LF0")] == pytest.approx(105.0)
    assert by[("cpu.instructions_pf", "eis@MID_LF0")] == pytest.approx(80.333, abs=1e-3)
    assert by[("cpu.stall_cycles_pf", "eis@MID_LF0")] == pytest.approx(300 / 800 * 803.333 / 10, rel=1e-4)
    assert by[("cpu.pass_cv", "eis")] == pytest.approx(0.047619, abs=1e-5) and ("cpu.pass_cv", "all") in by
    assert not d.warnings


def test_pass_merge_warns_on_missing_anchor_and_single_group():
    merged, obs, warns = pmu_passes.merge_counter_groups(
        [PmuSample("cpu_cycles", "cluster", "MID_LF0", 10.0, group="p1"), PmuSample("cpu_stall_cycles", "cluster", "MID_LF0", 2.0, group="p2")],
        lambda m, k, r, v, line: PmuSample(m, k, r, v, line=line))
    assert any("anchor" in w for w in warns)
    _, _, one = pmu_passes.merge_counter_groups([PmuSample("cpu_cycles", "cluster", "X", 1.0, group="p1")],
                                                 lambda m, k, r, v, line: PmuSample(m, k, r, v, line=line))
    assert any("one group" in w for w in one)


def test_example_counters_flag_the_drifting_pass():
    meta = yaml.safe_load((EXAMPLE / "cam-rec-r1-8k30-psm" / "meta.yaml").read_text(encoding="utf-8"))
    d = import_pmu_digest(EXAMPLE / "cam-rec-r1-8k30-psm", PmuSpec.model_validate(meta["pmu"]))
    cv = {o["scope"]["ref"]: o["value"] for o in d.observations if o["metric_id"] == "cpu.pass_cv"}
    assert cv["post_irta"] > pmu_passes.PASS_CV_WARN > cv["post_crta"]
    assert any("post_irta" in w for w in d.warnings)
    calm = yaml.safe_load((EXAMPLE / "cam-rec-r1-uhd30-vdis" / "meta.yaml").read_text(encoding="utf-8"))
    d2 = import_pmu_digest(EXAMPLE / "cam-rec-r1-uhd30-vdis", PmuSpec.model_validate(calm["pmu"]))
    assert not any("disagree" in w for w in d2.warnings)


def test_running_residency_profile_power_differs_from_wall(model):
    ev = yaml.safe_load((DB / "03_evidence" / "meas-synthetic-clock-residency-r1-8k30-psm-e2600-evt1.yaml").read_text(encoding="utf-8"))
    prof = cpu_profile_from_evidence(ev, evidence_ref=ev["id"])
    assert prof.clusters["MID_LF0"].freq_residency_active
    pw = profile_cpu_power(prof, model=model, period_ms=1000 / 30)
    assert pw["clusters"]["MID_LF0"]["residency_basis"] == "active"


# ------------------------------------------------------------------ E7 GPU power
def test_gpu_power_from_ip_catalog_and_rails():
    ip = yaml.safe_load((DB / "00_hw" / "ip-gpu-s5e9965.yaml").read_text(encoding="utf-8"))
    models = models_from_ip_catalog([ip], "soc-exynos2600", {"GPU": "gpu"})
    m = models["GPU"]
    assert m.sample and m.coeff_source == "profiler_dynamic_coeff" and m.mv(300) == 637.0 and m.mv(2000) == 812.0
    est = m.estimate([{"mhz": 300.0, "ratio": 1.0}], [{"mhz": 300.0, "ratio": 1.0}], 0.25, 0.5)
    assert est["dynamic_mw"] == pytest.approx(0.25 * m.dyn_mw(300.0), rel=1e-3)
    assert est["static_mw"] == pytest.approx(0.5 * m.leak_mw(300.0), rel=1e-2)
    assert any("SAMPLE" in n for n in est["notes"])
    no_ratio = m.estimate([{"mhz": 300.0, "ratio": 1.0}], None, None, None)
    assert any("100%" in n for n in no_ratio["notes"])
    assert models_from_ip_catalog([ip], "soc-other", {"GPU": "gpu"}) == {}
    assert DomainPowerModel.from_ip("GPU", "x", {"power_model": {"profiler_dynamic_coeff": 1.0}}) is None   # no V-f
    mw, rails = measured_rail_mw({"VDD_G3D0": {"power_mw": 3.0}, "VDD_G3D1": {"power_mw": 1.5}, "VDD_MIF": {"power_mw": 9.0}}, "gpu")
    assert mw == 4.5 and rails == ["VDD_G3D0", "VDD_G3D1"]


# ------------------------------------------------------------------ Timing Budget coupling (stretch budgets)
def test_stretch_budgets_keep_the_measured_placement_feasible_and_bound_the_tasks(model):
    free = cpu_rebalance(_profile("r1-8k30-psm"), target=model, fps=30, spec=RebalanceSpec())
    nrt = ("post_crta", "pre_me_rta", "post_irta")
    # unconstrained: dropping MID_LF0 one OPP slows the NRT tasks left on it (latency, not fps)
    assert free["best"]["delta_mw"] < -10
    assert any(free["best"]["task_ms"][t] > free["reference"]["task_ms"][t] * 1.05 for t in nrt)
    # stretch 1.0 = the NRT stage has no SW slack left: no NRT task may get slower than measured
    tight = cpu_rebalance(_profile("r1-8k30-psm"), target=model, fps=30,
                          spec=RebalanceSpec(stretch_budgets={t: 1.0 for t in nrt}))
    assert tight["curve"][0]["feasible"] and tight["reference"]["feasible"]
    assert tight["best"]["total_mw"] <= tight["reference"]["total_mw"] + 1e-6
    assert all(tight["best"]["task_ms"][t] <= tight["budgets_ms"][t] for t in nrt)
    assert {tight["budget_source"][t] for t in nrt} == {"stretch"}
    assert {u["budget_source"] for u in tight["units"] if u["unit"] in nrt} <= {"stretch"}


def test_explain_names_the_cluster_whose_opp_drops(model):
    r = cpu_rebalance(_profile("r1-uhd30-vdis"), target=model, fps=30, spec=RebalanceSpec())
    why = r["why"]
    assert why["delta_mw"] == pytest.approx(r["best"]["delta_mw"], abs=0.01)
    assert why["driver"]["cluster"] == "MID_LF0" and why["driver"]["mhz"][1] < why["driver"]["mhz"][0]
    assert why["driver"]["delta_util_needed"] is not None
    assert {m["unit"] for m in why["moves"]} == set(r["best"]["moved"])
    assert why["stretched"] and all(s["stretch"] > 1.2 for s in why["stretched"])
