from __future__ import annotations

from dashboard.components.timing_chart import (
    timeline_chart_color,
    timeline_frame_outputs,
    timeline_legend_name,
)


def test_timing_chart_frame_outputs_use_source_to_sink_latency_and_intervals():
    events = [
        {"task_id": "sensor#f0", "constraint_type": "source", "frame_index": 0, "start_ms": 0.0, "end_ms": 18.0},
        {"task_id": "dpu#f0", "constraint_type": "sink", "frame_index": 0, "start_ms": 20.0, "end_ms": 26.0},
        {"task_id": "sensor#f1", "constraint_type": "source", "frame_index": 1, "start_ms": 33.333, "end_ms": 51.0},
        {"task_id": "dpu#f1", "constraint_type": "sink", "frame_index": 1, "start_ms": 58.0, "end_ms": 66.0},
    ]

    outputs = timeline_frame_outputs(events)

    assert [item["frame_index"] for item in outputs] == [0, 1]
    assert outputs[0]["latency_ms"] == 26.0
    assert round(outputs[1]["output_ms"] - outputs[0]["output_ms"], 3) == 40.0
    assert outputs[1]["output_task"] == "dpu#f1"


def test_timing_chart_groups_otf_m2m_sw_and_constraints_by_legend():
    assert timeline_legend_name({"constraint_type": "source"}) == "Sensor In"
    assert timeline_legend_name({"constraint_type": "sink"}) == "Display Out"
    assert timeline_legend_name({"task_type": "sw_task", "resource_id": "CPU"}) == "SW"
    assert timeline_legend_name({"edge_type": "OTF", "otf_group_id": "otf0#f1"}) == "OTF otf0"
    assert timeline_legend_name({"edge_type": "M2M", "resource_id": "MCSC"}) == "M2M MCSC"

    assert timeline_chart_color({"constraint_type": "source"}) == "#22C55E"
    assert timeline_chart_color({"constraint_type": "sink"}) == "#0EA5E9"
    assert timeline_chart_color({"edge_type": "OTF", "otf_group_id": "otf0#f1", "task_id": "byrp"}) != "#64748B"
    assert timeline_chart_color({"edge_type": "M2M", "resource_id": "MCSC", "task_id": "mcsc"}) != "#64748B"
