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
    "stages": [{"id": "rdma", "kind": "dma", "unit": "dma", "stream": "pb_main"},
               {"id": "decode", "kind": "codec", "unit": "hifi5", "stream": "pb_main", "mcps": 18,
                "when": {"offload": True}},
               {"id": "mix", "kind": "mixer", "unit": "ca32_0", "stream": "pb_out", "mcps": 6},
               {"id": "eq", "kind": "effect", "unit": "hifi5", "stream": "pb_out", "mcps": 25},
               {"id": "spk", "kind": "solution", "unit": "ca32_1", "stream": "pb_out", "mcps": 12, "bind": "speaker"},
               {"id": "out", "kind": "interface", "unit": "uaif0", "stream": "pb_out", "bind": "speaker"}],
    "edges": [["rdma", "decode"], ["decode", "mix"], ["rdma", "mix"], ["mix", "eq"], ["eq", "spk"], ["spk", "out"]],
    "routes": [{"id": "pb_cpu", "kind": "playback", "when": {"offload": False},
                "stages": ["rdma", "mix", "eq", "spk", "out"], "latency_target_ms": 60},
               {"id": "pb_off", "kind": "playback", "when": {"offload": True},
                "stages": ["rdma", "decode", "mix", "eq", "spk", "out"]}],
    "wake": [{"kind": "period_irq", "stream": "pb_main", "when": {"offload": False}},
             {"kind": "refill", "every_ms": 2000, "mb": 0.4, "when": {"offload": True}}],
}
OPTS = TimingBudgetOptions(throughput_model="pipelined")


def _plain(variant=CPU_ON):
    """The MP3 graph with the ABOX subsystem of the E2600 data and its variant patches taken out (R-4b)."""
    graph = _exynos2600_generated_graph(UC, variant)
    for node in graph.scenario.pipeline["nodes"]:
        if node["id"] == "abox":
            node.pop("subsystem", None)
    cfgs = dict(graph.variant.node_configs or {})
    abox = dict(cfgs.get("abox") or {})
    abox["sim"] = {k: v for k, v in (abox.get("sim") or {}).items() if k != "subsystem"}
    abox.pop("dvfs", None)      # the clock is chosen, not pinned (pinning: its own test)
    cfgs["abox"] = abox
    graph.variant.node_configs = cfgs
    return graph


def _graph(variant=CPU_ON, sub=None, patch=None):
    graph = _plain(variant)
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
    (lambda s: s["stages"][2].update(unit="ghost"), "unit 'ghost' not found"),
    (lambda s: s["stages"][2].update(stream="ghost"), "stream 'ghost' not found"),
    (lambda s: s["stages"][0].update(mcps=3), "a load needs a cpu / dsp unit"),
    (lambda s: s["stages"][2].update(mcycles_per_period=1), "mcps or mcycles_per_period, not both"),
    (lambda s: s["routes"][0].update(stages=["rdma", "eq", "mix", "spk", "out"]), "are not edges"),
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
    with pytest.raises(ValidationError, match=r"names unknown nodes \['speaker'\]"):
        Pipeline.model_validate({"nodes": nodes})
    Pipeline.model_validate({"nodes": nodes + [{"id": "speaker", "ip_ref": "ip-abox"}]})


def test_an_undeclared_node_dumps_no_subsystem():
    assert "subsystem" not in Pipeline.model_validate({"nodes": [{"id": "a", "ip_ref": "ip-x"}]}).model_dump(
        exclude_none=True)["nodes"][0]


# ---------------------------------------------------------------------------- evaluator

def test_without_a_subsystem_the_report_has_none():
    plain = analyze_timing_budget(_plain(), OPTS)
    assert "subsystems" not in plain
    assert "abox" not in (plain["power"].get("domain_loads") or {})


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
    assert "subsystems" not in report and "abox" not in (report["power"].get("domain_loads") or {})


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
    plain = _condition_hash(_plain(), OPTS, shim, {})
    one = _condition_hash(_graph(), OPTS, shim, {})
    heavier = deepcopy(SUB)
    heavier["stages"][2]["mcps"] = 7
    assert len({plain, one, _condition_hash(_graph(sub=heavier), OPTS, shim, {})}) == 3


