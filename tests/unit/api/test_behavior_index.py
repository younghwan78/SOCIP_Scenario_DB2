from __future__ import annotations

from types import SimpleNamespace

from scenario_db.api.routers.behavior import behavior_index


def _ev(id_, scenario, variant, at, events=None, flows=None):
    return SimpleNamespace(id=id_, scenario_ref=scenario, variant_ref=variant, measured_at=at, timeline_events=events,
                           handoff_flows={"format": "sdb.handoff/1", "flows": flows} if flows is not None else None)


def test_index_keeps_variants_with_layered_events_or_flows_newest_first():
    rows = [
        _ev("old", "uc-cam", "r1", "2026-10-01", events=[{"task_id": "a", "layer": "hal"}]),
        _ev("new", "uc-cam", "r1", "2026-10-31", flows=[{"id": "f1"}, {"id": "f2"}]),
        _ev("pipe", "uc-cam", "r2", "2026-10-31", events=[{"task_id": "isp", "node_id": "csis"}]),   # pipeline trace: no layer
        _ev("yt", "uc-yt", "v1", "2026-10-31", events=[{"task_id": "x", "layer": "app"}], flows=[{"id": "frame"}]),
    ]
    assert behavior_index(rows) == [
        {"scenario_ref": "uc-cam", "variant_ref": "r1", "evidence_ids": ["new", "old"], "full_stack": True, "flows": 2},
        {"scenario_ref": "uc-yt", "variant_ref": "v1", "evidence_ids": ["yt"], "full_stack": True, "flows": 1},
    ]
