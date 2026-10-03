"""DSU <-> cluster clock coupling (vote table) in the CPU what-if sweep."""
from __future__ import annotations

import pathlib

import pytest
import yaml

from scenario_db.models.capability.power_model import CpuDsuVote, PowerModelParams
from scenario_db.sim import cpu_dsu
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_sched import SweepSpec, cpu_sweep
from scenario_db.sim.models import CpuClusterProfile, CpuDsuProfile, CpuProfile, CpuTaskProfile

ROOT = pathlib.Path(__file__).resolve().parents[3]
E2600 = ROOT / "examples" / "cpu-topology" / "pmp-exynos2600-cpu-example.yaml"
VOTE = {"MID_LF": [[1000, 400], [1600, 900], [2000, 1500]], "MID_HF": [[1200, 400], [2000, 900], [2600, 1500]],
        "BIG": [[2000, 900], [3600, 1500]]}


def _vote(cluster: str, mhz: float) -> float:
    pts = VOTE[cluster.rstrip("01")]                       # MID_LF0 / MID_LF1 -> core type MID_LF
    return next((d for f, d in pts if f >= mhz), pts[-1][1])


def _raw() -> dict:
    return yaml.safe_load(E2600.read_text(encoding="utf-8"))


def _model(vote=None, source="estimate") -> CpuPowerModel:
    raw = _raw()
    if vote is not None:
        raw["cpu"]["dsu"]["vote"] = [{"cluster": k, "points": v} for k, v in vote.items()]
        raw["cpu"]["dsu"]["vote_source"] = source
    return CpuPowerModel.from_params(PowerModelParams.model_validate(raw))


def _profile(dsu: dict[float, float] | None = None) -> CpuProfile:
    tasks = [CpuTaskProfile(task=f"cam{i}", cluster="MID_LF0", cycles=c * 1e6, stall_cycles=c * 1.5e5)
             for i, c in enumerate([17, 13, 11, 9, 9, 8, 7, 6, 5, 4])]
    return CpuProfile(tasks=tasks, clusters={"MID_LF0": CpuClusterProfile(cycles=sum(t.cycles for t in tasks))},
                      dsu=CpuDsuProfile(freq_residency=dsu) if dsu else None)


def test_vote_is_optional_and_keeps_existing_params_hash():
    raw = _raw()
    before = PowerModelParams.model_validate(raw).params_hash()
    assert PowerModelParams.model_validate(yaml.safe_load(E2600.read_text(encoding="utf-8"))).params_hash() == before
    assert "vote" not in PowerModelParams.model_validate(raw).model_dump(mode="json", exclude_none=True)["cpu"]["dsu"]


@pytest.mark.parametrize("points", [[[1600, 900], [1000, 400]], [[1000, 900], [1600, 400]], [[1000, 0]]])
def test_vote_table_validation(points):
    with pytest.raises(ValueError):
        CpuDsuVote(cluster="MID_LF", points=points)
    with pytest.raises(ValueError):
        cpu_dsu._table({"MID_LF": points})


def test_auto_mode_resolution():
    measured = {900.0: 1.0}
    assert cpu_dsu.resolve(_model(), measured=None).mode == "proportional"
    assert cpu_dsu.resolve(_model(), measured=measured).mode == "measured"
    p = cpu_dsu.resolve(_model(VOTE), measured=measured)
    assert (p.mode, p.source) == ("vote", "estimate")
    q = cpu_dsu.resolve(_model(VOTE), vote={"MID_LF": [[2000, 400]]})
    assert q.source == "request" and set(q.vote) == {"MID_LF"}
    with pytest.raises(ValueError):
        cpu_dsu.resolve(_model(), mode="vote")
    with pytest.raises(ValueError):
        cpu_dsu.resolve(_model(), mode="fixed")


def test_vote_uses_core_type_and_max_of_busy_clusters():
    m = _model(VOTE)
    p = cpu_dsu.resolve(m, mode="vote")
    fmax = {c.name: c.opps[-1].mhz for c in m.clusters}
    assert cpu_dsu.residency(p, m, {"MID_LF0": 1600.0}, fmax) == {900.0: 1.0}
    assert cpu_dsu.residency(p, m, {"MID_LF0": 1600.0, "MID_HF": 2600.0}, fmax) == {1500.0: 1.0}
    assert cpu_dsu.residency(p, m, {"MID_LF0": 400.0}, fmax) == {400.0: 1.0}
    assert cpu_dsu.residency(p, m, {}, fmax) == {400.0: 1.0}          # nothing busy -> lowest DSU OPP


