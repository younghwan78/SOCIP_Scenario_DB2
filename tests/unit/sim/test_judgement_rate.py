"""R-1 / M-1: judgement.rate (request fps > contract rate > design_conditions.fps > 30) and the sink kinds."""

import subprocess
import sys
from copy import deepcopy

import pytest
from pydantic import ValidationError

from scenario_db.models.definition.usecase import JudgementContract, Pipeline, RateSpec
from scenario_db.sim.judgement import baseline_fps, declared_rate, rate_and_source, rate_issues
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

GAME = "uc-game-play-e2600"
MP3 = "uc-aud-mp3-playback-e2600"
OPTS = TimingBudgetOptions(throughput_model="pipelined")


def _run(uc, variant, config=None):
    return analyze_timing_budget(_exynos2600_generated_graph(uc, variant), OPTS, config=config)


@pytest.mark.parametrize("raw", [{}, {"hz": 50, "condition": "target_fps"}, {"hz": 0}, {"hz": float("nan")},
                                 {"hz": float("inf")}, {"condition": ""}])
def test_a_rate_names_exactly_one_finite_positive_source(raw):
    with pytest.raises(ValidationError):
        RateSpec.model_validate(raw)


def test_an_unknown_rate_node_is_refused():
    with pytest.raises(ValidationError, match="judgement.rate node"):
        Pipeline.model_validate({"nodes": [{"id": "gpu", "ip_ref": "ip-gpu"}], "judgement": {"rate": {"node": "dpu"}}})


def test_the_game_is_judged_at_its_target_fps():
    for variant, fps in (("game-fhd-60fps-sdr", 60.0), ("game-fhd-90fps-sdr", 90.0), ("game-fhd-120fps-sdr", 120.0)):
        r = _run(GAME, variant)
        assert r["fps"] == fps and r["fps_source"] == "contract.condition:target_fps"
        assert r["intervals"]["preview"]["node"] == "dpu"            # the display sink takes the preview slot
        assert "pacing" in r and not any("frame_pacing" in n for n in r["verdict"]["notes"])   # R-5: evaluated


def test_a_request_fps_wins_and_moves_the_rate_following_gpu():
    base = _run(GAME, "game-fhd-120fps-sdr")
    swept = _run(GAME, "game-fhd-120fps-sdr", SimulationRunConfig(fps=60))
    assert swept["fps"] == 60.0 and swept["fps_source"] == "request"
    gpu, gpu60 = base["power"]["domain_loads"]["gpu"], swept["power"]["domain_loads"]["gpu"]
    assert (gpu["rate_hz"], gpu60["rate_hz"]) == (120.0, 60.0)   # GPU work follows the swept rate (no sim.fps pin)
    assert gpu60["mw"] < gpu["mw"] and swept["bw"]["total_mbs"] < base["bw"]["total_mbs"]


def test_undeclared_scenarios_keep_their_report_shape():
    r = _run("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr")
    assert "fps_source" not in r and r["fps"] == 30.0
    graph = _exynos2600_generated_graph("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr")
    assert declared_rate(graph) is None
    assert rate_and_source(graph, SimulationRunConfig(fps=60)) == (60.0, None)


@pytest.mark.parametrize("value", [None, 0, float("nan"), "fast"])
def test_a_missing_or_bad_condition_is_refused(value):
    graph = _exynos2600_generated_graph(GAME, "game-fhd-60fps-sdr")
    dc = dict(graph.variant.design_conditions)
    dc.pop("target_fps")
    if value is not None:
        dc["target_fps"] = value
    graph.variant.design_conditions = dc
    with pytest.raises(ValueError, match="judgement.rate"):
        declared_rate(graph)


