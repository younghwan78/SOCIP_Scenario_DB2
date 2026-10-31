from __future__ import annotations

import pytest

from scenario_db.meas_import.fullstack import SQL_BOUNDS, SQL_FLOWS, SQL_FULLSTACK_SLICES, evidence, extract
from scenario_db.models.evidence.measurement import MeasurementEvidence

MS = 1_000_000


def _row(sid, ts_ms, dur_ms, task=None, layer=None, frame=None, node=None, handoff=None, process="p", thread="t"):
    return {"slice_id": sid, "ts_ns": int(1000 * MS + ts_ms * MS), "dur_ns": int(dur_ms * MS), "slice_name": task or "noise",
            "track_name": thread, "thread_name": thread, "process_name": process, "sdb_task": task, "sdb_layer": layer,
            "sdb_frame": frame, "sdb_node": node, "sdb_handoff": handoff}


class FakeTrace:
    def __init__(self, rows, flows):
        self.rows, self.flows = rows, flows

    def query(self, sql):
        if sql == SQL_BOUNDS:
            return [{"start_ts": 1000 * MS, "end_ts": 1000 * MS + 1000 * MS}]
        if sql == SQL_FULLSTACK_SLICES:
            return self.rows
        if sql == SQL_FLOWS:
            return [{"slice_out": a, "slice_in": b} for a, b in self.flows]
        raise AssertionError(sql)


def _trace():
    rows = [
        _row(1, 0.0, 2.3, "hal.request", "hal", 4, process="camera.provider", thread="request"),
        _row(2, 1.0, 10.2, "sensor.readout", "hw", 0, "sensor_rear", "kick", process="Sensor", thread="readout"),
        _row(3, 12.0, 7.8, "eis.warp", "hal", 0, "eis", "complete", process="camera.provider", thread="VDISCore"),
        _row(4, 3.0, 0.8, "abox.dsp", "hw", node="abox", process="ABOX", thread="capture"),
        _row(5, 23.0, 0.8, "abox.dsp", "hw", node="abox", process="ABOX", thread="capture"),
        _row(6, 43.0, 0.8, "abox.dsp", "hw", node="abox", process="ABOX", thread="capture"),
        _row(7, 5.0, 1.0),                                  # no sdb.task: counted, skipped
        _row(8, 500.0, 7.5, "eis.warp", "hal", 15, "eis"),  # outside the window
    ]
    return FakeTrace(rows, flows=[(2, 3), (7, 3), (8, 3)])


def test_window_events_follow_the_common_name_contract():
    events, report = extract(_trace(), window_ms=100.0)
    by = {e["task_id"]: e for e in events}
    assert sorted(by) == ["abox.dsp#c0", "abox.dsp#c1", "abox.dsp#c2", "eis.warp#f0", "hal.request#f4", "sensor.readout#f0"]
    eis = by["eis.warp#f0"]
    assert eis["logical_task_id"] == "eis.warp" and eis["layer"] == "hal" and eis["node_id"] == "eis"
    assert eis["resource_name"] == "fullstack/HAL/camera.provider · VDISCore"
    assert eis["start_ms"] == pytest.approx(12.0) and eis["duration_ms"] == pytest.approx(7.8)
    # only flows between named slices inside the window become predecessors
    assert eis["predecessors"] == ["sensor.readout#f0"] and eis["handoff"] == "complete"
    abox = by["abox.dsp#c1"]
    assert abox["frame_index"] is None and abox["cadence_period_ms"] == pytest.approx(20.0) and abox["task_type"] == "hw"
    assert "cadence_period_ms" not in eis
    assert report["skipped_unnamed_slices"] == 1 and report["named_slices"] == 7 and report["window_events"] == 6


def test_layer_and_handoff_are_validated():
    bad = FakeTrace([_row(1, 0.0, 1.0, "x", "driver")], [])
    with pytest.raises(ValueError, match="sdb.layer"):
        extract(bad)
    bad = FakeTrace([_row(1, 0.0, 1.0, "x", "hal", handoff="wake")], [])
    with pytest.raises(ValueError, match="sdb.handoff"):
        extract(bad)


def test_evidence_document_validates_and_records_the_trace_artifact():
    events, _ = extract(_trace(), window_ms=100.0)
    doc = evidence(events, evidence_id="meas-fullstack-test", scenario="uc-cam-recording-e2600", variant="cam-rec-r1-uhd30-vdis",
                   project="proj-sm-s947b", measured_at="2026-10-31T10:00:00+09:00", silicon_rev="EVT1",
                   sw_baseline_ref="sw-vendor-v1.2.3", trace_path="t.pftrace", trace_sha256="0" * 64, window_ms=100.0)
    model = MeasurementEvidence.model_validate(doc)
    assert model.provenance.raw_artifacts[0].type == "perfetto.fullstack"
    assert len(model.timeline_events) == 6
