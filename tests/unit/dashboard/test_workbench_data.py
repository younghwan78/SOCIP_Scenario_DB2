"""Unit tests for the Scenario Workbench payload/selection helpers."""
from __future__ import annotations

import pytest

from dashboard.components.workbench_data import (
    DEFAULT_FRAME_INTERVAL_MS,
    build_component_args,
    build_graph_payload,
    derive_frame_interval_ms,
    filter_events_by_range,
    normalize_selection,
)

pytestmark = pytest.mark.unit


def make_event(**overrides):
    event = {"task_id": "task", "start_ms": 0.0, "end_ms": 1.0, "duration_ms": 1.0}
    event.update(overrides)
    return event


class TestDeriveFrameInterval:
    def test_prefers_source_fps(self):
        events = [make_event(source_fps=30)]
        assert derive_frame_interval_ms(events) == pytest.approx(1000.0 / 30.0)

    def test_falls_back_to_median_frame_spacing(self):
        events = [
            make_event(frame_index=0, start_ms=0.0),
            make_event(frame_index=0, start_ms=5.0),
            make_event(frame_index=1, start_ms=33.0),
            make_event(frame_index=2, start_ms=66.0),
        ]
        assert derive_frame_interval_ms(events) == pytest.approx(33.0)

    def test_defaults_without_frame_data(self):
        assert derive_frame_interval_ms([make_event()]) == pytest.approx(DEFAULT_FRAME_INTERVAL_MS)


class TestBuildComponentArgs:
    def test_shapes_args_for_the_component(self):
        events = [make_event(source_fps=60), "not-a-dict"]
        args = build_component_args(events, show_waits=False, show_deadlines=True, theme="dark")
        assert args["events"] == [events[0]]
        assert args["options"] == {
            "showWaits": False,
            "showDeadlines": True,
            "theme": "dark",
            "frameIntervalMs": pytest.approx(1000.0 / 60.0),
        }

    def test_rejects_unknown_theme(self):
        args = build_component_args([], theme="neon")
        assert args["options"]["theme"] == "light"

    def test_sanitizes_export_name(self):
        args = build_component_args([], export_name="timeline evid/1:bad")
        assert args["exportName"] == "timeline_evid_1_bad"
        assert build_component_args([], export_name="///")["exportName"] == "___"
        assert build_component_args([])["exportName"] == "timeline"


class TestBuildGraphPayload:
    VIEW = {
        "nodes": [
            {"data": {"id": "csis0", "label": "CSIS0", "type": "ip", "layer": "hw"}},
            {"data": {"id": "buf-rec", "label": "Record Buf", "type": "buffer", "layer": "memory"}},
            {"data": {"id": "lane-1", "label": "", "type": "lane_bg", "layer": "meta"}},
        ],
        "edges": [
            {"data": {"id": "e1", "source": "csis0", "target": "buf-rec", "flow_type": "M2M"}},
            {"data": {"id": "e2", "source": "csis0", "target": "ghost", "flow_type": "OTF"}},
        ],
    }

    def test_slims_nodes_and_drops_layout_and_dangling(self):
        graph = build_graph_payload(self.VIEW)
        assert [node["id"] for node in graph["nodes"]] == ["csis0", "buf-rec"]
        assert graph["edges"] == [{"id": "e1", "source": "csis0", "target": "buf-rec", "flow_type": "M2M"}]

    def test_returns_none_for_empty_or_invalid(self):
        assert build_graph_payload(None) is None
        assert build_graph_payload({"nodes": []}) is None


class TestFilterEventsByRange:
    def test_keeps_intersecting_events_only(self):
        events = [
            make_event(task_id="a", start_ms=0.0, end_ms=10.0),
            make_event(task_id="b", start_ms=5.0, end_ms=15.0),
            make_event(task_id="c", start_ms=20.0, end_ms=30.0),
        ]
        hits = filter_events_by_range(events, 4.0, 6.0)
        assert [event["task_id"] for event in hits] == ["a", "b"]

    def test_touching_endpoints_are_exclusive(self):
        events = [make_event(task_id="a", start_ms=0.0, end_ms=10.0)]
        assert filter_events_by_range(events, 10.0, 12.0) == []

    def test_normalizes_reversed_range(self):
        events = [make_event(task_id="a", start_ms=0.0, end_ms=10.0)]
        assert filter_events_by_range(events, 6.0, 4.0) == events

    def test_uses_duration_when_end_missing(self):
        events = [make_event(task_id="a", start_ms=0.0, end_ms=None, duration_ms=8.0)]
        assert filter_events_by_range(events, 7.0, 9.0) == events


class TestNormalizeSelection:
    def test_none_for_empty_or_invalid(self):
        assert normalize_selection(None) is None
        assert normalize_selection("x") is None
        assert normalize_selection({"selectedTaskId": None, "rangeStartMs": None, "rangeEndMs": None}) is None

    def test_normalizes_task_and_range(self):
        raw = {
            "selectedTaskId": "isp#f1",
            "rangeStartMs": 4.5,
            "rangeEndMs": 9,
            "rangeStats": {"eventCount": 3},
        }
        assert normalize_selection(raw) == {
            "selected_task_id": "isp#f1",
            "range_start_ms": 4.5,
            "range_end_ms": 9.0,
            "range_stats": {"eventCount": 3},
        }

    def test_half_open_range_is_dropped(self):
        raw = {"selectedTaskId": "isp", "rangeStartMs": 4.5, "rangeEndMs": None}
        normalized = normalize_selection(raw)
        assert normalized is not None
        assert normalized["range_start_ms"] is None
        assert normalized["range_end_ms"] is None
