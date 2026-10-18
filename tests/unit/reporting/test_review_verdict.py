"""Review verdicts (REF-05), fps validity (RISK-01), SW-01 count, lever ladder and the KPI scoreboard."""
from scenario_db.reporting.review_verdict import fps_validity, lever_actions, power_verdicts, scoreboard
from scenario_db.reporting.risk_rules import build_risks
import pytest


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


@pytest.mark.parametrize('median', [-100, -120])
def test_nonpositive_bias_denominator_cannot_create_a_corrected_power(median):
    s = snap(scenarios=[row('v')], references={'v': {'mw': 600}},
             model={'bias': {'total': {'n': 8, 'median': median, 'verdict': 'bias'}}})
    v = power_verdicts(s)[0]
    assert v['corr_mw'] is None and v['bias_pct'] is None and v['state'] == 'ok'


def test_silicon_verdict_without_a_comparable_prediction_still_builds_risks():
    s = snap(scenarios=[row('v', spec_ok=False, prediction_id=None)],
             calibration=[cal('v', 500)], references={'v': {'mw': 600}})
    verdict = power_verdicts(s)[0]
    assert verdict['basis'] == 'measurement' and verdict['state'] == 'ok' and verdict['pred_mw'] is None
    risks = {r['key']: r for r in build_risks(s)}
    assert '비교 가능한 예측 없음' in risks['reference_unregistered']['detail']


def test_same_named_failures_keep_their_own_scenario_validity():
    real = row('shared', scenario_id='a', spec_ok=False, reasons_explained=[{'code': 'rt_budget'}])
    uncertain = row('shared', scenario_id='b', fps=240, spec_ok=False, reasons_explained=[{'code': 'sw_budget'}])
    failed = [{'scenario_id': r['scenario_id'], 'variant_id': 'shared', 'reasons': ['timing']} for r in (real, uncertain)]
    s = snap(scenarios=[real, uncertain], spec_summary={'explored': 2, 'failed': failed})
    risks = {r['key']: r for r in build_risks(s)}
    assert risks['fps_drop']['severity'] == 'critical' and '1/2' in risks['fps_drop']['title']
    assert risks['fps_drop_unverified']['validity'] == 'model_limit' and '1/2' in risks['fps_drop_unverified']['title']
    # Legacy reports lack scenario IDs: an ambiguous row must never downgrade a confirmed failure.
    s['spec_summary']['failed'] = [{'variant_id': 'shared', 'reasons': ['timing']}]
    assert next(r for r in build_risks(s) if r['rule'] == 'fps_drop')['severity'] == 'critical'


@pytest.mark.parametrize('codes', [['rt_budget'], ['ip_clock'], ['other'], ['sw_budget', 'rt_budget']])
def test_high_frame_rate_does_not_hide_independent_hardware_or_unknown_failures(codes):
    r = row('hfr', fps=240, spec_ok=False, reasons_explained=[{'code': c} for c in codes])
    assert fps_validity(r)[0] == 'confirmed'


def test_partial_summary_and_resolved_risks_do_not_claim_completion_or_request_old_decisions():
    from scenario_db.reporting.review_verdict import decisions, messages

    s = snap(spec_summary={'explored': 0, 'spec_ok': 0, 'errors': [{'variant_id': 'v', 'error': 'bad input'}]})
    text = messages(s, [], [])[0]
    assert '부분 평가' in text and '계산 실패 1개' in text and '평가 완료 결과 없음' in text and '전부 fps 충족' not in text
    risks = [{'key': 'power_over_reference', 'trend': 'resolve_candidate'},
             {'key': 'verdict_flip', 'status': 'closed'}, {'key': 'sw_margin_low', 'auto_state': 'resolve_candidate'},
             {'key': 'kpi_uncovered', 'status': 'open'}]
    assert decisions(risks) == ['미커버 KPI scenario 탐색 · 등록 일정']


def test_kpi_xlsx_is_available_without_previous_project_references():
    from scenario_db.reporting.arch_report import build_snapshot
    from scenario_db.reporting.xlsx_export import report_sheets

    s = build_snapshot({'id': 'run', 'title': 'review', 'scenario_type': 'camera', 'spec': {}, 'variants': [], 'summary': {}}, {}, {})
    s['review_context'] = {'policy': {'kpi': [{'variant_ref': 'missing', 'label': 'Missing KPI'}]}}
    sheets = {name: (headers, rows) for name, headers, rows in report_sheets(s)}
    assert 'KPI' in sheets and sheets['KPI'][1][0][0] == 'Missing KPI'
    assert sheets['KPI'][1][0][-1] == '미커버' and '전과제 판정' not in sheets


