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