@pytest.mark.parametrize("mutate,message", [
    (lambda s: s["units"][0].update(power={**CA32, "vf": [600]}), r"vf must be a list of \{mhz: > 0, mv: > 0\}"),
    (lambda s: s["units"][0].update(power={**CA32, "coeff_uw_per_mhz_v2": float("inf")}), "must be a positive number"),
    (lambda s: s["units"][3].update(power={"mw": float("inf")}), "finite >= 0"),
    (lambda s: s["units"][0].update(power={**CA32, "leakage": {"mw_at_ref": -1}}), "leakage takes"),
    (lambda s: s["units"][0].update(power={**CA32, "gain": 2}), r"unknown keys \['gain'\]"),
    (lambda s: s["stages"][2].pop("stream"), r"load stages \['mix'\] need a stream"),
])
def test_power_coefficients_and_route_periods_are_checked(mutate, message):
    sub = deepcopy(SUB)
    mutate(sub)
    with pytest.raises(ValidationError, match=message):
        SubsystemSpec.model_validate(sub)


def test_a_shared_clock_takes_only_levels_every_unit_supports():
    one = deepcopy(SUB)
    one["units"][0]["freqs_mhz"] = [150]                    # catalog levels start at 200: no common point
    with pytest.raises(ValueError, match="share no operating point"):
        analyze_timing_budget(_graph(sub=one), OPTS)
    both = deepcopy(SUB)
    for u in both["units"][:3]:
        u["freqs_mhz"] = [300, 600]
    assert _sub(_graph(sub=both))["domains"]["AUD"]["freq_mhz"] == pytest.approx(300.0)


def test_a_subsystem_replaces_the_node_power_and_keeps_coverage_partial():
    report = analyze_timing_budget(_graph(), OPTS)
    assert report["power"]["hw_by_ip"]["abox"] == pytest.approx(report["subsystems"]["abox"]["mw"], abs=1e-3)
    assert "abox.uaif0" in report["power"]["zero_power_ips"]          # an unattributed unit: a lower bound
    full = deepcopy(SUB)
    full["units"][4]["power"] = {"mw": 0.5}
    assert not [z for z in analyze_timing_budget(_graph(sub=full), OPTS)["power"]["zero_power_ips"]
                if z.startswith("abox.")]


def test_a_patched_declaration_must_name_real_nodes():
    with pytest.raises(ValueError, match=r"names unknown nodes \['ghost'\]"):
        analyze_timing_budget(_graph(patch={"$items": {"stages": {"patch": {"mix": {"bind": "ghost"}}}}}), OPTS)
    with pytest.raises(ValueError, match=r"names unknown nodes \['ghost'\]"):
        analyze_timing_budget(_graph(patch={"$items": {"stages": {"patch": {"mix": {"when_node_enabled": "ghost"}}}}}),
                              OPTS)


def test_a_bad_patch_on_a_disabled_node_does_not_break_the_hash():
    from scenario_db.api.services.timing_budget import _condition_hash
    from tests.unit.sim.test_service_hash import _request

    graph = _graph(patch={"$items": {"stages": {"patch": {"ghost": {"mcps": 1}}}}})
    assert isinstance(_condition_hash(graph, OPTS, _request(), {}), str)


def test_a_yaml_declaration_parses_with_the_unit_key():
    import yaml

    doc = yaml.safe_load("""
units: [{id: dsp, kind: dsp, power: {coeff_uw_per_mhz_v2: 90, vf: [{mhz: 200, mv: 600}]}}]
streams: [{id: s, fs_hz: 48000, channels: 2, bits: 16, period_frames: 240}]
stages: [{id: eq, kind: effect, unit: dsp, stream: s, mcps: 25}]
""")
    assert SubsystemSpec.model_validate(doc).stages[0].unit == "dsp"


def test_non_compute_units_on_a_clock_share_its_levels():
    sub = deepcopy(SUB)
    for u in sub["units"][:3]:
        u["freqs_mhz"] = [200, 400]
    sub["units"][3].update(clock_domain="AUD", freqs_mhz=[400])        # dma runs at 400 only
    assert _sub(_graph(sub=sub))["domains"]["AUD"]["freq_mhz"] == pytest.approx(400.0)


