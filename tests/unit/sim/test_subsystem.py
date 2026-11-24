"""R-4 / M-4: IP subsystem declaration and the mcps-v1 evaluator on the E2600 MP3 playback graph."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from scenario_db.models.definition.subsystem import SubsystemSpec
from scenario_db.models.definition.usecase import Pipeline
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

UC = "uc-aud-mp3-playback-e2600"
CPU_ON, OFFLOAD = "audio-mp3-screen-on", "audio-mp3-screen-off-offload"
CA32 = {"coeff_uw_per_mhz_v2": 60, "vf": [{"mhz": 200, "mv": 600}, {"mhz": 1500, "mv": 850}],
        "leakage": {"mw_at_ref": 1.5, "ref_mv": 750}}
SUB = {
    "units": [{"id": "ca32_0", "kind": "cpu", "clock_domain": "AUD", "power": CA32},
              {"id": "ca32_1", "kind": "cpu", "clock_domain": "AUD", "power": CA32},
              {"id": "hifi5", "kind": "dsp", "clock_domain": "AUD", "power": {**CA32, "coeff_uw_per_mhz_v2": 90}},
              {"id": "dma", "kind": "hw", "power": {"mw": 1.0}}, {"id": "uaif0", "kind": "interface"}],
    "streams": [{"id": "pb_main", "fs_hz": 48000, "channels": 2, "bits": 16, "period_frames": 960},
                {"id": "pb_out", "fs_hz": 48000, "channels": 2, "bits": 32, "period_frames": 240, "buffer": "sram"}],
    "stages": [{"id": "rdma", "kind": "dma", "on": "dma", "stream": "pb_main"},
               {"id": "decode", "kind": "codec", "on": "hifi5", "stream": "pb_main", "mcps": 18,
                "when": {"offload": True}},
               {"id": "mix", "kind": "mixer", "on": "ca32_0", "stream": "pb_out", "mcps": 6},
               {"id": "eq", "kind": "effect", "on": "hifi5", "stream": "pb_out", "mcps": 25},
               {"id": "spk", "kind": "solution", "on": "ca32_1", "stream": "pb_out", "mcps": 12, "bind": "speaker"},
               {"id": "out", "kind": "interface", "on": "uaif0", "stream": "pb_out", "bind": "speaker"}],
    "edges": [["rdma", "decode"], ["decode", "mix"], ["rdma", "mix"], ["mix", "eq"], ["eq", "spk"], ["spk", "out"]],
    "routes": [{"id": "pb_cpu", "kind": "playback", "when": {"offload": False},
                "stages": ["rdma", "mix", "eq", "spk", "out"], "latency_target_ms": 60},
               {"id": "pb_off", "kind": "playback", "when": {"offload": True},
                "stages": ["rdma", "decode", "mix", "eq", "spk", "out"]}],
    "wake": [{"kind": "period_irq", "stream": "pb_main", "when": {"offload": False}},
             {"kind": "refill", "every_ms": 2000, "mb": 0.4, "when": {"offload": True}}],
}
OPTS = TimingBudgetOptions(throughput_model="pipelined")


def _graph(variant=CPU_ON, sub=None, patch=None):
    graph = _exynos2600_generated_graph(UC, variant)
    for node in graph.scenario.pipeline["nodes"]:
        if node["id"] == "abox":
            node["subsystem"] = deepcopy(sub or SUB)
    if patch is not None:
        cfgs = dict(graph.variant.node_configs or {})
        abox = dict(cfgs.get("abox") or {})
        abox["sim"] = {**(abox.get("sim") or {}), "subsystem": patch}
        cfgs["abox"] = abox
        graph.variant.node_configs = cfgs
    return graph


def _sub(graph):
    return analyze_timing_budget(graph, OPTS)["subsystems"]["abox"]


# ---------------------------------------------------------------------------- schema

@pytest.mark.parametrize("mutate,message", [
    (lambda s: s["units"].append(deepcopy(s["units"][0])), "duplicate unit ids"),
    (lambda s: s["stages"][2].update(on="ghost"), "unit 'ghost' not found"),
    (lambda s: s["stages"][2].update(stream="ghost"), "stream 'ghost' not found"),
    (lambda s: s["stages"][0].update(mcps=3), "a load needs a cpu / dsp unit"),
    (lambda s: s["stages"][2].update(mcycles_per_period=1), "mcps or mcycles_per_period, not both"),
    (lambda s: s["routes"][0]["stages"].insert(1, "eq"), "are not edges"),
    (lambda s: s["routes"][0]["stages"].append("ghost"), "unknown stages"),
    (lambda s: s["edges"].append(["mix", "ghost"]), "needs two known stage ids"),
    (lambda s: s["wake"].append({"kind": "refill"}), "refill needs every_ms"),
    (lambda s: s["units"][3].update(power={"coeff_uw_per_mhz_v2": 1, "vf": []}), "takes power {mw"),
    (lambda s: s["units"][0].update(power={"mw": 3}), "takes util-vf-v1 power"),
    (lambda s: s["streams"][0].update(period_frames=0), "greater than 0"),
])
def test_subsystem_structure_errors(mutate, message):
    sub = deepcopy(SUB)
    mutate(sub)
    with pytest.raises(ValidationError, match=message):
        SubsystemSpec.model_validate(sub)


def test_a_bind_must_name_a_pipeline_node():
    nodes = [{"id": "abox", "ip_ref": "ip-abox", "subsystem": deepcopy(SUB)}]
    with pytest.raises(ValidationError, match=r"bind to unknown nodes \['speaker'\]"):
        Pipeline.model_validate({"nodes": nodes})
    Pipeline.model_validate({"nodes": nodes + [{"id": "speaker", "ip_ref": "ip-abox"}]})


def test_an_undeclared_node_dumps_no_subsystem():
    assert "subsystem" not in Pipeline.model_validate({"nodes": [{"id": "a", "ip_ref": "ip-x"}]}).model_dump(
        exclude_none=True)["nodes"][0]


# ---------------------------------------------------------------------------- evaluator

def test_without_a_subsystem_the_report_is_unchanged():
    plain = analyze_timing_budget(_exynos2600_generated_graph(UC, CPU_ON), OPTS)
    assert "subsystems" not in plain
    assert plain["power"]["domain_loads"]["abox"]["model"] == "util-vf-v1"


def test_the_subsystem_replaces_the_domain_load():
    report = analyze_timing_budget(_graph(), OPTS)
    entry = report["power"]["domain_loads"]["abox"]
    sub = report["subsystems"]["abox"]
    assert entry["model"] == "mcps-v1" and entry["mw"] == pytest.approx(sub["mw"])
    assert "subsystem" not in entry                               # detail lives in report.subsystems
    assert sub["mw"] == pytest.approx(sum(u["mw"] for u in sub["units"] if "mw" in u))
    assert sub["unattributed_units"] == ["uaif0"]


def test_unit_load_clock_and_slack():
    sub = _sub(_graph())
    units = {u["id"]: u for u in sub["units"]}
    assert units["hifi5"]["load_mcps"] == pytest.approx(25.0)          # decode is offload-only
    assert units["ca32_1"]["load_mcps"] == pytest.approx(12.0)
    # ABOX catalog AUD levels (aud_qos_levels_khz): the lowest keeps hifi5 at 25 / 200 = 0.125 <= 0.85
    assert sub["domains"]["AUD"]["freq_mhz"] == pytest.approx(200.0)
    slack = {r["stream"]: r for r in sub["deadline_slack"]}
    assert slack["pb_out"]["slack_ms"] == pytest.approx(5.0 * (1 - 25 / 200))


def test_route_latency_and_wake_follow_the_variant():
    cpu, off = _sub(_graph(CPU_ON)), _sub(_graph(OFFLOAD))
    assert cpu["route"]["id"] == "pb_cpu" and off["route"]["id"] == "pb_off"
    # buffering 20 ms x 2 + 5 ms x 2, plus the stage work per period
    assert cpu["route"]["buffering_ms"] == pytest.approx(50.0)
    assert cpu["route"]["latency_ms"] == pytest.approx(50.0 + (6 + 25 + 12) * 5.0 / 200)
    assert cpu["route"]["latency_ok"] is True
    assert cpu["wake"]["per_s"] == pytest.approx(50.0) and off["wake"]["per_s"] == pytest.approx(0.5)
    assert {s["id"] for s in off["stages"]} >= {"decode"}


def test_a_higher_load_raises_the_domain_clock_and_power():
    heavy = deepcopy(SUB)
    heavy["stages"][3]["mcps"] = 400                                   # eq on hifi5: 400 / 0.85 -> > 400 MHz
    base, hot = _sub(_graph()), _sub(_graph(sub=heavy))
    assert hot["domains"]["AUD"]["freq_mhz"] > base["domains"]["AUD"]["freq_mhz"]
    assert hot["mw"] > base["mw"]
    assert all(u["freq_mhz"] == hot["domains"]["AUD"]["freq_mhz"] for u in hot["units"] if "freq_mhz" in u)


def test_an_overload_fails_the_verdict():
    over = deepcopy(SUB)
    over["stages"][3]["mcps"] = 5000
    report = analyze_timing_budget(_graph(sub=over), OPTS)
    assert report["power"]["domain_loads"]["abox"]["feasible"] is False
    assert report["verdict"]["status"] == "fail"


def test_a_variant_patches_the_subsystem_by_id():
    sub = _sub(_graph(patch={"$items": {"stages": {"patch": {"eq": {"mcps": 50}}}}}))
    assert {u["id"]: u for u in sub["units"]}["hifi5"]["load_mcps"] == pytest.approx(50.0)
    report = analyze_timing_budget(_graph(patch="none"), OPTS)
    assert "subsystems" not in report and report["power"]["domain_loads"]["abox"]["model"] == "util-vf-v1"


def test_routes_must_resolve_to_exactly_one():
    both = deepcopy(SUB)
    both["routes"][1]["when"] = {}
    with pytest.raises(ValueError, match="exactly one active route"):
        analyze_timing_budget(_graph(sub=both), OPTS)
    off_stage = deepcopy(SUB)
    off_stage["stages"][4]["when"] = {"output": "bt"}
    with pytest.raises(ValueError, match=r"route pb_cpu stages \['spk'\] are not active"):
        analyze_timing_budget(_graph(sub=off_stage), OPTS)


def test_the_condition_hash_follows_the_subsystem():
    from scenario_db.api.services.timing_budget import _condition_hash
    from tests.unit.sim.test_service_hash import _request

    shim = _request()
    plain = _condition_hash(_exynos2600_generated_graph(UC, CPU_ON), OPTS, shim, {})
    one = _condition_hash(_graph(), OPTS, shim, {})
    heavier = deepcopy(SUB)
    heavier["stages"][2]["mcps"] = 7
    assert len({plain, one, _condition_hash(_graph(sub=heavier), OPTS, shim, {})}) == 3
