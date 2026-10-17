"""Automatic review risks (RPT-04) from a frozen snapshot."""
from scenario_db.reporting.risk_rules import build_risks, risk_counts


def _snap(**kw):
    base = {"overview": {"sample_dvfs": False}, "spec_summary": {"explored": 4, "failed": [], "errors": []},
            "review_context": {"policy": {"throughput_model": "pipelined"}, "rows": []}, "sw_margin_top5": []}
    return base | kw


def test_rules_and_severity_order():
    snap = _snap(
        spec_summary={"explored": 4, "errors": [], "failed": [{"variant_id": "cam-rec-r1-uhd120", "reasons": ["nrt"],
                                                                "explained": [{"text": "SW 11.1 ms > 8.33 ms", "action": "2-frame batch"}]}]},
        review_context={"policy": {"throughput_model": "pipelined"}, "rows": [
            {"variant_id": "cam-rec-r1-uhd30-vdis", "total_mw": 788.0, "reference": {"status": "over", "delta_pct": 27.1}}]},
        reference_check={"total": 4, "missing": ["cam-rec-apv-uhd60"]},
        thermal={"items": [{"variant_id": "cam-rec-r1-uhd30-portrait", "current_mw": 584,
                            "plans": [{"ask_pct": 10, "need_mw": -58.4, "saving_mw": -34.6, "achieved": False},
                                      {"ask_pct": 20, "need_mw": -116.7, "saving_mw": -34.6, "achieved": False}]},
                           {"variant_id": "cam-rec-x", "current_mw": 500,
                            "plans": [{"ask_pct": 10, "need_mw": -50, "saving_mw": -60, "achieved": True},
                                      {"ask_pct": 20, "need_mw": -100, "saving_mw": -60, "achieved": False}]},
                           {"variant_id": "cam-rec-r1-uhd120", "current_mw": None, "plans": []}]},
        sw_margin_top5=[{"variant_id": "cam-rec-f1-fhd60", "margin_pct": 0.0, "stage": "nrt", "bottleneck": "post_irta"}],
        model={"bias": {"cpu": {"verdict": "model_common", "median": -60.9}, "bw": {"verdict": "model_common", "median": 76.6},
                        "ip": {"verdict": "scenario", "median": -22}}, "offsetting": 20,
               "coverage": {"origin": {"physical_capture": 0, "synthetic": 53}}},
        overview={"sample_dvfs": True, "dvfs_table_ref": "dvfs-sample"},
    )
    r = build_risks(snap)
    keys = [x["key"] for x in r]
    assert keys[0] == "fps_drop" and r[0]["severity"] == "critical" and r[0]["mitigation"] == "2-frame batch"
    assert "pipelined" in r[0]["title"]
    sev = {x["key"]: x["severity"] for x in r}
    assert sev == {"fps_drop": "critical", "power_over_reference": "high", "reference_missing": "high", "thermal_10": "high",
                   "thermal_20": "medium", "thermal_unassessed": "medium", "sw_margin_low": "medium", "model_bias": "medium",
                   "sample_input": "info"}
    # −20 % is reported only for a variant whose −10 % is reachable
    assert next(x for x in r if x["key"] == "thermal_20")["affected"] == ["cam-rec-x"]
    assert "CPU -61%" in next(x for x in r if x["key"] == "model_bias")["title"]
    assert risk_counts([x | {"status": "open", "auto_state": "active"} for x in r]) == {"critical": 1, "high": 3, "medium": 4, "info": 1}


def test_clean_snapshot_has_no_risk():
    assert build_risks(_snap()) == []


def test_register_view_keeps_recent_history_and_orders_active_risks_first():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from scenario_db.api.services.review_risks import _order, risk_view

    now = datetime.now(UTC)
    row = SimpleNamespace(id='risk', seq=3, project_ref='project', risk_key='fps', rule='fps',
                          severity='critical', category='performance', title='FPS', detail='proof',
                          affected=['variant'], mitigation=None, owner='owner', status='open', note=None,
                          auto_state='active', first_seen_at=now, last_seen_at=now, updated_at=now,
                          updated_by='reviewer', last_report_ref='report', history=[{'n': n} for n in range(30)])
    view = risk_view(row, trend='ongoing')
    assert view['label'] == 'R-03' and view['updated_at'] == now.isoformat()
    assert view['history'] == [{'n': n} for n in range(10, 30)]
    view['affected'].append('another')
    assert row.affected == ['variant']
    rows = [view | {'id': 'closed', 'status': 'closed'},
            view | {'id': 'candidate', 'auto_state': 'resolve_candidate'},
            view | {'id': 'active', 'severity': 'high'}]
    assert [r['id'] for r in _order(rows)] == ['active', 'candidate', 'closed']
