"""Baseline trace regeneration must preserve causal edges and physical resources."""
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from scripts import generate_baseline_evidence as generator

DB = Path(__file__).resolve().parents[3] / "db_Exynos2600_SM-S947B" / "03_evidence"


@pytest.mark.parametrize("variant,fps", [
    ("cam-rec-r1-uhd30-vdis", 30), ("cam-rec-r1-8k30-psm", 30), ("cam-rec-f1-uhd60", 60),
])
def test_checked_in_baseline_trace_is_reproducible_causal_and_serialized(variant, fps):
    sim = yaml.safe_load((DB / f"sim-baseline-{variant}-mean-20261004.yaml").read_text(encoding="utf-8"))
    measured = yaml.safe_load((DB / f"meas-synth-baseline-{variant}-evt1-20261004.yaml").read_text(encoding="utf-8"))
    before = deepcopy(sim)
    trace = generator.measured_trace(sim, variant, fps)
    assert sim == before
    assert trace == measured["timeline_events"]
    assert generator.sw_timing_from_trace(trace, fps) == measured["sw_task_timing"]
    source_frames = defaultdict(list)
    for event in sim["timeline_events"]:
        source_frames[event["frame_index"]].append(event)
    frames = sorted(source_frames)
    frames = frames[1:] if len(frames) > 2 else frames
    by_id = {e["task_id"]: e for e in trace}
    assert len(by_id) == len(trace)
    resources = defaultdict(list)
    for event in trace:
        assert event["end_ms"] > event["start_ms"]
        source = {e["node_id"]: e for e in source_frames[frames[event["frame_index"] % len(frames)]]}
        original = source[event["node_id"]]
        for predecessor in event.get("predecessors", []):
            parent = by_id[predecessor]
            old_parent = source[parent["node_id"]]
            if original["start_ms"] >= old_parent["end_ms"] - 1e-6:
                assert event["start_ms"] + 1e-4 >= parent["end_ms"]
            else:
                assert event["start_ms"] + 1e-4 >= parent["start_ms"]
                assert event["end_ms"] + 1e-4 >= parent["end_ms"]
        if event["node_id"].startswith("sensor"):
            assert event["start_ms"] == pytest.approx(event["frame_index"] * 1000 / fps, abs=1e-4)
        resources[event.get("resource_id") or event["node_id"]].append(event)
    for events in resources.values():
        events.sort(key=lambda e: e["start_ms"])
        assert all(a["end_ms"] <= b["start_ms"] + 1e-4 for a, b in zip(events, events[1:]))
