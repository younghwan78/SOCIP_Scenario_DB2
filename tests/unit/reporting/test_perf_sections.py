"""Performance sections: output fps, latency → buffer use, SW optimisation requests."""
from copy import deepcopy

from scenario_db.reporting.arch_report import _frame_buffer, render_html
from scenario_db.reporting.perf_sections import (
    buffer_rows,
    latency_buffer_block,
    output_fps_block,
    output_rows,
    sw_request_block,
    sw_requests,
)
from scenario_db.reporting.risk_rules import _latency_risks

from tests.unit.reporting.test_review_report import snapshot


def stage(name, load, margin, chain, st="nrt", binding="task"):
    return {"stage": st, "bottleneck": name, "binding_ms": load, "bottleneck_ms": load, "margin_pct": margin,
            "chain_ms": chain, "binding": binding, "hw_ms": chain - load, "sw_ms": load, "in_flight": 1}


def row(vid, fps, ok, intervals, stages, latency=None, fb=None):
    p = 1000.0 / fps
    return {"scenario_id": "uc", "variant_id": vid, "fps": fps, "period_ms": p, "spec_ok": ok,
            "intervals": intervals, "sw_stages": stages, "latency": latency, "frame_buffer": fb,
            "reasons": [] if ok else ["SW task > frame period"],
            "reasons_explained": [] if ok else [{"text": "SW task > frame period"}],
            "power": {"total_mw": 500.0, "cpu_mw": 100.0, "hw_mw": 200.0, "bw_mw": 200.0}, "bw_mbs": 3000.0,
            "distribution": {k: {"min": 450.0, "p25": 480.0, "median": 500.0, "p75": 520.0, "max": 550.0}
                             for k in ("total_mw", "cpu_mw", "hw_mw", "bw_ip_mw", "bw_cpu_mw", "bw_mbs")}, "compression": [], "dvfs": {}, "eis_on": False, "status": {}, "cls": None,
            "inputs": {}, "sw": {}, "ip_mw": {}, "assumed_mw": {}}


def perf_snap():
    s = snapshot()
    s["review_context"] = {"policy": {"sw_growth_budget": 1.2, "max_latency_frames": 2}}
    s["scenarios"] = [
        row("cam-rec-a30", 30, True, {"preview": 33.333, "video": 33.333}, [stage("post_irta", 5.6, 83.2, 30.0)],
            {"video_ms": 70.0, "preview_ms": 54.0, "video_frames": 2.1, "preview_frames": 1.6}, {"mb": 40.0, "raw_mb": 50.0}),
        row("cam-rec-b60", 60, True, {"preview": 16.667, "video": 16.667}, [stage("post_irta", 14.0, 16.0, 20.0)],
            {"video_ms": 30.0, "preview_ms": 30.0, "video_frames": 1.8, "preview_frames": 1.8}, {"mb": 30.0, "raw_mb": 30.0}),
        row("cam-rec-c240", 240, False, {"preview": 8.333, "video": 8.333}, [stage("post_irta", 5.6, -34.0, 9.0),
                                                                           stage("blend", 1.0, 76.0, 1.0, st="post")],
            {"video_ms": 18.0, "preview_ms": 18.0, "video_frames": 4.4, "preview_frames": 4.4}, None),
    ]
    return s


def test_output_fps_lists_drops_first_then_the_closest_to_a_drop():
    rows = output_rows(perf_snap())
    assert [o["variant_id"] for o in rows] == ["cam-rec-c240", "cam-rec-b60", "cam-rec-a30"]
    drop = rows[0]
    assert drop["preview_fps"] == 120.0 and drop["preview_ok"] is False and drop["margin_pct"] == -34.0
    assert rows[1]["video_ok"] is True and rows[1]["stage"] == "nrt"
    html = output_fps_block(perf_snap())
    assert "frame drop 1" in html and "SW task &gt; frame period" in html


def test_latency_buffer_estimate_uses_frames_alive_and_the_compressed_frame():
    rows = buffer_rows(perf_snap())
    a = next(o for o in rows if o["variant_id"] == "cam-rec-a30")
    assert a["alive"] == 3 and a["buffer_mb"] == 120.0
    assert next(o for o in rows if o["variant_id"] == "cam-rec-c240")["buffer_mb"] is None
    html = latency_buffer_block(perf_snap())
    assert "압축 전 50.0" in html and "latency 한도 2 frame" in html
    risks = _latency_risks(perf_snap())
    # a spec miss is a frame drop risk already; the buffer risk lists fps-holding scenarios only
    assert risks[0]["key"] == "latency_buffer" and risks[0]["affected"] == ["cam-rec-a30"]
    assert "추정 buffer 120 MB" in risks[0]["detail"]
    s = perf_snap()
    s["review_context"]["policy"]["max_latency_frames"] = None
    assert _latency_risks(s) == []


def test_frame_buffer_divides_traffic_by_fps_and_ports_and_applies_the_case_compression():
    bufs = [{"buffer": "A", "raw_mbs": 3000.0, "ports": ["w", "r"], "comp_ratio": 0.7,
             "modes": [{"mode": "LOSSY", "comp_ratio": 0.5}]},
            {"buffer": "B", "raw_mbs": 900.0, "ports": ["w", "r1", "r2"]}]
    assert _frame_buffer(bufs, 30, [], {}) == {"raw_mb": 60.0, "mb": 60.0, "buffers": 2}
    assert _frame_buffer(bufs, 30, ["A"], {"A": "LOSSY"})["mb"] == 35.0
    assert _frame_buffer(bufs, 30, ["A"], {})["mb"] == 45.0
    assert _frame_buffer([], 30, [], {}) is None and _frame_buffer(bufs, None, [], {}) is None


def test_sw_requests_rank_tasks_that_need_a_cut_and_flag_growth():
    reqs = sw_requests(perf_snap())
    top = reqs[0]
    assert top["task"] == "post_irta" and top["low"] == ["cam-rec-c240"] and len(top["variants"]) == 3
    # 10 % margin at 240 fps: 5.6 − 0.9 × 4.167 = 1.85 ms
    assert top["need_ms"] == 1.85 and top["need_variant"] == "cam-rec-c240"
    # ×1.2 growth: b60 14 × 1.2 = 16.8 ms > 0.9 × 16.67 → under 10 %
    assert "cam-rec-b60" in top["grown_low"]
    blend = next(t for t in reqs if t["task"] == "blend")
    assert blend["stages"] == ["post"] and blend["need_ms"] == 0 and not blend["grown_low"]
    snap = perf_snap()
    before = deepcopy(snap)
    html = sw_request_block(snap)
    assert snap == before
    assert "요청 1건" in html and "1.9 ms 이상 단축 필요" in html and "SW ×1.2" in html
    full = render_html("Review", snap)
    assert "SW 최적화 요청 post_irta −1.9 ms" in full and "Frame drop — 최종 출력 fps" in full
    assert "Latency → buffer 사용" in full
