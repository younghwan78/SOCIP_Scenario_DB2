from pathlib import Path
from types import SimpleNamespace

import pytest

from scenario_db.meas_import.camera import assemble_camera, parse_markdown
from scenario_db.meas_import.camera_scenario_trace import logical_name, summarize
from scenario_db.meas_import.camera_trace import sequence_preview
from scenario_db.meas_import.perfetto_digest import PerfettoTraceProcessor
from scenario_db.models.evidence.camera import CameraTask

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "examples/measurement-import/camera/uhd30-eis"


def test_exact_extensible_mapping():
    task = CameraTask(task_id="future_task", label="New vendor task", kind="sw",
                      stage="eis", timing_scope="exclusive_sw", observation_only=True,
                      trace_slice_name="~NEW_TASK", trace_track_name="Scenario / SW / NEW")
    row = dict(slice_name="~NEW_TASK f0042", track_name="Scenario / SW / NEW")
    assert logical_name(row, [task]) == "future_task"
    assert logical_name({**row, "track_name": "unrelated"}, [task]) is None
    assert logical_name({**row, "slice_name": "~NEW_TASK f42_extra"}, [task]) is None
    with pytest.raises(ValueError, match="ambiguous"):
        logical_name(row, [task, task.model_copy(update={"task_id": "other"})])


def test_missing_duplicate_incomplete_and_extra_events():
    template = parse_markdown((BUNDLE / "mapping-template.md").read_text(encoding="utf-8"))
    template.pipeline_model["tasks"] = [template.pipeline_model["tasks"][7]]
    template.pipeline_model["edges"] = []
    template.execution_path.enabled_task_ids = ["crta_3a"]
    rows = [dict(slice_name="~CRTA_3A f0001", track_name="Scenario / SW / ICPU", dur_ns=300_000)]
    tp = SimpleNamespace(query=lambda sql: [dict(start_ts=0, end_ts=15_000_000_000)] if "trace_bounds" in sql else rows)
    _, report = summarize(tp, template)
    assert report["samples_by_task"] == {"crta_3a": 1}
    rows.append(dict(slice_name="extra", track_name="unknown", dur_ns=1))
    rows.append({**rows[0], "slice_name": "~CRTA_3A f0002", "dur_ns": -1})
    _, report = summarize(tp, template)
    assert report["ignored_slices"] == report["incomplete_slices"] == 1
    rows.append(rows[0])
    with pytest.raises(ValueError, match="duplicate"):
        summarize(tp, template)
    rows.clear()
    with pytest.raises(ValueError, match="no complete samples"):
        summarize(tp, template)


def test_real_fixture_stats_hierarchy_and_timeline():
    pytest.importorskip("perfetto")
    template = parse_markdown((BUNDLE / "mapping-template.md").read_text(encoding="utf-8"))
    tp = PerfettoTraceProcessor(str(BUNDLE / "uhd30-eis-15s.pftrace"))
    try:
        bundle, report = summarize(tp, template)
        evidence = assemble_camera(bundle)
        assert report["duration_ms"] == 15000
        assert len(report["samples_by_task"]) == 19
        assert report["samples_by_task"]["gdc_o"] == 449
        assert all(count == 450 for task, count in report["samples_by_task"].items() if task != "gdc_o")
        assert report["incomplete_slices"] == 1
        assert report["ignored_slices"] == 3
        assert len(evidence.sw_task_timing) == 5
        assert len(evidence.hw_task_timing) == 14
        stats = {s.task: s for s in [*evidence.sw_task_timing, *evidence.hw_task_timing]}
        for task, typical in {"sensor_readout": 11.8, "pre_me_rta": 4,
                              "eis": 3.2, "mtnr": 8, "msnr": 8, "yuvp": 8,
                              "mcsc": 8, "gdc_m": 2.3, "gdc_o": 8.6}.items():
            assert stats[task].mean_ms == pytest.approx(typical, abs=.001)
            assert stats[task].min_ms == pytest.approx(typical * .98)
            assert stats[task].max_ms == pytest.approx(typical * 1.02)
        eis = next(s for s in evidence.sw_task_timing if s.task == "eis")
        assert (eis.min_ms, eis.mean_ms, eis.max_ms) == pytest.approx((3.136, 3.2, 3.264))
        events = sequence_preview(tp, evidence.pipeline_model)
        assert len(events) == 56
        assert {e["frame_index"] for e in events} == {0, 1, 2}
        assert sum(len(e["predecessors"]) for e in events) == 18 * 3 - 1
        by_id = {e["event_id"]: e for e in events}
        assert all(by_id[p]["frame_index"] == e["frame_index"]
                   for e in events for p in e["predecessors"])
        flows = tp.query("SELECT s.name AS source, t.name AS target FROM flow f "
                         "JOIN slice s ON s.id=f.slice_out JOIN slice t ON t.id=f.slice_in")
        assert len(flows) == 18 * 450
        for frame in range(450):
            suffix = f" f{frame:04d}"
            pairs = [(f["source"], f["target"]) for f in flows if f["source"].endswith(suffix)]
            assert len(pairs) == 18
            assert all(target.endswith(suffix) for _, target in pairs)
            reached = {"SENSOR_READOUT" + suffix}
            for _ in range(19):
                reached.update(target for source, target in pairs if source in reached)
            assert len(reached) == 19
            assert "~GDC_WARP_PREVIEW" + suffix in reached
            assert "~GDC_WARP_VIDEO" + suffix in reached
        nrt = tp.query("SELECT name, ts, dur FROM slice WHERE name GLOB 'MTNR_PROCESS f*' "
                       "OR name GLOB 'MSNR_PROCESS f*' OR name GLOB 'YUVP_PROCESS f*' "
                       "OR name GLOB 'MCSC_PROCESS f*'")
        assert len(nrt) == 4 * 450
        assert sum(s["dur"] for s in nrt) / len(nrt) / 1e6 == pytest.approx(8)
        for frame in range(450):
            assert len({(s["ts"], s["dur"]) for s in nrt
                        if s["name"].endswith(f" f{frame:04d}")}) == 1
        assert any(e["observation_only"] for e in events)
        tracks = tp.query("SELECT t.name, p.name AS parent FROM track t JOIN track p ON t.parent_id=p.id")
        assert any(t["name"] == "Scenario / SW / ICPU" and t["parent"] == "Scenario / SW" for t in tracks)
    finally:
        tp.close()


