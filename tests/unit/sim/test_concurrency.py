"""S-06 concurrent scenarios: static composition of the members' own reports."""

from types import SimpleNamespace

import pytest

from scenario_db.db.models.definition import Project
from scenario_db.sim.concurrency import compose
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph


def _report(scenario, variant):
    g = _exynos2600_generated_graph(scenario, variant)
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    return analyze_timing_budget(g, TimingBudgetOptions())


def _synthetic(label, mhz, mv, mw, period=16.667, busy=4.0, verdict="ok", node="mfc"):
    return (label, {
        "scenario_id": label, "variant_id": "v", "period_ms": period, "fps": 1000 / period, "verdict": {"status": verdict},
        "ips": [{"node": node, "dvfs_group": "MFC", "set_clock_mhz": mhz, "voltage_mv": mv, "power_mw": mw}],
        "power": {"total_mw": mw + 50, "cpu_mw": 40.0, "hw_mw": mw, "bw_mw": 10.0, "cpu_busy_ms": busy,
                  "hw_by_ip": {node: mw}},
        "bw": {"total_mbs": 100.0},
        "dvfs": {"ladders": {"MFC": [{"level": 0, "mhz": 200, "mv": 600}, {"level": 1, "mhz": 400, "mv": 700},
                                     {"level": 2, "mhz": 600, "mv": 800}]}},
    })


def test_a_shared_dvfs_domain_runs_at_the_highest_clock_and_reprices_the_slower_member():
    c = compose([_synthetic("dec", 200, 600, 36.0, node="mfc_dec"), _synthetic("enc", 600, 800, 100.0, node="mfc_enc")])
    dom = c["shared_domains"][0]
    assert (dom["group"], dom["clock_mhz"], dom["mv"]) == ("MFC", 600.0, 800.0)
    assert dom["raised"] == [{"member": "dec", "node": "mfc_dec", "own_mhz": 200.0, "own_mv": 600.0,
                              "delta_mw": pytest.approx(36.0 * ((800 / 600) ** 2 - 1), abs=1e-3)}]
    assert c["power"]["total_mw"] == pytest.approx(c["power"]["sum_of_members_mw"] + dom["delta_mw"], abs=0.01)
    assert c["members"][0]["dvfs_raise_mw"] == pytest.approx(dom["delta_mw"], abs=1e-3)


def test_cpu_load_adds_up_and_a_failing_member_fails_the_set():
    c = compose([_synthetic("a", 200, 600, 10, busy=10.0), _synthetic("b", 200, 600, 10, busy=8.0, verdict="fail", node="x")])
    assert c["cpu"]["load_core_eq"] == pytest.approx(18.0 / 16.667, rel=1e-3)
    assert c["verdict"]["status"] == "fail" and c["verdict"]["failing_members"] == ["b"]
    assert any("CPU 부하 합" in n for n in c["verdict"]["notes"])
    with pytest.raises(ValueError, match="two members"):
        compose([_synthetic("a", 200, 600, 10)])


def test_youtube_with_a_voice_call_shares_the_abox_and_adds_the_power():
    yt = _report("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr")
    call = _report("uc-call-voice-e2600", "voice-call-volte")
    c = compose([("yt", yt), ("call", call)])
    assert c["power"]["sum_of_members_mw"] == pytest.approx(yt["power"]["total_mw"] + call["power"]["total_mw"], abs=0.02)
    assert c["bw"]["total_mbs"] == pytest.approx(yt["bw"]["total_mbs"] + call["bw"]["total_mbs"], abs=0.2)
    shared = {s["node"]: s for s in c["shared_nodes"]}
    assert "abox" in shared and set(shared["abox"]["members"]) == {"yt", "call"}
    assert shared["abox"]["mw"] == pytest.approx(yt["power"]["hw_by_ip"]["abox"] + call["power"]["hw_by_ip"]["abox"], abs=1e-3)
    assert len(c["limits"]) == 3


def test_the_service_composes_each_members_own_report(monkeypatch):
    from scenario_db.api.schemas.timing_budget import TimingBudgetConcurrentRequest
    from scenario_db.api.services import timing_budget as svc
    from scenario_db.exceptions import UnprocessableError

    seen = []

    def fake(db, req):
        seen.append((req.scenario_id, req.variant_id, req.options.include_whatif))
        label, rep = _synthetic(req.variant_id, 200 if req.variant_id == "a" else 400, 600 if req.variant_id == "a" else 700, 20)
        rep["dvfs"]["table_ref"] = "dvfs-x"
        return SimpleNamespace(report=rep)

    monkeypatch.setattr(svc, "analyze_timing_budget_request", fake)
    req = TimingBudgetConcurrentRequest(members=[{"scenario_id": "s1", "variant_id": "a"}, {"scenario_id": "s2", "variant_id": "b"}])
    out = svc.analyze_concurrent_request(None, req)
    assert seen == [("s1", "a", False), ("s2", "b", False)]
    assert out["dvfs_table_refs"] == ["dvfs-x"] and out["shared_domains"][0]["clock_mhz"] == 400.0
    dup = TimingBudgetConcurrentRequest(members=[{"scenario_id": "s1", "variant_id": "a"}] * 2)
    with pytest.raises(UnprocessableError, match="twice"):
        svc.analyze_concurrent_request(None, dup)