def test_a_node_rate_reads_that_nodes_sim_fps():
    graph = _exynos2600_generated_graph(GAME, "game-fhd-60fps-npu-ai")
    scenario = deepcopy(graph.scenario.pipeline)
    scenario["judgement"]["rate"] = {"node": "panel"}
    graph.scenario.pipeline = scenario
    graph.variant.node_configs = {**graph.variant.node_configs,
                                  "panel": {**graph.variant.node_configs["panel"],
                                            "sim": {**graph.variant.node_configs["panel"]["sim"], "fps": 48}}}
    assert declared_rate(graph) == (48.0, "contract.node:panel")


def test_audio_is_judged_at_the_mixer_period_but_not_by_frame_interval():
    for variant in ("audio-mp3-screen-on", "audio-mp3-screen-off-offload"):
        r = _run(MP3, variant)
        assert r["fps"] == 50.0 and r["period_ms"] == 20.0 and r["fps_source"] == "contract.hz"
        assert r["verdict"]["status"] == "not_applicable"
        notes = " ".join(r["verdict"]["notes"])
        assert "speaker (audio)" in notes and "bt_codec" not in notes         # inactive sink not listed
        assert "underrun" in notes and "latency" in notes                   # neither evaluated, never passed


def test_streaming_packet_receive_keeps_its_own_rate():
    r = _run("uc-aud-streaming-e2600", "audio-stream-aac-screen-off")
    assert r["fps"] == 50.0
    network = {row["node"]: row for row in r["own_cadence"]}["network"]
    assert network["period_ms"] == pytest.approx(33.333)     # its sw_timing rate, not the 20 ms mixer period
    assert any("assumed" in w for w in r["warnings"])          # own-cadence SW timing is still flagged


def test_the_m2m_driver_model_runs_at_the_declared_rate():
    from scenario_db.sim.driver_models import evaluate_graph

    rows = {r["node_id"]: r for r in evaluate_graph(_exynos2600_generated_graph(GAME, "game-fhd-60fps-m2m-upscale"))["rows"]}
    assert rows["m2m_scaler"]["status"] == "calculated" and rows["m2m_scaler"]["inputs"]["fps"] == 60.0


def test_the_measured_inputs_read_the_declared_rate():
    from scenario_db.api.services.sim_inputs import _fps

    assert _fps(_exynos2600_generated_graph(GAME, "game-fhd-90fps-sdr")) == 90.0


PIPE = {"judgement": {"rate": {"condition": "target_fps"}}}


def test_the_rate_is_checked_on_the_effective_variants():
    variants = [{"id": "a", "design_conditions": {"target_fps": 60, "fps": 60},
                 "node_configs": {"gpu": {"sim": {"fps": 60}}, "panel": {"sim": {"fps": 120}}}},
                {"id": "child", "derived_from_variant": "a", "design_conditions_override": {"target_fps": 90}},
                {"id": "b", "design_conditions": {}}]
    errors, warnings = rate_issues("uc", PIPE, variants)
    # the child inherits fps 60 but overrides the rate to 90: a mismatch; b has no rate at all
    assert any(e.startswith("uc/child: design_conditions.fps 60") for e in errors)
    assert any(e.startswith("uc/b: judgement.rate") for e in errors) and len(errors) == 2
    assert all("'gpu' sim.fps 60" in w for w in warnings if w.startswith("uc/a:")) and len(warnings) >= 1


def test_an_inherited_rate_resolves():
    variants = [{"id": "a", "design_conditions": {"target_fps": 60}}, {"id": "c", "derived_from_variant": "a"}]
    assert rate_issues("uc", PIPE, variants) == ([], [])


def test_a_badly_typed_rate_is_left_to_the_schema_check():
    assert rate_issues("uc", {"judgement": {"rate": {"condition": ["target_fps"]}}}, [{"id": "a"}]) == ([], [])


