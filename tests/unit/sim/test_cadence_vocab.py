"""D-04: the hand-off cadence vocabulary as the simulation task model, each own cadence judged by its own deadline."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scenario_db.sim.timeline import build_timeline_events
from scenario_db.sim.timeline_adapter import CADENCE_KINDS, _apply_cadence, _resolve_vsync, own_cadence
from scenario_db.sim.timing_budget import _verdict, own_cadence_rows

P = 100.0 / 3  # 30 fps frame period


def _task(node="t", **timeline):
    task = {"id": node, "node_id": node, "duration_ms": 0.0}
    _apply_cadence(task, {"timeline": timeline})
    return task


def test_the_vocabulary_is_the_handoff_one():
    assert CADENCE_KINDS == ("frame", "period", "chunk", "vsync", "divided", "event")


def test_a_period_without_cadence_keeps_its_previous_meaning():
    # the ABOX entries authored before: an own period outside the frame DAG, not judged
    task = _task(period_ms=10.0, duration_ms=0.6)
    assert task == {"id": "t", "node_id": "t", "duration_ms": 0.6, "independent_period_ms": 10.0}
    assert own_cadence(task) and "deadline_ms" not in task and "cadence" not in task
    assert _task() == {"id": "t", "node_id": "t", "duration_ms": 0.0}


@pytest.mark.parametrize("timeline, expected", [
    ({"cadence": "frame"}, {}),
    ({"cadence": "period", "period_ms": 10.0}, {"cadence": "period", "independent_period_ms": 10.0, "deadline_ms": 10.0}),
    ({"cadence": "chunk", "period_ms": 500.0, "deadline_ms": 40.0},
     {"cadence": "chunk", "independent_period_ms": 500.0, "deadline_ms": 40.0}),
    ({"cadence": "vsync", "refresh_hz": 120}, {"cadence": "vsync", "independent_period_ms": 1000 / 120, "deadline_ms": 1000 / 120}),
    ({"cadence": "divided", "every": 5}, {"cadence": "divided", "independent_every": 5}),
    ({"cadence": "event", "phase_ms": 12.0, "deadline_ms": 30.0},
     {"cadence": "event", "independent_once": True, "independent_phase_ms": 12.0, "deadline_ms": 30.0}),
    ({"cadence": "event"}, {"cadence": "event", "independent_once": True}),
])
def test_each_kind_becomes_a_release_rule_and_a_deadline(timeline, expected):
    task = _task(**timeline)
    assert {k: v for k, v in task.items() if k not in ("id", "node_id", "duration_ms")} == pytest.approx(expected)


@pytest.mark.parametrize("timeline, message", [
    ({"cadence": "beat"}, "not one of"),
    ({"cadence": "period"}, "needs period_ms"),
    ({"cadence": "chunk", "period_ms": 0}, "needs period_ms"),
    ({"cadence": "divided", "every": 1}, "every >= 2"),
    ({"cadence": "period", "period_ms": 10, "deadline_ms": 0}, "deadline_ms must be > 0"),
])
def test_bad_declarations_are_refused(timeline, message):
    with pytest.raises(ValueError, match=message):
        _task(**timeline)


def test_vsync_takes_the_panel_refresh_when_it_names_none():
    tasks = [_task("vs", cadence="vsync"), {"id": "panel", "refresh_hz": 60.0}]
    _resolve_vsync(tasks)
    assert tasks[0]["independent_period_ms"] == pytest.approx(1000 / 60) and tasks[0]["deadline_ms"] == pytest.approx(1000 / 60)
    with pytest.raises(ValueError, match="needs refresh_hz"):
        _resolve_vsync([_task("vs", cadence="vsync")])


def _events(*own):
    return build_timeline_events(
        tasks=[{"id": "isp", "node_id": "isp", "duration_ms": 10.0, "resource_id": "isp"},
               {"id": "mfc", "node_id": "mfc", "duration_ms": 8.0}, *own],
        edges=[{"from": "isp", "to": "mfc", "type": "M2M"}],
        frame_count=3, frame_period_ms=P, critical_budget_ms=P,
    )


def test_divided_and_event_cadences_release_outside_the_frame_dag():
    events = _events({**_task("m2m", cadence="divided", every=2), "duration_ms": 4.0},
                     {**_task("cap", cadence="event", phase_ms=5.0, deadline_ms=3.0), "duration_ms": 1.0})
    m2m = [e for e in events if e.node_id == "m2m"]
    assert [e.start_ms for e in m2m] == pytest.approx([0.0, 2 * P])  # every 2nd frame over 3 frames
    assert all(e.frame_index is None and e.cadence == "divided" and e.independent_period_ms == pytest.approx(2 * P) for e in m2m)
    assert all(e.deadline_ms - e.ready_ms == pytest.approx(2 * P) for e in m2m)  # deadline = its own period
    cap = [e for e in events if e.node_id == "cap"]
    assert len(cap) == 1 and cap[0].start_ms == pytest.approx(5.0) and cap[0].cadence == "event"
    # the frame tasks are unchanged and carry no cadence
    assert all("cadence" not in e.model_dump() for e in events if e.frame_index is not None)
    assert len([e for e in events if e.frame_index is not None]) == 6


def test_an_own_cadence_is_judged_by_its_own_deadline():
    # a 10 ms loop sharing the ISP's resource waits behind it: the response exceeds its 10 ms deadline
    # (released 0.5 ms after the frame: the ISP holds the resource until 10 ms, so the first loop ends at 11 ms)
    loop = {**_task("loop", cadence="period", period_ms=10.0, phase_ms=0.5), "duration_ms": 1.0, "resource_id": "isp"}
    rows = own_cadence_rows(_events(loop))
    assert rows == [{"node": "loop", "cadence": "period", "period_ms": 10.0, "deadline_ms": 10.0, "releases": 10,
                     "worst_response_ms": pytest.approx(10.5, abs=0.01), "worst_slack_ms": pytest.approx(-0.5, abs=0.01), "ok": False}]
    fine = own_cadence_rows(_events({**_task("loop", cadence="period", period_ms=10.0), "duration_ms": 1.0}))
    assert fine[0]["ok"] is True and fine[0]["worst_response_ms"] == pytest.approx(1.0)
    # an undeclared own period is still not judged
    assert own_cadence_rows(_events({"id": "abox", "node_id": "abox", "duration_ms": 0.6, "independent_period_ms": 10.0})) == []
    # an event without a deadline is reported, not judged
    event = own_cadence_rows(_events({**_task("cap", cadence="event"), "duration_ms": 1.0}))
    assert event[0]["ok"] is None and event[0]["deadline_ms"] is None


def test_a_missed_own_deadline_fails_the_verdict():
    stages = [{"id": "rt", "name": "RT", "feasible": True, "hw_ms": 1.0, "budget_ms": 10.0, "nodes": ["csis"]}]
    intervals = {"target_ms": P, "preview": {"ok": True}, "video": {"ok": True}, "streams": []}
    row = {"node": "loop", "cadence": "period", "period_ms": 10.0, "deadline_ms": 10.0, "worst_response_ms": 11.0, "ok": False}
    verdict = _verdict(stages, intervals, [], {}, P, [row])
    assert verdict["status"] == "fail"
    assert verdict["reasons"] == ["loop (period 10.0 ms): 응답 11.000 ms > 자체 deadline 10.000 ms"]
    assert _verdict(stages, intervals, [], {}, P, [{**row, "ok": True}])["status"] == "ok"
    assert _verdict(stages, intervals, [], {}, P)["status"] == "ok"


def test_rows_read_events_by_attribute():
    e = SimpleNamespace(frame_index=None, cadence="chunk", node_id="writer", independent_period_ms=500.0,
                        deadline_ms=40.0, ready_ms=0.0, start_ms=0.0, end_ms=12.0, slack_ms=28.0)
    assert own_cadence_rows([e])[0] == {"node": "writer", "cadence": "chunk", "period_ms": 500.0, "deadline_ms": 40.0,
                                        "releases": 1, "worst_response_ms": 12.0, "worst_slack_ms": 28.0, "ok": True}
