from __future__ import annotations

import pytest


pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.sim.timeline import build_timeline_events


def test_build_timeline_events_includes_sw_task_precedence():
    events = build_timeline_events(
        tasks=[
            {"id": "t_isp", "node_id": "isp0", "hw_name": "ISP", "task_type": "hw", "duration_ms": 2.0},
            {"id": "t_codec2", "node_id": "codec2", "hw_name": "CPU", "task_type": "sw", "duration_ms": 4.0},
            {"id": "t_mfc", "node_id": "mfc", "hw_name": "MFC", "task_type": "hw", "duration_ms": 3.0},
        ],
        edges=[
            {"from": "t_isp", "to": "t_codec2"},
            {"from": "t_codec2", "to": "t_mfc"},
        ],
    )

    by_task = {event.task_id: event for event in events}
    assert by_task["t_isp"].start_ms == 0.0
    assert by_task["t_codec2"].start_ms == 2.0
    assert by_task["t_codec2"].task_type == "sw"
    assert by_task["t_mfc"].start_ms == 6.0
    assert by_task["t_mfc"].end_ms == 9.0


def test_timeline_serializes_tasks_on_same_resource():
    events = build_timeline_events(
        tasks=[
            {"id": "a", "hw_name": "ISP", "task_type": "hw", "duration_ms": 3.0},
            {"id": "b", "hw_name": "ISP", "task_type": "hw", "duration_ms": 2.0},
        ],
        edges=[],
    )

    by_task = {event.task_id: event for event in events}
    assert by_task["a"].start_ms == 0.0
    assert by_task["b"].start_ms == 3.0
    assert by_task["b"].resource_wait_ms == 3.0
    assert by_task["b"].resource_id == "ISP"


def test_timeline_models_m2m_token_transfer_delay():
    events = build_timeline_events(
        tasks=[
            {"id": "producer", "hw_name": "ISP", "task_type": "hw", "duration_ms": 2.0},
            {"id": "consumer", "hw_name": "MFC", "task_type": "hw", "duration_ms": 3.0},
        ],
        edges=[
            {
                "from": "producer",
                "to": "consumer",
                "type": "M2M",
                "buffer": "record",
                "transfer_ms": 1.5,
            }
        ],
    )

    by_task = {event.task_id: event for event in events}
    assert by_task["consumer"].ready_ms == 3.5
    assert by_task["consumer"].start_ms == 3.5
    assert by_task["consumer"].token_wait_ms == 0.0


def test_timeline_serializes_shared_m2m_token_queue():
    events = build_timeline_events(
        tasks=[
            {"id": "p0", "hw_name": "ISP0", "task_type": "hw", "duration_ms": 1.0},
            {"id": "p1", "hw_name": "ISP1", "task_type": "hw", "duration_ms": 1.0},
            {"id": "c0", "hw_name": "MFC0", "task_type": "hw", "duration_ms": 1.0},
            {"id": "c1", "hw_name": "MFC1", "task_type": "hw", "duration_ms": 1.0},
        ],
        edges=[
            {"from": "p0", "to": "c0", "type": "M2M", "transfer_ms": 3.0, "token_resource": "record-bus"},
            {"from": "p1", "to": "c1", "type": "M2M", "transfer_ms": 3.0, "token_resource": "record-bus"},
        ],
    )

    waits = sorted(event.token_wait_ms for event in events if event.task_id in {"c0", "c1"})
    starts = sorted(event.start_ms for event in events if event.task_id in {"c0", "c1"})
    assert waits == [0.0, 3.0]
    assert starts == [4.0, 7.0]


def test_timeline_expands_multiple_frames_with_release_period():
    events = build_timeline_events(
        tasks=[
            {"id": "isp", "hw_name": "ISP", "task_type": "hw", "duration_ms": 4.0},
            {"id": "mfc", "hw_name": "MFC", "task_type": "hw", "duration_ms": 2.0},
        ],
        edges=[{"from": "isp", "to": "mfc"}],
        frame_count=2,
        frame_period_ms=10.0,
    )

    by_task = {event.task_id: event for event in events}
    assert by_task["isp#f0"].frame_index == 0
    assert by_task["isp#f1"].frame_index == 1
    assert by_task["isp#f1"].start_ms == 10.0
    assert by_task["mfc#f1"].start_ms == 14.0


def test_timeline_marks_critical_path():
    events = build_timeline_events(
        tasks=[
            {"id": "short", "hw_name": "A", "task_type": "hw", "duration_ms": 1.0},
            {"id": "long", "hw_name": "B", "task_type": "hw", "duration_ms": 5.0},
            {"id": "join", "hw_name": "C", "task_type": "hw", "duration_ms": 2.0},
        ],
        edges=[
            {"from": "short", "to": "join"},
            {"from": "long", "to": "join"},
        ],
    )

    critical = [event.task_id for event in events if event.critical]
    assert critical == ["long", "join"]
    assert [event.critical_path_rank for event in events if event.critical] == [0, 1]
