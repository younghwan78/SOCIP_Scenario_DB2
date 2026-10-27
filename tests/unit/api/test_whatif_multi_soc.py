"""What-if is SoC-agnostic: availability comes from the variant's data, not from a SoC allow-list."""
import pytest

from scenario_db.api.schemas.scenario_whatif import WhatIfChange
from scenario_db.api.services.whatif_conditions import CHANGE_KINDS, ChangeKind, apply_whatif_changes, register, whatif_targets
from scenario_db.api.services.whatif_query import plan_query
from scenario_db.db.models.definition import Project
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _fixture_graph


def _g(fixture, scenario, variant, soc):
    g = _fixture_graph(fixture, scenario, variant)
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": soc}, globals_={})
    return g


def _run(graph, changes):
    candidate, config, _ = apply_whatif_changes(graph, [WhatIfChange(**c) for c in changes], SimulationRunConfig())
    return (analyze_timing_budget(graph, TimingBudgetOptions(), config=SimulationRunConfig()),
            analyze_timing_budget(candidate, TimingBudgetOptions(), config=config))


@pytest.fixture(scope="module")
def e2700():
    return _g("db_Exynos2700_SM-S957B", "uc-cam-recording-e2700", "cam-rec-r1-uhd120", "soc-exynos2700")


@pytest.fixture(scope="module")
def playback():
    return _g("db_Exynos2600_SM-S947B", "uc-vid-playback-local-e2600", "vplay-local-h264-fhd30-sdr", "soc-exynos2600")


def test_stream_groups_cannot_cascade_into_another_selected_group(playback):
    from copy import deepcopy
    graph = deepcopy(playback)
    graph.variant.node_configs["extra_surface"] = {"width": 1280, "height": 720}
    changes = [WhatIfChange(target="stream_size", stream_id="1920x1080", width=1280, height=720),
               WhatIfChange(target="stream_size", stream_id="1280x720", width=3840, height=2160)]
    original = deepcopy(graph.variant.node_configs)
    for ordered in (changes, list(reversed(changes))):
        with pytest.raises(ValueError, match="overlap"):
            apply_whatif_changes(graph, ordered, SimulationRunConfig())
    assert graph.variant.node_configs == original


def test_exynos2700_recording_runs_end_to_end(e2700):
    targets = whatif_targets(e2700)
    assert targets["capability"]["soc_ref"] == "soc-exynos2700"
    assert targets["capability"]["soc_profile"] == "generic" and targets["capability"]["notes"]   # default policy is stated
    assert {"output_size", "fps", "node_clock_mhz"} <= set(targets["supported_changes"])
    out = plan_query("녹화를 FHD로 낮추면 전력은?", targets)
    assert out["status"] == "ready" and out["changes"][0]["anchor_id"] == "record_out"
    before, after = _run(e2700, out["changes"])
    assert after["power"]["total_mw"] < before["power"]["total_mw"]
    assert after["bw"]["total_mbs"] < before["bw"]["total_mbs"]


def test_output_role_comes_from_consumer_ip_category(e2700):
    roles = {a["id"]: a["role"] for a in whatif_targets(e2700)["anchors"] if a["kind"] == "output"}
    assert roles == {"record_out": "record", "preview_out": "preview"}


def test_anchorless_playback_changes_the_main_stream_together(playback):
    targets = whatif_targets(playback)
    assert targets["anchors"] == [] and targets["streams"][0]["primary"]
    out = plan_query("UHD로 재생하면 전력은?", targets)
    assert out["changes"] == [{"target": "stream_size", "stream_id": "1920x1080", "width": 3840, "height": 2160}]
    assert any("mfc_dec" in note for note in out["notes"])          # what moves together is stated
    before, after = _run(playback, out["changes"])
    assert after["power"]["total_mw"] > before["power"]["total_mw"]
    # decoder alias resolves through the IP catalog category, not a SoC-specific table
    assert plan_query("디코더 clock 400MHz", targets)["changes"] == [{"target": "node_clock_mhz", "node_id": "mfc_dec", "value": 400}]


def test_unmodeled_parameter_is_reported_not_offered(playback):
    targets = whatif_targets(playback)
    assert "node_param" not in targets["supported_changes"]
    out = plan_query("주사율 120Hz로 바꾸면 전력은?", targets)
    assert out["status"] == "unsupported" and "모델" in out["ignored"][0]["reason"]


def test_variant_without_modelable_conditions_says_so():
    g = _g("db_Exynos2600_SM-S947B", "uc-aud-mp3-playback-e2600", "audio-mp3-screen-on", "soc-exynos2600")
    targets = whatif_targets(g)
    # only the LLC placement of its DMA buffers is modelable (no size / clock / sensor condition)
    assert set(targets["supported_changes"]) <= {"llc_alloc"}
    out = plan_query("FHD로", targets)
    assert out["status"] == "unsupported" and out["ignored"]


def test_new_change_kind_is_one_registration(e2700):
    kind = register(ChangeKind("demo_scale", "데모", "value", None, max_value=2.0,
                               discover=lambda t: [{"id": "demo"}], apply=lambda ctx, data: ("demo_scale", None)))
    try:
        assert "demo_scale" in whatif_targets(e2700)["supported_changes"]
        WhatIfChange(target="demo_scale", value=1.5)
        with pytest.raises(ValueError):
            WhatIfChange(target="demo_scale", value=3)
    finally:
        CHANGE_KINDS.pop(kind.target)
    with pytest.raises(ValueError, match="unsupported What-if target"):
        WhatIfChange(target="demo_scale", value=1.5)
