"""R-1 / M-1: judgement.rate (request fps > contract rate > design_conditions.fps > 30) and the sink kinds."""

import subprocess
import sys
from copy import deepcopy

import pytest
from pydantic import ValidationError

from scenario_db.authoring.validate import _rate_errors
from scenario_db.models.definition.usecase import JudgementContract, Pipeline, RateSpec
from scenario_db.sim.judgement import declared_rate, rate_and_source
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
        assert "fps" not in (r.get("design_conditions") or {})
        assert any("frame_pacing" in n for n in r["verdict"]["notes"])


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


def test_authoring_checks_the_rate_and_warns_on_a_repeated_pin():
    uc = {"id": "uc", "pipeline": {"judgement": {"rate": {"condition": "target_fps"}}},
          "variants": [{"id": "a", "design_conditions": {"target_fps": 60},
                        "node_configs": {"gpu": {"sim": {"fps": 60}}, "panel": {"sim": {"fps": 120}}}},
                       {"id": "b", "design_conditions": {}}]}
    warnings: list[str] = []
    errors = _rate_errors(uc, warnings)
    assert errors == ["uc/b: judgement.rate condition 'target_fps' missing in design_conditions"]
    assert len(warnings) == 1 and "'gpu' sim.fps 60" in warnings[0]


def test_the_contract_default_has_no_rate():
    assert JudgementContract().rate is None
    assert "rate" not in JudgementContract().model_dump(exclude_none=True)


def test_judgement_does_not_import_the_adapter():
    code = ("import sys, scenario_db.sim.judgement; "
            "assert 'scenario_db.sim.adapter' not in sys.modules and 'scenario_db.sim.timing_budget' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True)
