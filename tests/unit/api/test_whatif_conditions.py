"""Conditions must preserve the baseline and bind to actual resolved inputs."""
from copy import deepcopy

import pytest

from scenario_db.api.schemas.scenario_whatif import WhatIfChange, WhatIfPreviewRequest
from scenario_db.api.services.whatif_conditions import apply_whatif_changes, whatif_targets
from scenario_db.api.services.whatif_query import plan_query
from scenario_db.db.models.definition import Project
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.timing_budget import analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph


@pytest.fixture
def graph():
    g = _exynos2600_generated_graph("uc-cam-recording-e2600", "cam-rec-r1-uhd30-vdis")
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    return g


def _change(**kw):
    return WhatIfChange(**kw)


def test_record_resize_preserves_sensor_and_preview_but_changes_clock_power_bw(graph):
    before = baseline_fingerprint(graph)
    original_config = SimulationRunConfig()
    candidate, config, _ = apply_whatif_changes(graph, [_change(target="output_size", anchor_id="record_out",
                    width=1920, height=1080)], original_config)
    base_inputs, inputs = build_simulation_inputs(graph), build_simulation_inputs(candidate)
    def sizes(inputs):
        return {w.node_id: (w.width, w.height) for w in inputs.workloads}
    assert sizes(inputs)["mfc_enc"] == sizes(inputs)["gdc_o"] == (1920, 1080)
    for key in ("csis", "pdp", "mcsc", "dpu", "gdc_m"):
        assert sizes(inputs)[key] == sizes(base_inputs)[key]
    assert candidate.variant.size_overrides["sensor_full"] == graph.variant.size_overrides["sensor_full"]
    a, b = analyze_timing_budget(graph), analyze_timing_budget(candidate, config=config)
    assert b["power"]["total_mw"] < a["power"]["total_mw"]
    assert b["bw"]["total_mbs"] < a["bw"]["total_mbs"]
    ai = {i["node"]: i for i in a["ips"]}
    bi = {i["node"]: i for i in b["ips"]}
    assert bi["mfc_enc"]["own_required_mhz"] < ai["mfc_enc"]["own_required_mhz"]
    assert baseline_fingerprint(graph) == before
    assert original_config.fps is None


def test_node_surface_resize_propagates_named_buffer_consumers(graph):
    candidate, _, _ = apply_whatif_changes(graph, [_change(target="node_size", node_id="gdc_o", width=1920, height=1080)], SimulationRunConfig())
    sizes = {w.node_id: (w.width, w.height) for w in build_simulation_inputs(candidate).workloads}
    assert sizes["gdc_o"] == sizes["mfc_enc"] == (1920, 1080)
    with pytest.raises(ValueError, match="unsupported node_size"):
        apply_whatif_changes(graph, [_change(target="node_size", node_id="csis", width=1920, height=1080)], SimulationRunConfig())


def test_sensor_and_ambiguous_output_rejected(graph):
    for change, match in [(_change(target="anchor_size", anchor_id="sensor_full", width=1920, height=1080), "unsupported size anchor"),
                          (_change(target="output_size", width=1920, height=1080), "ambiguous")]:
        with pytest.raises(ValueError, match=match):
            apply_whatif_changes(graph, [change], SimulationRunConfig())


def test_fps_and_clock_are_explicit_bounded_conditions(graph):
    graph.variant.node_configs["mfc_enc"]["sim"]["fps"] = 30
    candidate, config, _ = apply_whatif_changes(graph, [_change(target="fps", value=60),
        _change(target="node_clock_mhz", node_id="mfc_enc", value=600)], SimulationRunConfig())
    inputs = build_simulation_inputs(candidate, config)
    assert inputs.config.fps == 60
    assert all(w.fps == 60 for w in inputs.workloads)
    assert next(w for w in inputs.workloads if w.node_id == "mfc_enc").manual_clock_mhz == 600
    assert graph.variant.node_configs["mfc_enc"]["sim"]["fps"] == 30
    for kw in ({"target": "fps", "value": 241}, {"target": "node_clock_mhz", "node_id": "mfc_enc", "value": float("nan")}):
        with pytest.raises(ValueError):
            _change(**kw)


@pytest.mark.parametrize("query,target,anchor", [
    ("센서 입력은 유지하고 녹화 출력을 FHD로 변경하면 clock과 power가?", "output_size", "record_out"),
    ("Keep sensor input unchanged and change recording output from UHD to FHD", "output_size", "record_out"),
    ("record_out을 1920x1080으로 변경", "anchor_size", "record_out"),
    ("녹화를 FHD로 낮추면 전력이 얼마나 줄어?", "output_size", "record_out"),
    ("녹화 해상도를 절반으로", "output_size", "record_out"),
])
def test_korean_english_query_is_explicit(graph, query, target, anchor):
    plan = plan_query(query, whatif_targets(graph))
    assert plan["status"] == "ready"
    assert plan["changes"] == [{"target": target, "anchor_id": anchor, "width": 1920, "height": 1080}]