def test_previous_comparison_conditions_spec_up_decomposition_and_latency():
    from scenario_db.reporting.review_verdict import compare_previous

    cur = row("uhd60", 900.0, conditions={"resolution": "UHD", "fps": 60, "hdr": "HDR10"},
              power={"total_mw": 900.0, "cpu_mw": 200.0, "hw_mw": 300.0, "bw_mw": 400.0}, latency={"video_frames": 2.5})
    ref = {"mw": 850.0, "conditions": {"resolution": "UHD", "fps": 30, "hdr": "SDR"},
           "split": {"cpu_mw": 180.0, "ip_mw": 320.0, "bw_mw": 350.0}, "latency_frames": 2.0}
    out = compare_previous(cur, ref)
    assert [d["key"] for d in out["cond_diff"]] == ["fps", "hdr"] and out["spec_up"] == ["fps 30→60", "SDR→HDR10"]
    assert out["decomp"] == {"CPU": 20.0, "IP": -20.0, "BW": 50.0, "기준 차이": 0.0} and out["latency_delta_frames"] == 0.5
    assert compare_previous(cur, {"mw": 850.0})["cond_diff"] is None      # explicit value: nothing to compare


def test_spec_up_without_headroom_and_condition_diff_risks():
    up = row("a", 700.0, conditions={"fps": 60}, distribution={"total_mw": {"min": 690.0, "max": 710.0}})
    same = row("b", 500.0, conditions={"fps": 30, "sensor_board": "new"})
    s = snap(scenarios=[up, same], references={"a": {"mw": 600.0, "source": "prediction", "conditions": {"fps": 30}},
                                                "b": {"mw": 600.0, "source": "prediction", "conditions": {"fps": 30, "sensor_board": "old"}}})
    risks = {r["key"]: r for r in build_risks(s)}
    assert risks["spec_up_no_headroom"]["affected"] == ["a"] and risks["spec_up_no_headroom"]["severity"] == "high"
    assert risks["reference_condition_diff"]["affected"] == ["b"]
    assert all(isinstance(r["priority"], int) for r in risks.values()) and risks["spec_up_no_headroom"]["decision_needed"]


def test_sw_growth_budget_and_priority_order():
    rows = [row("kpi", sw={"growth_tolerance": 1.1}), row("other", sw={"growth_tolerance": 1.3})]
    s = snap(scenarios=rows, review_context={"policy": {"throughput_model": "pipelined", "sw_growth_budget": 1.2,
                                                        "kpi": [{"variant_ref": "kpi", "tier": "thermal"}]}, "rows": []})
    r = next(x for x in build_risks(s) if x["key"] == "sw_growth_budget")
    assert r["affected"] == ["kpi"] and "×1.2" in r["title"] and r["priority"] > 0


def test_data_quality_flags_identical_results_missing_conditions_and_kpi_gaps():
    from scenario_db.reporting.review_verdict import data_quality

    a = row("f1-fhd120", 691.0, conditions={"resolution": "FHD", "fps": 120}, bw_mbs=3687)
    b = row("f1-uhd120", 691.0, conditions={"resolution": "UHD", "fps": 120}, bw_mbs=3687)
    c = row("x", 500.0, conditions={"fps": 30})
    s = snap(scenarios=[a, b, c], review_context={"policy": {"kpi": [{"variant_ref": "apv"}]}, "rows": []})
    dq = {d["key"]: d for d in data_quality(s)}
    assert dq["identical_result"]["variants"] == ["f1-fhd120", "f1-uhd120"] and dq["missing_condition"]["variants"] == ["x"]
    assert dq["kpi_uncovered"]["level"] == "block"


def test_publish_blockers_use_kpi_scenario_scope_and_detect_ambiguous_ids():
    from scenario_db.api.services.arch_exploration import report_blockers

    s = snap(scenarios=[row('shared', scenario_id='other')], review_context={'policy': {'kpi': [
        {'variant_ref': 'shared', 'scenario_ref': 'required'}]}})
    assert report_blockers(s)[0]['key'] == 'kpi_uncovered'
    s['scenarios'].append(row('shared', scenario_id='required'))
    assert report_blockers(s) == []
    s['review_context']['policy']['kpi'][0].pop('scenario_ref')
    assert report_blockers(s)[0]['key'] == 'kpi_uncovered'


def test_sw_growth_at_tested_limit_is_unverified_rather_than_a_proven_failure():
    from scenario_db.reporting.review_summary import sw_table

    r = row('v', sw_margin_pct=2, sw={'growth_tolerance': 1.2, 'growth_tested_max': 1.2, 'hw_ms': 10})
    s = snap(scenarios=[r], review_context={'policy': {'sw_growth_budget': 1.5}})
    risks = {r['key']: r for r in build_risks(s)}
    assert 'sw_growth_budget' not in risks and risks['sw_growth_unverified']['validity'] == 'input_unverified'
    assert '예산까지 미검증' in sw_table(s) and '≥×1.20' in sw_table(s)
    r['sw']['growth_tested_max'] = 1.5
    risks = {r['key']: r for r in build_risks(s)}
    assert 'sw_growth_budget' in risks and 'sw_growth_unverified' not in risks
