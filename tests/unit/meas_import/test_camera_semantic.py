from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from scenario_db.meas_import.camera import parse_markdown, assemble_camera, canonical_hash, main
from scenario_db.models.evidence.measurement import MeasurementEvidence
from scenario_db.sim.sw_projection import SwProjectionSelection, build_projection, apply_projection

EXAMPLE = (
    Path(__file__).resolve().parents[3]
    / "examples/measurement-import/camera/scenario-statistics.md"
)


def bundle():
    return parse_markdown(EXAMPLE.read_text(encoding="utf-8"))


def evidence():
    return assemble_camera(bundle())


def test_summary_contract_and_deterministic_cli(tmp_path):
    item = evidence()
    assert item.sw_task_timing[0].mean_ms == 0.2
    assert item.sw_event_latency[0].pairing == "producer_defined"
    assert item.stage_timing[0].usage == "validation_only"
    assert not item.timeline_events
    assert item.provenance.import_fingerprint == canonical_hash(item)
    output = tmp_path / "out.yaml"
    assert main(["--markdown", str(EXAMPLE), "--out", str(output)]) == 0
    before = output.read_bytes()
    assert main(["--markdown", str(EXAMPLE), "--out", str(output)]) == 0
    assert output.read_bytes() == before
    assert (
        MeasurementEvidence.model_validate(yaml.safe_load(before)).pipeline_model
        == item.pipeline_model
    )


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "alias",
        "two_blocks",
        "avg_conflict",
        "samples",
        "inactive",
        "cycle",
        "nan",
        "anchor",
    ],
)
def test_reject_malformed_producer_data(change):
    text = EXAMPLE.read_text(encoding="utf-8")
    if change == "duplicate":
        text = text.replace("format_version:", "id: duplicate\nformat_version:")
    elif change == "alias":
        text = text.replace("workload:", "workload: &workload")
    elif change == "two_blocks":
        text += text
    elif change == "avg_conflict":
        text = text.replace("avg_ms: 0.2", "avg_ms: 0.2\n    mean_ms: 9")
    elif change == "samples":
        text = text.replace("samples: 600", "samples: 0")
    elif change == "nan":
        text = text.replace("avg_ms: 0.2", "avg_ms: .nan")
    else:
        raw = bundle().model_dump()
        if change == "inactive":
            raw["execution_path"]["enabled_task_ids"].remove("post_crta")
        if change == "cycle":
            raw["pipeline_model"]["edges"].append(
                dict(edge_id="back", source_task_id="post_crta", target_task_id="rt_chain")
            )
        if change == "anchor":
            raw["pipeline_model"]["edges"][0]["source_anchor"] = "start"
        text = "```yaml camera-profile-v1\n" + yaml.safe_dump(raw) + "```\n"
    with pytest.raises(ValueError):
        assemble_camera(parse_markdown(text))


def fake_target(monkeypatch):
    from scenario_db.sim import measured_timing, timeline_adapter, timing_profiles

    monkeypatch.setattr(measured_timing, "baseline_fingerprint", lambda g: "b" * 64)
    monkeypatch.setattr(
        timeline_adapter,
        "timeline_tasks",
        lambda g: [
            dict(id="target_sw", task_type="sw", duration_ms=99),
            dict(id="target_hw", task_type="hw", duration_ms=7),
        ],
    )
    monkeypatch.setattr(
        timeline_adapter,
        "timeline_edges",
        lambda g: [{"from": "target_hw", "to": "target_sw", "latency_ms": 99}],
    )
    monkeypatch.setattr(timing_profiles, "timing_profiles", lambda g: {})
    return SimpleNamespace(
        scenario=SimpleNamespace(project_ref="proj-next"),
        scenario_id="uc-next",
        variant_id="target",
        pipeline_nodes=[{"id": "target_sw"}, {"id": "target_hw"}],
    )


def selection(**kwargs):
    return SwProjectionSelection(
        source_evidence_ref="meas-camera-semantic-example-r1",
        target_project_ref="proj-next",
        target_scenario_ref="uc-next",
        target_variant_ref="target",
        target_path_id="no-gdc",
        assumption_notes="Explicit unchanged SW assumption",
        **kwargs,
    )


def test_projection_only_changes_selected_sw_and_replaces_latency(monkeypatch):
    graph = fake_target(monkeypatch)
    source = evidence()
    original = source.model_dump()
    request = selection(
        task_mapping={"post_crta": "target_sw"},
        edge_mapping={"rt_post": {"source": "target_hw", "target": "target_sw"}},
        runtime_overrides={"post_crta": {"scale": 1.5}},
    )
    projection = build_projection(source, "a" * 64, graph, request)
    tasks = [
        dict(id="target_sw", task_type="sw", duration_ms=99),
        dict(id="target_hw", task_type="hw", duration_ms=7),
    ]
    edges = [{"from": "target_hw", "to": "target_sw", "latency_ms": 99}]
    updated, updated_edges, profiles = apply_projection(graph, projection, tasks, edges, {})
    assert updated[0]["duration_ms"] == pytest.approx(0.3)
    assert updated[1]["duration_ms"] == 7 and tasks[0]["duration_ms"] == 99
    assert updated_edges[0]["latency_ms"] == 0.03 and edges[0]["latency_ms"] == 99
    assert profiles["target_sw"]["value_source"] == "projected"
    assert source.model_dump() == original