def test_the_ip_row_shows_the_subsystem_power():
    report = analyze_timing_budget(_graph(), OPTS)
    row = next(ip for ip in report["ips"] if ip["node"] == "abox")
    assert row["power_mw"] == pytest.approx(report["subsystems"]["abox"]["mw"], abs=1e-3)


@pytest.mark.parametrize("patch,message", [("nnoe", "takes a patch mapping or 'none'"),
                                           ({"$items": ["stages"]}, "patch is malformed"),
                                           (3, "takes a patch mapping or 'none'")])
def test_a_malformed_variant_slot_is_an_input_error(patch, message):
    with pytest.raises(ValueError, match=message):
        analyze_timing_budget(_graph(patch=patch), OPTS)


def test_null_takes_the_default_and_an_explicit_zero_stays_zero():
    sub = deepcopy(SUB)
    sub["units"][0]["power"] = {**CA32, "idle_gated": None,
                                "leakage": {"mw_at_ref": 10, "ref_mv": 750, "exponent": 0}}
    ca32_0 = {u["id"]: u for u in _sub(_graph(sub=sub))["units"]}["ca32_0"]
    assert ca32_0["static_mw"] == pytest.approx(10.0, abs=1e-3)          # V^0: constant leakage


def test_a_modeled_zero_is_not_unmodeled():
    sub = deepcopy(SUB)
    sub["units"] = [{"id": "dma", "kind": "hw", "power": {"mw": 0}}]
    sub["stages"] = [s for s in sub["stages"] if s["id"] == "rdma"]
    sub["edges"], sub["routes"], sub["wake"] = [], None, None
    report = analyze_timing_budget(_graph(sub=sub), OPTS)
    assert "abox" not in report["power"]["zero_power_ips"]


@pytest.mark.parametrize("mutate,message", [
    (lambda s: s["wake"].append({"kind": "event", "per_s": float("inf")}), "finite number"),
    (lambda s: s["routes"][0]["stages"].extend(["mix"]), "visits each stage once"),
])
def test_finite_wake_inputs_and_linear_routes(mutate, message):
    sub = deepcopy(SUB)
    mutate(sub)
    with pytest.raises(ValidationError, match=message):
        SubsystemSpec.model_validate(sub)


def test_a_tiny_refill_period_is_refused_not_infinite():
    sub = deepcopy(SUB)
    sub["wake"][1]["every_ms"] = 1e-320
    with pytest.raises(ValueError, match="rate is not finite"):
        analyze_timing_budget(_graph(OFFLOAD, sub=sub), OPTS)


def _pin(graph, khz):
    cfgs = dict(graph.variant.node_configs or {})
    cfgs["abox"] = {**cfgs["abox"], "dvfs": {"aud_freq_khz": khz}}
    graph.variant.node_configs = cfgs
    return graph


def test_the_node_aud_operating_point_pins_the_domain_clock():
    free = _sub(_graph())
    pinned = _sub(_pin(_graph(), 400000))
    assert free["domains"]["AUD"]["freq_mhz"] < 400 and "pinned" not in free["domains"]["AUD"]
    assert pinned["domains"]["AUD"] == {**pinned["domains"]["AUD"], "freq_mhz": 400.0, "pinned": True}
    assert pinned["mw"] > free["mw"]
    with pytest.raises(ValueError, match="pinned to 123 MHz"):
        _sub(_pin(_graph(), 123000))


def test_the_pinned_clock_is_in_the_condition_hash():
    from scenario_db.api.services.timing_budget import _domain_load_inputs

    assert _domain_load_inputs(_graph())["abox"] != _domain_load_inputs(_pin(_graph(), 400000))["abox"]


def test_a_hw_or_interface_unit_without_an_active_stage_is_gated():
    sub = deepcopy(SUB)
    sub["units"][4]["power"] = {"mw": 0.3}
    sub["units"].append({"id": "uaif1", "kind": "interface", "power": {"mw": 0.3}})
    sub["units"].append({"id": "sram", "kind": "memory", "power": {"mw": 0.2}})
    units = {u["id"]: u for u in _sub(_graph(sub=sub))["units"]}
    assert units["uaif1"] == {**units["uaif1"], "mw": 0.0, "gated": True}
    assert units["uaif0"]["mw"] == 0.3 and units["sram"]["mw"] == 0.2 and "gated" not in units["sram"]
