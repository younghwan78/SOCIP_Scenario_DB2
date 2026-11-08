"""Performance sections: output fps, latency → buffer use, SW optimisation requests."""
from copy import deepcopy

from scenario_db.reporting.arch_report import render_html
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
    return {"stage": st, "basis": "pipelined", "bottleneck": name, "binding_ms": load, "bottleneck_ms": load, "margin_pct": margin,
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
            {"video_ms": 70.0, "preview_ms": 54.0, "video_frames": 2.1, "preview_frames": 1.6}, {"mb": 40.0}),
        row("cam-rec-b60", 60, True, {"preview": 16.667, "video": 16.667}, [stage("post_irta", 14.0, 16.0, 20.0)],
            {"video_ms": 30.0, "preview_ms": 30.0, "video_frames": 1.8, "preview_frames": 1.8}, {"mb": 30.0})
        | {"sw_growth": {"1.1": {"nrt": 8.0}, "1.2": {"nrt": 2.0}}},
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
    assert "latency 한도 2 frame" in html and "DMA write 합" in html
    risks = _latency_risks(perf_snap())
    # a spec miss is a frame drop risk already; the buffer risk lists fps-holding scenarios only
    assert risks[0]["key"] == "latency_buffer" and risks[0]["affected"] == ["cam-rec-a30"]
    assert "추정 buffer 120 MB" in risks[0]["detail"]
    s = perf_snap()
    s["review_context"]["policy"]["max_latency_frames"] = None
    assert _latency_risks(s) == []


def test_sw_requests_rank_tasks_that_need_a_cut_and_flag_growth():
    reqs = sw_requests(perf_snap())
    top = reqs[0]
    assert top["task"] == "post_irta" and top["low"] == [("uc", "cam-rec-c240")] and len(top["variants"]) == 3
    # 10 % margin at 240 fps: 5.6 − 0.9 × 4.167 = 1.85 ms
    assert top["need_ms"] == 1.85 and top["need_variant"] == "cam-rec-c240"
    # ×1.2 growth: b60 14 × 1.2 = 16.8 ms > 0.9 × 16.67 → under 10 %
    assert ("uc", "cam-rec-b60") in top["grown_low"]
    blend = next(t for t in reqs if t["task"] == "blend")
    assert blend["stages"] == ["post"] and blend["need_ms"] == 0 and not blend["grown_low"]
    snap = perf_snap()
    before = deepcopy(snap)
    html = sw_request_block(snap)
    assert snap == before
    assert "요청 1건" in html and "1.9 ms 이상 단축 필요" in html and "SW ×1.2" in html
    # the cut comes from a 240 fps scenario (batch not modelled): flagged as an upper bound
    assert "batch 미모델 — 상한값" in html and "그 외 scenario는 단축 불필요" in html
    full = render_html("Review", snap)
    assert "SW 최적화 요청 post_irta −1.9 ms (고속 batch 미모델 상한)" in full and "Frame drop — 최종 출력 fps" in full
    assert "Latency → buffer 사용" in full


def test_frame_drop_comes_from_the_output_intervals_not_the_overall_spec_verdict():
    s = perf_snap()
    # outputs hold 30 fps; the spec miss is a power budget
    s["scenarios"].append(row("cam-rec-budget", 30, False, {"preview": 33.333, "video": 33.333}, [stage("post_irta", 5.6, 83.2, 30.0)]))
    rows = {o["variant_id"]: o for o in output_rows(s)}
    assert rows["cam-rec-budget"]["drop"] is False and rows["cam-rec-c240"]["drop"] is True
    html = output_fps_block(s)
    assert "frame drop 1" in html and "다른 spec(전력 · BW 예산 등) 미달 1" in html and "기타 spec 미달" in html
    # without intervals (older snapshot) the spec verdict stands
    s["scenarios"].append(row("cam-rec-old", 30, False, {}, []))
    assert {o["variant_id"]: o for o in output_rows(s)}["cam-rec-old"]["drop"] is True


def test_stage_basis_cuts_the_whole_serial_stage():
    s = perf_snap()
    st = stage("blend", 3.0, 0.0, 10.0, st="post") | {"basis": "stage", "sw_ms": 6.0, "hw_ms": 4.0}
    s["scenarios"] = [row("cam-rec-s", 100, True, {"preview": 10.0, "video": 10.0}, [st])]
    t = sw_requests(s)[0]
    # period 10 ms, HW 4 + SW 6 = 10 ms: 1 ms cut for a 10 % margin (the 3 ms longest task alone would say 0)
    assert t["need_ms"] == 1.0 and t["basis"] == ["stage"] and t["max_ms"] == 6.0


