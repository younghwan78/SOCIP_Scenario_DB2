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


def _readout(pct: int, budget: float, period: float | None) -> str:
    share = f" (frame period {period:.3f} ms의 70%)" if period else ""
    return (f"RT HW 23.35 ms > {pct}% budget {budget:.2f} ms — sensor readout 23.35 ms{share}가 정하는 시간이라 "
            "clock으로 줄일 수 없음 (sensor mode · blanking 또는 margin 조정)")


def test_read_out_bound_rt_points_at_the_sensor_not_the_clock():
    e = explain(_readout(65, 21.67, 33.333))
    assert e["code"] == "rt_budget" and "sensor readout 23.35 ms가 정함" in e["text"]
    assert "clock으로는 줄지 않음" in e["action"] and "SW margin 29% 이하" in e["action"]  # 1 - 23.355 / 33.333 = 29.9 %
    assert "RT clock ×" not in e["action"]
    # margin 35.5 % shows a rounded "64%" budget; the limit still comes from the exact period, not 30 %
    assert "SW margin 29% 이하" in explain(_readout(64, 21.50, 33.333))["action"]
    # a 0 % budget (margin ~100 %) does not divide by it
    assert "SW margin 29% 이하" in explain(_readout(0, 0.03, 33.333))["action"]
    # no period in the line: the caller's frame period, else no margin advice
    assert "SW margin 29% 이하" in explain(_readout(65, 21.67, None), 1000 / 30)["action"]
    assert "SW margin" not in explain(_readout(65, 21.67, None))["action"]
    # read-out longer than the period (8K read-out at 60 fps): no margin fixes it
    long = explain(_readout(75, 12.50, 16.667))["action"]
    assert "SW margin" not in long and "margin으로는 불가, fps 하향" in long


def test_off_target_summary_kept_when_no_stream_detail():
    assert [e["code"] for e in explain_all(["preview/video interval off target"], 30)] == ["interval"]


def test_pipelined_failures_are_sw_budget_with_a_thread_action():
    """The pipelined verdict names one thread or one shared CPU, not the stage SW: both are SW-budget causes
    (validity rules apply), never "other" with no action."""
    from scenario_db.reporting.reason_text import diagnose

    e = explain("NRT: SW task 9.10 ms > frame period (한 thread가 1 frame 안에 못 끝남)", 1000 / 240)
    assert e["code"] == "sw_budget" and "최장 SW task 9.1 ms > frame 주기 4.17 ms" in e["text"]
    assert "4.9 ms 이상 단축" in e["action"] and "3-frame batch" in e["action"]
    g = explain("Post-NRT: CPU CPU (shared_cpu)의 SW 합 12.00 ms > frame period (같은 thread/core: eis, post_irta)", 1000 / 120)
    assert g["code"] == "sw_budget" and "CPU (shared_cpu)" in g["text"] and "(eis, post_irta)" in g["text"]
    assert "다른 core" in g["action"] and "3.7 ms 이상 단축" in g["action"]
    # a task exactly two periods long needs two threads, not three
    assert "2-frame batch" in explain("NRT: SW task 20.00 ms > frame period (한 thread가 1 frame 안에 못 끝남)", 10.0)["action"]
    d = diagnose([e], 240)
    assert d["code"] == "sw_budget" and "pipelined 판정" in d["focus"] and d["actions"][0] == e["action"]
    assert d["severity"].startswith("SW 9.1 ms")


def test_stage_names_with_punctuation():
    e = explain("Post-NRT (EIS/SW → GDC): SW 6.00 ms leaves no HW budget", 1000 / 240)
    assert e["code"] == "sw_budget" and e["text"].startswith("Post-NRT (EIS/SW → GDC) SW 6.0 ms")
