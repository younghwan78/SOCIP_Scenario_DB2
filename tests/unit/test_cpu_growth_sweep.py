"""SW-growth sweep helpers: OPP events, tolerance and the scaled Timing Budget coupling."""
import pytest

from scenario_db.api.services.cpu import growth_limits, opp_events, scale_coupling


def _p(g, ref_mw, lf0, best_mw, stages=None):
    return {"growth": g, "reference": {"total_mw": ref_mw, "mhz": {"MID_LF0": lf0, "MID_LF1": 400, "dsu": 645}},
            "best": {"total_mw": best_mw, "mhz": {"MID_LF0": lf0, "MID_LF1": 400, "dsu": 645}}, "stages": stages or []}


def test_largest_opp_step_and_timing_room_set_the_tolerance():
    nrt = [{"stage": "nrt", "sw_ms": 11.1, "room_ms": 14.844, "slack_ms": 3.744}]
    pts = [_p(1.0, 237.4, 1600, 232.6, nrt), _p(1.1, 257.7, 1600, 247.3), _p(1.3, 297.8, 1600, 279.0), _p(1.4, 432.7, 2000, 408.5)]
    ev = opp_events(pts, "reference") + opp_events(pts, "best")
    assert [(e["which"], e["growth_from"], e["cluster"], e["mhz"]) for e in ev] == [
        ("reference", 1.3, "MID_LF0", [1600, 2000]), ("best", 1.3, "MID_LF0", [1600, 2000])]
    lim = growth_limits(pts, ev)
    assert lim["opp_step"]["delta_mw"] == 134.9 and lim["opp_step_best_mw"] == 129.5
    assert lim["timing_at"] == 1.337 and lim["tolerance"] == 1.3 and lim["binding"] == "opp"
    # a stage with less room binds first
    tight = [{"stage": "nrt", "sw_ms": 10.0, "room_ms": 12.0, "slack_ms": 2.0}]
    pts2 = [_p(1.0, 1, 1600, 1, tight), _p(1.4, 1.4, 1600, 1.4), _p(1.5, 3, 2000, 3)]
    lim2 = growth_limits(pts2, opp_events(pts2, "reference"))
    assert lim2["binding"] == "timing" and lim2["tolerance"] == 1.2
    assert growth_limits([_p(1.0, 1, 1600, 1), _p(1.1, 1.1, 1600, 1)], [])["tolerance"] is None


def test_scale_coupling_keeps_room_and_scales_sw():
    base = {"runtime_scale": 1.0, "period_ms": 33.3, "stages": [
        {"stage": "nrt", "sw_ms": 11.1, "hw_ms": 10.0, "overhead_ms": 8.46, "room_ms": 14.844, "slack_ms": 3.744, "stretch": 1.337,
         "tasks": [{"task": "post_irta", "ms": 5.0}, {"task": "pre_me_rta", "ms": 6.1}]}], "stretch": {"post_irta": 1.337}}
    s = scale_coupling(base, 1.4)
    st = s["stages"][0]
    assert st["sw_ms"] == 15.54 and st["room_ms"] == 14.844 and st["slack_ms"] < 0
    assert st["stretch"] == 1.0 and s["stretch"]["pre_me_rta"] == 1.0 and s["runtime_scale"] == 1.4
    assert abs(st["tasks"][0]["ms"] - 7.0) < 1e-9


@pytest.mark.parametrize('room', [0.0, -2.0])
def test_no_stage_room_means_no_sw_growth_tolerance(room):
    pts = [_p(1.0, 1, 1600, 1, [{'stage': 'nrt', 'sw_ms': 10, 'room_ms': room}])]
    limits = growth_limits(pts, [])
    assert limits['timing_at'] == limits['tolerance'] == 0
    assert limits['binding'] == 'timing'


def test_timing_limit_preserves_fixed_per_task_growth():
    # 8 ms of fixed task work + 2 ms * default_growth: 14 ms room runs out at x3.
    pts = [_p(1, 1, 1600, 1, [{'stage': 'nrt', 'sw_ms': 10, 'room_ms': 14}]),
           _p(2, 2, 1600, 2, [{'stage': 'nrt', 'sw_ms': 12, 'room_ms': 14}])]
    assert growth_limits(pts, [])['timing_at'] == 3