def test_the_e2600_game_and_audio_rates_resolve_in_every_variant():
    import yaml

    for uc in (GAME, MP3, "uc-aud-streaming-e2600"):
        with open(f"db_Exynos2600_SM-S947B/02_definition/{uc}.yaml", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        assert rate_issues(uc, doc["pipeline"], doc["variants"]) == ([], []), uc


def test_measured_replay_and_sensor_modes_compare_the_declared_rate():
    graph = _exynos2600_generated_graph(GAME, "game-fhd-90fps-sdr")
    assert baseline_fps(graph) == 90.0
    graph.variant.design_conditions = {k: v for k, v in graph.variant.design_conditions.items() if k != "fps"}
    assert baseline_fps(graph) == 90.0                     # the contract, not the stored design fps
    yt = _exynos2600_generated_graph("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr")
    assert baseline_fps(yt) == yt.variant.design_conditions.get("fps")


def test_a_request_fps_moves_the_rate_following_m2m_driver():
    from scenario_db.sim.adapter import build_simulation_inputs

    graph = _exynos2600_generated_graph(GAME, "game-fhd-60fps-m2m-upscale")
    rows = {r["node_id"]: r for r in build_simulation_inputs(graph, SimulationRunConfig(fps=45)).driver_model_report["rows"]}
    assert rows["m2m_scaler"]["inputs"]["fps"] == 45.0


def test_the_contract_default_has_no_rate():
    assert JudgementContract().rate is None
    assert "rate" not in JudgementContract().model_dump(exclude_none=True)


def test_judgement_does_not_import_the_adapter():
    code = ("import sys, scenario_db.sim.judgement; "
            "assert 'scenario_db.sim.adapter' not in sys.modules and 'scenario_db.sim.timing_budget' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_the_write_api_reports_an_unresolved_rate_on_the_staged_variant():
    from scenario_db.write.service import _rate_write_issues

    variants = [{"id": "a", "design_conditions": {"target_fps": 60}}, {"id": "b", "design_conditions": {}}]
    issues = _rate_write_issues("uc", PIPE, variants, "payload.variant", only={"b"})
    assert [(i.severity, i.code) for i in issues] == [("error", "judgement_rate_invalid")]
    assert _rate_write_issues("uc", PIPE, variants, "payload.variant", only={"a"}) == []


def test_a_non_mapping_rate_node_config_is_a_check_error_not_a_crash():
    pipe = {"judgement": {"rate": {"node": "gpu"}}}
    errors, _ = rate_issues("uc", pipe, [{"id": "a", "node_configs": {"gpu": "60fps"}}])
    assert errors and "has no sim.fps" in errors[0]


def test_a_whatif_fps_change_keeps_a_node_with_its_own_rate():
    from types import SimpleNamespace

    from scenario_db.api.services.whatif_conditions import _Apply, _apply_fps

    variant = SimpleNamespace(design_conditions={"target_fps": 60, "fps": 60},
                              node_configs={"panel": {"sim": {"fps": 90}}, "gpu": {"sim": {"width": 1920}}})
    candidate = SimpleNamespace(scenario=SimpleNamespace(pipeline=PIPE), variant=variant)
    ctx = _Apply(candidate=candidate, variant=variant, config=SimulationRunConfig(), targets={"fps": 60})
    _apply_fps(ctx, {"value": 45})
    assert ctx.config.fps == 45 and variant.node_configs["panel"]["sim"]["fps"] == 90
    assert variant.design_conditions["fps"] == 45


def test_the_evidence_check_skips_own_cadence_sink_events():
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    path = Path(__file__).resolve().parents[3] / "scripts" / "verify_is_v15_camera.py"
    spec = importlib.util.spec_from_file_location("verify_is_v15_camera", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    vsync = SimpleNamespace(node_id="panel", frame_index=None, end_ms=5.0, cadence_avg_interval_ms=16.6)
    out = mod.assess(SimpleNamespace(feasible=True, timeline_events=[vsync]), 60.0, 3.0, {"panel"})
    assert out["accepted"] is False and out["max_frame_latency_ms"] == float("inf")