def test_sw_requests_count_scenario_variant_pairs():
    s = perf_snap()
    twin = dict(s["scenarios"][2]) | {"scenario_id": "uc-apv"}
    s["scenarios"].append(twin)
    t = sw_requests(s)[0]
    assert t["low"] == [("uc", "cam-rec-c240"), ("uc-apv", "cam-rec-c240")] and len(t["variants"]) == 4


def test_secondary_stream_cadence_and_legacy_stage_basis_and_budget_only_latency_risk():
    s = perf_snap()
    # preview / video hold 30 fps but a secondary encoder does not: the all-stream verdict wins
    s["scenarios"].append(row("cam-rec-dual", 30, False, {"preview": 33.333, "video": 33.333}, []) | {"intervals_ok": False})
    assert {o["variant_id"]: o for o in output_rows(s)}["cam-rec-dual"]["drop"] is True
    # a stage without basis (engine < 15) was a stage-chain margin: HW 4 + SW 6 in 10 ms needs a 1 ms cut
    legacy = {k: v for k, v in stage("blend", 3.0, 0.0, 10.0, st="post").items() if k != "basis"} | {"sw_ms": 6.0, "hw_ms": 4.0}
    s2 = perf_snap()
    s2["scenarios"] = [row("cam-rec-old", 100, True, {"preview": 10.0, "video": 10.0}, [legacy])]
    assert sw_requests(s2)[0]["need_ms"] == 1.0
    # outputs hold fps but a power budget fails: the latency / buffer risk still applies
    s3 = perf_snap()
    s3["scenarios"][0]["spec_ok"] = False
    assert "cam-rec-a30" in _latency_risks(s3)[0]["affected"]


def test_growth_uses_the_simulated_slices_and_the_objective_scale():
    from scenario_db.reporting.perf_sections import _grown_margin

    r = {"sw_scale": 1.0, "sw_growth": {"1.2": {"nrt": 11.9}}}
    # the slice (runtime scaled, fixed latency / overhead kept) decides, not SW × budget
    assert _grown_margin(r, "nrt", 40.0, 1.2) == 11.9
    # an objective already at ×1.2: its margin is the grown margin (no double growth)
    assert _grown_margin({"sw_scale": 1.2}, "nrt", 13.6, 1.2) == 13.6
    assert _grown_margin({"sw_scale": 1.0, "sw_growth": {}}, "nrt", 40.0, 1.3) is None
    s = perf_snap()
    s["review_context"]["policy"]["sw_growth_budget"] = 1.3
    t = next(x for x in sw_requests(s) if x["task"] == "post_irta")
    assert len(t["grown_unknown"]) == 3 and "미탐색 3" in sw_request_block(s)


def test_buffer_frames_use_the_unrounded_latency():
    s = perf_snap()
    s["scenarios"][0]["latency"] = {"video_ms": 100.03, "preview_ms": 50.0, "video_frames": 3.0, "preview_frames": 1.5}
    s["review_context"]["policy"]["max_latency_frames"] = 3
    a = next(o for o in buffer_rows(s) if o["variant_id"] == "cam-rec-a30")
    assert a["alive"] == 4 and a["buffer_mb"] == 160.0
    assert "cam-rec-a30" in _latency_risks(s)[0]["affected"]


def test_growth_margins_follow_each_stage_rule():
    from scenario_db.reporting.arch_report import _growth_margins

    v = {"fps": 100, "period_ms": 10.0, "sw_margin": {"statistic": "max"}, "slices": [
        {"statistic": "max", "runtime_scale": 1.2, "stages": {
            "nrt": {"throughput": "pipelined", "longest_sw_ms": 6.0, "cpu_load_ms": 7.0, "sw_ms": 9.0, "hw_ms": 4.0},
            "post": {"throughput": "stage", "sw_ms": 5.0, "hw_ms": 4.0}, "rt": {"hw_ms": 3.0}}},
        {"statistic": "mean", "runtime_scale": 1.2, "stages": {"nrt": {"throughput": "pipelined", "longest_sw_ms": 1.0}}}]}
    assert _growth_margins(v, None) == {"1.2": {"nrt": 30.0, "post": 10.0}}