def test_fixture_explicit_track_order():
    proto = pytest.importorskip("perfetto.protos.perfetto.trace.perfetto_trace_pb2")
    trace = proto.Trace.FromString((BUNDLE / "uhd30-eis-15s.pftrace").read_bytes())
    descriptors = [p.track_descriptor for p in trace.packet if p.HasField("track_descriptor")]
    by_name = {d.name: d for d in descriptors}
    expected = {
        "Scenario": ["SW", "SENSOR", "RT", "NRT", "M2M"],
        "Scenario / SW": ["HAL_RT", "ICPU", "CAM_DRIVER"],
        "Scenario / SENSOR": ["SENSOR"],
        "Scenario / RT": ["CSI", "PDP", "BYRP", "RGBP", "YUVSC", "MLSC"],
        "Scenario / NRT": ["MTNR", "MSNR", "YUVP", "MCSC"],
        "Scenario / M2M": ["LME", "GDC_M", "GDC_O", "VPS"],
    }
    for parent, children in expected.items():
        assert by_name[parent].child_ordering == proto.TrackDescriptor.EXPLICIT
        actual = sorted((d for d in descriptors if d.parent_uuid == by_name[parent].uuid),
                        key=lambda d: d.sibling_order_rank)
        assert [d.name for d in actual] == [f"{parent} / {child}" for child in children]


def test_exynos2600_fixture_binding_and_min_mean_max_exploration():
    from scenario_db.meas_import.camera import bind_graph, canonical_hash
    from scenario_db.sim.sw_projection import SwProjectionSelection, build_projection
    from scenario_db.sim.scenario_exploration import ScenarioExplorationRequest, preview_scenario
    from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

    evidence = assemble_camera(parse_markdown(
        (BUNDLE / "scenario-statistics.md").read_text(encoding="utf-8")))
    graph = _exynos2600_generated_graph("uc-camera-recording", "cam-rec-r1-uhd30-vdis")
    bind_graph(evidence, graph)
    for statistic in ("min", "mean", "max"):
        selection = SwProjectionSelection(
            source_evidence_ref=str(evidence.id), target_project_ref=str(evidence.project_ref),
            target_scenario_ref=str(evidence.scenario_ref), target_variant_ref=str(evidence.variant_ref),
            target_path_id="uhd30-eis-lme", task_mapping={"eis": "eis"},
            statistic=statistic, assumption_notes="Synthetic fixture validation")
        projection = build_projection(evidence, canonical_hash(evidence), graph, selection)
        request = ScenarioExplorationRequest(
            project_ref=str(evidence.project_ref), scenario_id=str(evidence.scenario_ref),
            variant_id=str(evidence.variant_ref),
            axes=[dict(target="node_clock_mhz", node_id="gdc_m", values=[300, 400])],
            config=dict(sw_timing_projection=projection, include_timeline=True, timeline_frame_count=2))
        report = preview_scenario(graph, request)
        assert len(report["cases"]) == 3
        assert report["persisted"] is False
    with pytest.raises(ValueError, match="exclusive SW"):
        build_projection(evidence, canonical_hash(evidence), graph,
                         selection.model_copy(update={"task_mapping": {"crta_3a": "post_crta"}}))
