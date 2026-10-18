"""Review verdicts (REF-05), fps validity (RISK-01), SW-01 count, lever ladder and the KPI scoreboard."""
from scenario_db.reporting.review_verdict import fps_validity, lever_actions, power_verdicts, scoreboard
from scenario_db.reporting.risk_rules import build_risks


def row(vid, mw=500.0, **kw):
    return {"scenario_id": "uc", "variant_id": vid, "fps": 30, "spec_ok": True, "prediction_id": f"P-{vid}",
            "power": {"total_mw": mw}, "distribution": {"total_mw": {"min": mw * 0.95, "max": mw * 1.02}},
            "sw_margin_pct": 20.0, "sw_bottleneck": "post_irta", "inputs": {"sw_timing_source": "measured"},
            "reasons_explained": [], "lossy": False} | kw


def cal(vid, meas, origin="physical_capture"):
    return {"scenario_id": "uc", "variant_id": vid, "measured_mw": meas, "origin": origin, "synthetic": origin != "physical_capture",
            "fit": {"worst_delta_pct": 0, "offsetting": False}}


def snap(**kw):
    base = {"overview": {"sample_dvfs": False}, "spec_summary": {"explored": 0, "failed": [], "errors": []},
            "review_context": {"policy": {"throughput_model": "pipelined"}, "rows": []}, "sw_margin_top5": [],
            "criteria": {"power": {"tolerance_pct": 3}}, "scenarios": [], "calibration": []}
    return base | kw


def test_verdict_uses_silicon_first_and_flags_a_flip():
    s = snap(scenarios=[row("vdis", 550.0)], references={"vdis": {"mw": 620.0, "source": "explicit"}},
             calibration=[cal("vdis", 675.2)])
    v = power_verdicts(s)[0]
    assert v["state"] == "over" and v["basis"] == "measurement" and v["flip"]
    assert round(v["pred_pct"], 1) == -11.3 and round(v["meas_pct"], 1) == 8.9
    risks = {r["key"]: r for r in build_risks(s)}
    assert risks["verdict_flip"]["severity"] == "high" and risks["power_over_reference"]["affected"] == ["vdis"]


def test_conditional_when_range_or_corrected_or_synthetic_crosses_the_tolerance():
    r = row("portrait", 584.0, distribution={"total_mw": {"min": 509.0, "max": 679.0}})
    s = snap(scenarios=[r], references={"portrait": {"mw": 640.0, "source": "explicit"}}, calibration=[cal("portrait", 700.3, "synthetic")],
             model={"bias": {"total": {"n": 54, "median": -15.5, "verdict": "bias"}}})
    v = power_verdicts(s)[0]
    assert v["state"] == "conditional" and not v["flip"] and v["basis"] == "prediction"
    assert "탐색 범위 상단 +6.1%" in v["why"] and "보정 예측" in v["why"] and "합성 실측 +9.4%" in v["why"]
    assert round(v["corr_mw"], 1) == round(584.0 / 0.845, 1)
    assert power_verdicts(snap(scenarios=[row("ok", 500.0)], references={"ok": {"mw": 620.0}}))[0]["state"] == "ok"


def test_unregistered_and_uncovered_references():
    s = snap(scenarios=[row("uhd120", 1855.1, prediction_id=None)],
             references={"uhd120": {"mw": 2000.0, "source": "explicit"}, "apv": {"mw": 1720.0, "source": "explicit"}})
    v = {x["variant_id"]: x for x in power_verdicts(s)}
    assert v["uhd120"]["state"] == "ok" and not v["uhd120"]["registered"] and "미등록" in v["uhd120"]["why"]
    assert v["apv"]["state"] == "uncovered"
    keys = {r["key"] for r in build_risks(s)}
    assert {"reference_unregistered", "reference_missing"} <= keys