@pytest.mark.parametrize("query", [
    "센서를 UHD와 녹화 FHD 둘다 변경",          # which size is the sensor's is undecidable -> nothing runs
    "센서 입력 FHD로 변경",
    "센서를 binning 모드로 바꾸면",
    "codec을 HEVC로 바꾸면?",
    "SELECT power FROM scenarios",
    "전력 얼마야?",
])
def test_unsupported_query_never_produces_changes(graph, query):
    out = plan_query(query, whatif_targets(graph))
    assert out["status"] == "unsupported"
    assert out["changes"] == []


@pytest.mark.parametrize("query,hint", [
    ("센서 입력 FHD로 변경", "Sensor Explore"),
    ("codec을 HEVC로 바꾸면?", "variant"),
    ("CPU를 HF로 옮기면", "CPU what-if"),
])
def test_unsupported_parts_name_where_they_are_handled(graph, query, hint):
    out = plan_query(query, whatif_targets(graph))
    assert any(hint in (item["hint"] or "") for item in out["ignored"])


@pytest.mark.parametrize("query,change,ignored", [
    ("recording output FHD, compression off", {"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}, "compression"),
    ("recording output FHD and voltage change to 900", {"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}, "voltage"),
    ("FPS를 60으로 변경하고 밝기를 낮춰줘", {"target": "fps", "value": 60}, "밝기"),
    ("녹화 출력을 FHD로 변경하고 코덱을 APV로 바꿔줘", {"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}, "코덱"),
    ("녹화 FHD로 바꾸고 EIS 끄면 전력은?", {"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}, "EIS"),
    ("Change recording output to FHD and rotate 90 degrees", {"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}, "rotate"),
    ("Change FPS to 60 and quantum-flux 12", {"target": "fps", "value": 60}, "quantum-flux"),
    ("센서 입력은 유지 rotate 90 degrees, 녹화 출력 FHD", {"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}, "rotate"),
])
def test_partial_query_runs_only_supported_part_and_reports_the_rest(graph, query, change, ignored):
    out = plan_query(query, whatif_targets(graph))
    assert out["status"] == "partial"
    assert out["changes"] == [change]
    assert any(ignored in item["text"] for item in out["ignored"])


@pytest.mark.parametrize("query,field", [
    ("clock 600 MHz", "node_id"),
    ("GDC clock 400MHz로", "node_id"),
    ("mfc_enc clock 400 MHz와 600 MHz를 비교", "clock"),
    ("프레임을 낮추면 전력은?", "fps"),
    ("해상도를 올리면?", "size"),
    ("녹화를 FHD로, 녹화를 HD로", "duplicate"),
])
def test_ambiguity_never_runs_and_every_choice_is_a_complete_change(graph, query, field):
    out = plan_query(query, whatif_targets(graph))
    assert out["status"] == "clarification" and out["changes"] == []
    clar = next(c for c in out["clarifications"] if c["field"] == field)
    assert clar["choices"] and all(WhatIfChange(**{k: v for k, v in ch["change"].items() if k != "scale"}) or True
                                   for ch in clar["choices"])
    assert all(ch["change"]["target"] for ch in clar["choices"])


def test_query_fps_and_node_clock(graph):
    targets = whatif_targets(graph)
    assert plan_query("FPS를 60으로 변경", targets)["changes"] == [{"target": "fps", "value": 60}]
    assert plan_query("mfc_enc clock 600 MHz", targets)["changes"] == [{"target": "node_clock_mhz", "node_id": "mfc_enc", "value": 600}]
    assert plan_query("인코더 클럭을 0.6 GHz로 올리면", targets)["changes"] == [{"target": "node_clock_mhz", "node_id": "mfc_enc", "value": 600}]
    assert plan_query("fps 절반으로 하면?", targets)["changes"] == [{"target": "fps", "value": 15}]
    # relative clock is resolved to MHz by the service against the baseline set clock
    assert plan_query("MFC 클럭 20% 낮추면 timing 여유는?", targets)["changes"] == [{"target": "node_clock_mhz", "node_id": "mfc_enc", "scale": 0.8}]


def test_combined_size_rate_and_focus(graph):
    out = plan_query("FHD 60으로 찍으면 BW랑 전력은?", whatif_targets(graph))
    assert out["changes"] == [{"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}, {"target": "fps", "value": 60}]
    assert set(out["focus"]) == {"bw", "power"}
    assert out["notes"]                         # bare size -> record output is stated, not silent
    out = plan_query("UHD60으로 바꾸면 timing 버틸 수 있어?", whatif_targets(graph))
    assert out["changes"] == [{"target": "fps", "value": 60}]      # record_out is already UHD: no-op size dropped
    assert "timing" in out["focus"] and "feasible" in out["focus"]


def test_query_preservation_and_each_clause_target_are_separate(graph):
    targets = whatif_targets(graph)
    out = plan_query("녹화 출력을 FHD로 변경하고 센서 입력 4032x3024는 유지", targets)
    assert out["changes"] == [{"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}]
    assert out["kept"]
    out = plan_query("녹화 출력을 FHD로 변경하고 mfc_enc clock을 600 MHz로 변경", targets)
    assert out["changes"] == [{"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080},
                              {"target": "node_clock_mhz", "node_id": "mfc_enc", "value": 600}]
    out = plan_query("녹화 UHD는 유지하고 FPS를 60으로 변경", targets)
    assert out["changes"] == [{"target": "fps", "value": 60}]
    out = plan_query("녹화 UHD는 유지하고 FPS를 30으로 변경", targets)
    assert out["status"] == "no_change" and out["changes"] == []


@pytest.mark.parametrize("query", [
    "센서입력유지하고녹화출력FHD변경하면clock과power는?",
    "센서 입력은 유지하고 녹화 출력을 FHD로 변경하면 clock과 power가 어떻게 변하는지?",
    "Change recording output from UHD to FHD and how does that affect power?",
    "Change recording output to FHD and clock and power?",
])
def test_bounded_grammar_accepts_supported_change_and_impact_questions(graph, query):
    out = plan_query(query, whatif_targets(graph))
    assert out["status"] == "ready"
    assert out["changes"] == [{"target": "output_size", "anchor_id": "record_out", "width": 1920, "height": 1080}]


@pytest.mark.parametrize("width,height", [("output_width", "output_height"), ("width_out", "height_out")])
def test_output_transform_aliases_follow_resized_anchor(graph, width, height):
    graph.variant.node_configs["gdc_o"]["sim"].update({width: 3840, height: 2160})
    candidate, _, _ = apply_whatif_changes(graph, [_change(target="output_size", anchor_id="record_out", width=1920, height=1080)], SimulationRunConfig())
    assert candidate.variant.node_configs["gdc_o"]["sim"][width] == 1920
    assert candidate.variant.node_configs["gdc_o"]["sim"][height] == 1080
    sizes = {w.node_id: (w.width, w.height) for w in build_simulation_inputs(candidate).workloads}
    assert sizes["gdc_o"] == sizes["mfc_enc"] == (1920, 1080)


def test_preview_rejects_measured_extrapolation_and_overlapping_changes(graph):
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id,
                 expected_baseline_hash=baseline_fingerprint(graph), changes=[dict(target="fps", value=60)])
    with pytest.raises(ValueError, match="measured clock"):
        WhatIfPreviewRequest(**scope, config={"measured_clock_ref": "measure"})
    with pytest.raises(ValueError, match="measured CPU"):
        WhatIfPreviewRequest(**scope, options={"cpu_model": "profile"})
    with pytest.raises(ValueError, match="overlap"):
        apply_whatif_changes(graph, [_change(target="anchor_size", anchor_id="record_out", width=1920, height=1080),
                      _change(target="node_size", node_id="gdc_o", width=1280, height=720)], SimulationRunConfig())


def test_capability_change_changes_baseline_fingerprint(graph):
    old = baseline_fingerprint(graph)
    ip = graph.ip_catalog[next(iter(graph.ip_catalog))]
    ip.capabilities = deepcopy(ip.capabilities)
    ip.capabilities["sim"] = {**ip.capabilities.get("sim", {}), "unit_power_mw_mp": 99}
    assert baseline_fingerprint(graph) != old


@pytest.mark.parametrize("query", ["녹화 99999x99999", "녹화 해상도 200% 줄이면", "녹화 해상도 100배", "녹화 해상도 99.99% 줄이면", "FPS 999와 1000 fps", "mfc_enc 9999 MHz와 10000 MHz"])
def test_plan_never_returns_out_of_bounds_conditions_or_choices(graph, query):
    out = plan_query(query, whatif_targets(graph))
    assert out["status"] == "unsupported"
    assert out["ignored"] and not out["changes"] and not out["clarifications"]