@pytest.mark.parametrize(
    "case", ["stage", "hw_target", "negative", "mixed", "included", "stale", "unknown_override"]
)
def test_projection_rejects_unsafe_mapping(monkeypatch, case):
    graph = fake_target(monkeypatch)
    source = evidence()
    kwargs = dict(task_mapping={"post_crta": "target_sw"})
    if case == "stage":
        kwargs["task_mapping"] = {"rt_chain": "target_sw"}
    if case == "hw_target":
        kwargs["task_mapping"] = {"post_crta": "target_hw"}
    if case == "negative":
        kwargs["runtime_overrides"] = {"post_crta": {"delta_ms": -2}}
    if case == "mixed":
        source.pipeline_model.execution_path.mixed_path = True
    if case == "included":
        source.sw_task_timing[0].includes_hw_nodes = ["lme"]
    if case == "unknown_override":
        kwargs["runtime_overrides"] = {"eis": {"scale": 2}}
    if case == "stale":
        graph.scenario.project_ref = "proj-other"
    with pytest.raises(ValueError):
        build_projection(source, "a" * 64, graph, selection(**kwargs))


def test_trace_sequence_is_bounded_and_does_not_aggregate():
    from scenario_db.meas_import.camera_trace import sequence_preview

    item = evidence()
    original = item.model_dump()

    class Trace:
        def query(self, sql):
            if "trace_bounds" in sql:
                return [{"origin": 10**18}]
            if "FROM flow" in sql:
                return [{"slice_out": 1, "slice_in": 2}]
            return [
                dict(slice_id=1, ts_ns=10**18, dur_ns=2_000_000, slice_name="rt_chain", track_id=1),
                dict(
                    slice_id=2,
                    ts_ns=10**18 + 3_000_000,
                    dur_ns=1_000_000,
                    slice_name="post_crta",
                    track_id=2,
                ),
            ]

    rows = sequence_preview(Trace(), item.pipeline_model)
    assert rows[1]["predecessors"] == ["slice:1"] and rows[1]["start_ms"] == 3
    assert item.model_dump() == original
    with pytest.raises(ValueError, match="limit"):
        sequence_preview(Trace(), item.pipeline_model, limit=1)
    with pytest.raises(ValueError):
        sequence_preview(Trace(), item.pipeline_model, window_ms=float("inf"))


def test_stage_span_comparison_preserves_overlap_and_missing_boundary():
    from scenario_db.comparison.camera import compare_camera_stages

    item = evidence().model_dump(mode="json")
    prediction = dict(
        kind="evidence.simulation",
        project_ref=item["project_ref"],
        scenario_ref=item["scenario_ref"],
        variant_ref=item["variant_ref"],
        timeline_events=[
            dict(node_id=node, frame_index=0, start_ms=start, end_ms=end)
            for node, start, end in [("csis", 0, 3), ("pdp", 1, 3), ("byrp", 1, 4), ("rgbp", 2, 5)]
        ],
    )
    result = compare_camera_stages(item, prediction)
    assert result["rows"][0]["predicted_mean_ms"] == 5  # span, not 11 ms sum
    assert result["validated"] is False
    prediction["timeline_events"].pop()
    assert compare_camera_stages(item, prediction)["rows"][0]["predicted_mean_ms"] is None
    prediction["run_info"] = {"timing_profile": {"task_runtime": {"csis": {}}}}
    with pytest.raises(ValueError):
        compare_camera_stages(item, prediction)
    prediction["scenario_ref"] = "uc-other"
    with pytest.raises(ValueError):
        compare_camera_stages(item, prediction)


@pytest.mark.parametrize("optional", [("eis", "gdc"), ("lme", "dof"), ("eis",), ("gdc",)])
def test_absent_stages_are_not_zero_measurements(optional):
    from scenario_db.models.evidence.camera import CameraPipeline

    raw = evidence().pipeline_model.model_dump()
    # Keep just one selected SW task; optional tasks may be absent entirely.
    raw["tasks"] = [t for t in raw["tasks"] if t["task_id"] == "post_crta"]
    raw["edges"] = []
    raw["execution_path"]["enabled_task_ids"] = ["post_crta"]
    raw["execution_path"]["disabled_tasks"] = [
        {"task_id": t, "reason": "path bypass"} for t in optional
    ]
    parsed = CameraPipeline.model_validate(raw)
    assert len(parsed.tasks) == 1
    assert not (set(optional) & set(parsed.execution_path.enabled_task_ids))


def test_conflicting_declared_sw_scope_and_invalid_yaml_fail():
    from scenario_db.meas_import.camera import CameraBundle

    raw = bundle().model_dump()
    raw["statistics"]["sw_task_timing"][0]["timing_scope"] = "inclusive_stage"
    with pytest.raises(ValueError, match="scope"):
        assemble_camera(CameraBundle.model_validate(raw))
    with pytest.raises(ValueError):
        parse_markdown("```yaml camera-profile-v1\n- [broken\n```")
    with pytest.raises(ValueError):
        parse_markdown("```yaml camera-profile-v1\n? [a, b]\n: x\n```")