def test_fps_miss_validity_caps_critical():
    hi = row("fhd240", fps=240, spec_ok=False, reasons_explained=[{"code": "sw_budget"}])
    unv = row("ssm", fps=60, spec_ok=False, reasons_explained=[{"code": "ip_clock"}], inputs={"sensor_support": "unverified_requested_size_or_fps"})
    real = row("uhd60", fps=60, spec_ok=False, reasons_explained=[{"code": "ip_clock"}])
    assert fps_validity(hi)[0] == "model_limit" and fps_validity(unv)[0] == "input_unverified" and fps_validity(real)[0] == "confirmed"
    failed = [{"variant_id": r["variant_id"], "reasons": ["x"], "explained": [{"text": "SW", "action": "—"}]} for r in (hi, unv, real)]
    risks = {r["key"]: r for r in build_risks(snap(scenarios=[hi, unv, real], spec_summary={"explored": 3, "failed": failed, "errors": []}))}
    assert risks["fps_drop"]["severity"] == "critical" and risks["fps_drop"]["affected"] == ["uhd60"]
    assert risks["fps_drop_unverified"]["severity"] == "high" and risks["fps_drop_unverified"]["validity"] == "model_limit"
    assert risks["fps_drop_unverified"]["checks"]


def test_sw_margin_counts_every_scenario_not_only_top5():
    rows = [row(f"v{i}", sw_margin_pct=float(i - 20), inputs={"sw_timing_source": "assumed"}) for i in range(32)]
    top5 = [{"variant_id": r["variant_id"], "margin_pct": r["sw_margin_pct"], "stage": "nrt", "bottleneck": "post_irta"} for r in rows[:5]]
    r = next(x for x in build_risks(snap(scenarios=rows, sw_margin_top5=top5)) if x["key"] == "sw_margin_low")
    assert r["title"] == "SW timing margin < 10% · 30건 (음수 20)" and r["validity"] == "input_unverified"


def test_lever_ladder_orders_clock_compression_sw_then_iq_options():
    s = snap(scenarios=[row("a", sw_margin_pct=-5.0)],
             domains=[{"scenario_id": "uc", "variant_id": "a", "domain": "CAM", "level": 6, "base_level": 7, "raise_mw": 12.0}],
             compression=[{"buffer": "LOSSY_BUF", "lossy": True, "support": "catalog", "variants": 2, "selected": 0, "delta_mw": -80.0},
                          {"buffer": "SBWC_BUF", "lossy": False, "support": "catalog", "variants": 1, "selected": 0, "delta_mw": -10.0}],
             power_options=[{"scenario_id": "uc", "variant_id": "a", "best": {"labels": ["MTNR L0 skip"], "delta_mw": -120.0, "iq_eval": "required"}}])
    acts = lever_actions(s)
    assert [a["tier"] for a in acts] == [1, 2, 2, 3, 4]
    assert acts[1]["action"].startswith("SBWC_BUF") and not acts[1]["iq"] and acts[2]["iq"]   # lossless before lossy
    assert acts[-1]["check"] == "IQ 평가 후에만 적용"


def test_scoreboard_marks_uncovered_kpi_and_parallel_fps():
    s = snap(scenarios=[row("fhd60", sw_margin_pct=-22.0)], references={},
             review_context={"policy": {"throughput_model": "pipelined",
                                        "kpi": [{"variant_ref": "fhd60", "label": "FHD60"}, {"variant_ref": "apv", "label": "APV"}]}, "rows": []})
    b = {k["label"]: k for k in scoreboard(s)}
    assert b["FHD60"]["fps"]["label"] == "충족 · 병렬 전제" and b["FHD60"]["overall"]["label"].startswith("판정 불가")
    assert not b["APV"]["covered"] and b["APV"]["overall"]["label"] == "미커버"
    assert any(r["key"] == "kpi_uncovered" for r in build_risks(s))


def test_drivers_rank_common_causes():
    from scenario_db.reporting.review_verdict import drivers

    rows = [row(f"v{i}", sw_margin_pct=-5.0, inputs={"sw_timing_source": "assumed"}) for i in range(4)] + [row("hfr", fps=240, spec_ok=False)]
    ds = {d["key"]: d for d in drivers(snap(scenarios=rows, overview={"sample_dvfs": True}))}
    assert ds["sw_task"]["label"] == "SW task post_irta" and ds["sw_task"]["count"] == 4
    assert ds["sw_assumed"]["count"] == 4 and ds["high_fps"]["count"] == 1 and ds["sample_dvfs"]["count"] == 5