def test_sweep_dsu_follows_placement_with_vote_but_not_with_measured_residency():
    prof = _profile(dsu={1500.0: 1.0})
    legacy = cpu_sweep(prof, target=_model(), fps=30.0, spec=SweepSpec(sweep_clusters={}, max_cases=400))
    assert legacy["dsu_model"]["mode"] == "measured"
    assert {c["dsu"]["mhz"] for c in [legacy["reference"], *legacy["cases"]]} == {1500.0}
    voted = cpu_sweep(prof, target=_model(VOTE), fps=30.0, spec=SweepSpec(sweep_clusters={}, max_cases=400))
    assert voted["dsu_model"]["mode"] == "vote" and voted["dsu_model"]["source"] == "estimate"
    mhz = {c["dsu"]["mhz"] for c in [voted["reference"], *voted["cases"], *voted["others"]]}
    assert len(mhz) > 1                                              # the DSU now moves with the placement
    for case in [voted["reference"], *voted["cases"]]:
        busy = {n: r["mhz"] for n, r in case["clusters"].items() if r["busy_ms"] > 0}
        assert case["dsu"]["mhz"] == max(_vote(n, f) for n, f in busy.items())
    assert voted["dsu_check"]["measured_mean_mhz"] == 1500.0
    assert voted["dsu_params"]["opps"][0]["mhz"] == 400.0
    assert all("opps_mhz" in c for c in voted["range"]["clusters"])


def test_request_vote_override_and_fixed_mode_change_only_dsu_power():
    prof = _profile()
    base = cpu_sweep(prof, target=_model(VOTE), fps=30.0, spec=SweepSpec(max_cases=200))
    low = cpu_sweep(prof, target=_model(VOTE), fps=30.0, spec=SweepSpec(max_cases=200, dsu_mode="fixed", dsu_fixed_mhz=400))
    ref_b, ref_l = base["reference"], low["reference"]
    assert ref_l["dsu"]["mhz"] == 400.0
    assert {n: r["mhz"] for n, r in ref_b["clusters"].items()} == {n: r["mhz"] for n, r in ref_l["clusters"].items()}
    assert ref_l["total_mw"] - ref_l["dsu"]["total_mw"] == pytest.approx(ref_b["total_mw"] - ref_b["dsu"]["total_mw"], abs=1e-3)
    over = cpu_sweep(prof, target=_model(VOTE), fps=30.0, spec=SweepSpec(max_cases=200, dsu_vote={"MID_LF": [[2000, 400]]}))
    assert over["dsu_model"]["source"] == "request" and over["reference"]["dsu"]["mhz"] == 400.0


def test_api_request_carries_dsu_rule(monkeypatch):
    from scenario_db.api.schemas.cpu import CpuSweepRequest
    import scenario_db.api.services.cpu as svc

    monkeypatch.setattr(svc, "_model", lambda _db, _ref: _model())
    req = CpuSweepRequest(cpu_profile=_profile(), power_params_ref="pmp-t", dsu_mode="vote",  # type: ignore[arg-type]
                          dsu_vote={"MID_LF": [[2000, 900]]}, max_cases=100)
    out = svc.run_cpu_sweep(object(), req)  # type: ignore[arg-type]
    assert out.result["dsu_model"] == {"mode": "vote", "requested": "vote", "source": "request", "vote": {"MID_LF": [[2000.0, 900.0]]}}
    assert out.result["reference"]["dsu"]["mhz"] == 900.0
    with pytest.raises(ValueError):
        CpuSweepRequest(power_params_ref="p", dsu_mode="nope")  # type: ignore[arg-type]
    with pytest.raises(svc.UnprocessableError):
        svc.run_cpu_sweep(object(), CpuSweepRequest(cpu_profile=_profile(), power_params_ref="p", dsu_mode="vote"))  # type: ignore[arg-type]
