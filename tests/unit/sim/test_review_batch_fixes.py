"""Fixes from the batched review of #105-#124: condition hash, event SW runtime, concurrent-set scope."""

from types import SimpleNamespace

import pytest

from scenario_db.db.models.definition import Project
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph


def _graph(scenario, variant):
    g = _exynos2600_generated_graph(scenario, variant)
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    return g


@pytest.fixture
def same_sim(monkeypatch):
    from scenario_db.api.services import timing_budget as svc

    monkeypatch.setattr(svc, "_request_hash", lambda *a, **k: "same-simulation-inputs")
    return svc


def test_the_condition_hash_follows_the_domain_load_declaration(same_sim):
    shim = SimpleNamespace(config=None)
    g = _graph("uc-game-play-e2600", "game-fhd-60fps-sdr")
    base = same_sim._condition_hash(g, TimingBudgetOptions(), shim, {})
    g.variant.node_configs["gpu"]["sim"]["domain_load"] = {"mcycles_per_frame": 8.0}
    assert same_sim._condition_hash(g, TimingBudgetOptions(), shim, {}) != base
    # a catalog coefficient the model reads moves it too
    g2 = _graph("uc-game-play-e2600", "game-fhd-60fps-sdr")
    ip = g2.ip_catalog["ip-gpu-s5e9965"]
    ip.capabilities = {**ip.capabilities, "power_model": {**ip.capabilities["power_model"], "profiler_dynamic_coeff": 9000}}
    assert same_sim._condition_hash(g2, TimingBudgetOptions(), shim, {}) != base


def test_the_condition_hash_follows_the_cpu_opp_and_is_unchanged_without_it(same_sim):
    shim = SimpleNamespace(config=None)
    g = _graph("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr")
    base = same_sim._condition_hash(g, TimingBudgetOptions(), shim, {})
    assert same_sim._cpu_opp_inputs(g) == {}
    g.variant.design_conditions["cpu_opp_mhz"] = 1000
    at_1000 = same_sim._condition_hash(g, TimingBudgetOptions(), shim, {})
    g.variant.design_conditions["cpu_mem_bound"] = 0.5
    assert len({base, at_1000, same_sim._condition_hash(g, TimingBudgetOptions(), shim, {})}) == 3


def test_an_event_sw_task_keeps_its_runtime_and_has_no_steady_cpu_share():
    g = _graph("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr")
    g.variant.node_configs["exo_loop"]["timeline"] = {"cadence": "event", "phase_ms": 2.0, "deadline_ms": 5.0}
    r = analyze_timing_budget(g, TimingBudgetOptions())
    row = next(x for x in r["own_cadence"] if x["node"] == "exo_loop")
    declared = float(g.variant.node_configs["exo_loop"]["sw_timing"]["max_ms"])
    # judged on its declared runtime (it ran ~1e-6 ms before the fix)
    assert (row["cadence"], row["releases"]) == ("event", 1)
    assert row["worst_response_ms"] == pytest.approx(declared, abs=1e-3)
    assert "exo_loop" not in r["power"]["cpu_by_task"]  # an event has no rate


def test_concurrent_members_must_share_one_project(monkeypatch):
    from scenario_db.api.schemas.timing_budget import TimingBudgetConcurrentRequest
    from scenario_db.api.services import timing_budget as svc
    from scenario_db.exceptions import UnprocessableError

    scenarios = {"a": SimpleNamespace(project_ref="proj-sm-s947b"), "b": SimpleNamespace(project_ref="proj-sm-s957b")}
    db = SimpleNamespace(get=lambda model, sid: scenarios.get(sid))
    req = TimingBudgetConcurrentRequest(members=[{"scenario_id": "a", "variant_id": "v"}, {"scenario_id": "b", "variant_id": "v"}])
    monkeypatch.setattr(svc, "analyze_timing_budget_request", lambda *a, **k: pytest.fail("must refuse before computing"))
    with pytest.raises(UnprocessableError, match="one project"):
        svc.analyze_concurrent_request(db, req)
