from __future__ import annotations

from scenario_db.reporting.arch_report import compact_reasons
from scenario_db.reporting.reason_text import explain, explain_all, first_text

FHD120 = [
    "NRT: SW 11.10 ms leaves no HW budget",
    "preview interval 10.267 ms != 8.333 ms",
    "video interval 10.267 ms != 8.333 ms",
    "byrp: required_clock 1348.8MHz exceeds max DVFS speed 1066.0MHz",
    "rgbp: required_clock 1348.8MHz exceeds max DVFS speed 1066.0MHz",
]


def test_explains_sw_budget_with_the_shortfall_and_batch_size():
    e = explain(FHD120[0], 1000 / 120)
    assert e["code"] == "sw_budget"
    assert "11.1 ms ≥ frame 주기 8.33 ms" in e["text"]
    assert "2.8 ms 이상 단축" in e["action"] and "2-frame batch" in e["action"]


def test_merges_intervals_and_groups_clock_lines():
    ex = explain_all(compact_reasons(FHD120 + ["preview/video interval off target"]), 120)
    assert [e["code"] for e in ex] == ["sw_budget", "ip_clock", "interval"]
    assert ex[1]["text"].startswith("byrp, rgbp: 필요 clock 1349 MHz > DVFS 최고 1066 MHz")
    assert "×1.27" in ex[1]["action"]
    assert ex[2]["text"].startswith("preview·video 출력 간격 10.27 ms (목표 8.33 ms, 97.4 fps")


def test_rt_budget_and_passthrough():
    e = explain("RT HW 3.10 ms > 75% budget 0.78 ms", 1.04)
    assert e["code"] == "rt_budget" and "×3.97" in e["action"]
    assert explain("something new", None) == {"code": "other", "raw": "something new", "text": "something new", "action": "—"}
    assert first_text([], 30) == "원인 미기록"


def test_read_out_bound_rt_points_at_the_sensor_not_the_clock():
    e = explain("RT HW 23.35 ms > 65% budget 21.67 ms — sensor readout 23.35 ms (frame period의 70%)가 정하는 시간이라 "
                "clock으로 줄일 수 없음 (sensor mode · blanking 또는 margin 조정)", 1.08)
    assert e["code"] == "rt_budget" and "sensor readout 23.35 ms가 정함" in e["text"]
    assert "clock으로는 줄지 않음" in e["action"] and "SW margin 29% 이하" in e["action"]  # 1 - 23.35 / 33.34
    assert "RT clock ×" not in e["action"]


def test_off_target_summary_kept_when_no_stream_detail():
    assert [e["code"] for e in explain_all(["preview/video interval off target"], 30)] == ["interval"]


def test_stage_names_with_punctuation():
    e = explain("Post-NRT (EIS/SW → GDC): SW 6.00 ms leaves no HW budget", 1000 / 240)
    assert e["code"] == "sw_budget" and e["text"].startswith("Post-NRT (EIS/SW → GDC) SW 6.0 ms")
