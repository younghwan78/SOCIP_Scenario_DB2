"""Timing Budget as the prediction workbench: SW-variance spread, condition evidence, condition registration."""

from sqlalchemy.orm import Session

from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import Prediction

S, V = "uc-projecta-fhd30-recording", "FHD30-recording"
CTX = {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "nominal", "method": "calculation"}


def test_condition_evidence_register_and_board(api_client, engine, demo_cleanup):
    base = {"scenario_id": S, "variant_id": V, "options": {"statistic": "max"}}
    rep = api_client.post("/api/v1/timing-budget/variant", json=base)
    assert rep.status_code == 200, rep.text
    dvfs = rep.json()["report"]["dvfs"]
    assert dvfs["overrides"] == {} and isinstance(dvfs["ladders"], dict)

    dist = api_client.post("/api/v1/timing-budget/interval-distribution", json={**base, "trials": 2, "frames": 10})
    assert dist.status_code == 200, dist.text
    assert dist.json()["warmup_excluded"] == 2

    ev = api_client.post("/api/v1/timing-budget/evidence", json={**base, "execution_context": CTX})
    assert ev.status_code == 200, ev.text
    body = ev.json()
    assert body["total_mw"] == rep.json()["report"]["power"]["total_mw"]
    again = api_client.post("/api/v1/timing-budget/evidence", json={**base, "execution_context": CTX}).json()
    assert again["evidence_id"] == body["evidence_id"] and again["existed"] is True
    with Session(engine) as db:
        row = db.get(Evidence, body["evidence_id"])
        assert row is not None and row.run_info["tool"] == "scenariodb-timing-budget" and row.timeline_events

    reg = api_client.post("/api/v1/timing-budget/register", json={**base, "reason": "workbench test"})
    if reg.status_code == 422:   # the demo variant may fail its timing at max; the refusal names the spec reason
        assert "spec" in reg.json()["detail"]
        return
    assert reg.status_code == 200, reg.text
    pid = reg.json()["promoted"][0]["id"]
    with Session(engine) as db:
        p = db.get(Prediction, pid)
        assert p.selection_rule == "manual:timing-budget" and p.reason == "workbench test"
    rows = api_client.get("/api/v1/arch/predictions/board", params={"scenario_id": S}).json()["rows"]
    cond = next(r for r in rows if r["id"] == pid)["condition"]
    assert cond["source"] == "timing-budget" and cond["statistic"] == "max" and cond["dvfs_overrides"] == {}
    fresh = api_client.get("/api/v1/arch/predictions/freshness", params={"scenario_id": S}).json()["rows"]
    assert next(r for r in fresh if r["prediction_id"] == pid)["status"] == "fresh"


def test_measurement_as_input_and_reference(api_client, demo_cleanup):
    """S4: measured-inputs listing, compare-only reference and measured SW runtime as input."""
    v = "UHD60-HDR10-H265"
    opts = api_client.get("/api/v1/timing-budget/measured-inputs", params={"scenario_id": S, "variant_id": v})
    assert opts.status_code == 200, opts.text
    meas = next(o for o in opts.json() if o["id"].startswith("meas-uc-projecta-fhd30-recording-UHD60-HDR10-H265-EVT0"))
    assert "eis_warp" in meas["sw_tasks"]
    base = {"scenario_id": S, "variant_id": v, "options": {"statistic": "mean"}}
    ref = api_client.post("/api/v1/timing-budget/variant", json={**base, "measured": {"measurement_ref": meas["id"]}})
    assert ref.status_code == 200, ref.text
    cmp_ = ref.json()["report"]["measured_compare"]
    assert cmp_["measurement_ref"] == meas["id"] and cmp_["inputs"] == {"sw": False, "clock": False, "cpu": False}
    assert {r["category"] for r in cmp_["rows"]} == {"cpu", "ip", "bw", "other"}
    used = api_client.post("/api/v1/timing-budget/variant", json={**base, "measured": {"measurement_ref": meas["id"], "sw": True}})
    assert used.status_code == 200, used.text
    assert used.json()["report"]["condition"]["task_runtime"]
    wrong = api_client.post("/api/v1/timing-budget/variant",
                            json={**base, "variant_id": V, "measured": {"measurement_ref": meas["id"], "sw": True}})
    assert wrong.status_code == 422      # a measurement of another variant is refused
    for endpoint, extra in (("evidence", {"execution_context": CTX}), ("register", {"reason": "foreign reference"})):
        wrong = api_client.post(f"/api/v1/timing-budget/{endpoint}",
                                json=base | {"variant_id": V, "measured": {"measurement_ref": meas["id"]}} | extra)
        assert wrong.status_code == 422, wrong.text


def test_intentional_dvfs_override_is_registered_as_is(api_client, demo_cleanup):
    """A DVFS level the user pins on purpose is part of the registered condition (and its prediction levels)."""
    base = {"scenario_id": S, "variant_id": V, "options": {"statistic": "mean"}}
    ips = api_client.post("/api/v1/timing-budget/variant", json=base).json()["report"]["ips"]
    groups = sorted({ip["dvfs_group"] for ip in ips if ip.get("dvfs_group")})
    assert groups
    # explicit DVFS tables for the demo (fixture ships none): three levels per domain, ASV group 4
    tables = {g: {"domain": g, "levels": [{"level": 0, "speed_mhz": 1200, "voltages": {"4": 850}},
                                          {"level": 1, "speed_mhz": 800, "voltages": {"4": 750}},
                                          {"level": 2, "speed_mhz": 400, "voltages": {"4": 650}}]} for g in groups}
    base = base | {"dvfs_tables": tables}
    rep = api_client.post("/api/v1/timing-budget/variant", json=base).json()["report"]
    dom = groups[0]
    assert [x["level"] for x in rep["dvfs"]["ladders"][dom]] == [2, 1, 0]
    body = {**base, "config": {"dvfs_overrides": {dom: 0}}, "reason": "pin fastest level on purpose"}
    pinned = api_client.post("/api/v1/timing-budget/variant", json=body).json()["report"]
    assert pinned["dvfs"]["overrides"] == {dom: 0}
    reg = api_client.post("/api/v1/timing-budget/register", json=body)
    if pinned["verdict"]["status"] == "fail":
        assert reg.status_code == 422      # a failing condition is never registered (fps drop)
        return
    assert reg.status_code == 200, reg.text
    pid = reg.json()["promoted"][0]["id"]
    row = next(r for r in api_client.get("/api/v1/arch/predictions/board", params={"scenario_id": S}).json()["rows"] if r["id"] == pid)
    assert row["condition"]["dvfs_overrides"] == {dom: 0} and row["dvfs"][dom] == 0
    assert row["selection_rule"] == "manual:timing-budget" and row["reason"] == "pin fastest level on purpose"


def test_condition_save_and_register_reject_input_drift(api_client, engine):
    from uuid import uuid4

    from scenario_db.db.models.capability import SimConfigProfile
    from scenario_db.db.models.definition import Scenario

    cfg = f"simcfg-timing-{uuid4().hex}"
    with Session(engine) as db:
        db.add(SimConfigProfile(id=cfg, schema_version="2.2", project_ref=db.get(Scenario, S).project_ref,
                               run_config={"vbat": 4.0}, yaml_sha256="test"))
        db.commit()
    base = {"scenario_id": S, "variant_id": V, "config_profile_ref": cfg}
    ids = []
    try:
        preview = api_client.post("/api/v1/timing-budget/variant", json=base).json()["report"]
        expected = preview["condition_hash"]
        # Drawing more frames is not a new physical condition.
        drawn = api_client.post("/api/v1/timing-budget/variant", json=base | {"options": {"timeline_frames": 20}}).json()
        assert drawn["report"]["condition_hash"] == expected
        saved = api_client.post("/api/v1/timing-budget/evidence", json=base | {"execution_context": CTX, "expected_condition_hash": expected})
        assert saved.status_code == 200, saved.text
        ids.append(saved.json()["evidence_id"])
        with Session(engine) as db:
            row = db.get(SimConfigProfile, cfg)
            row.run_config = {"vbat": 3.9}
            db.commit()

        for endpoint, extra in (("evidence", {"execution_context": CTX}), ("register", {"reason": "stale condition"})):
            rejected = api_client.post(f"/api/v1/timing-budget/{endpoint}", json=base | extra | {"expected_condition_hash": expected})
            assert rejected.status_code == 409, rejected.text
        # An explicit fresh save gets a new id rather than returning the old row.
        new = api_client.post("/api/v1/timing-budget/evidence", json=base | {"execution_context": CTX})
        assert new.status_code == 200, new.text
        ids.append(new.json()["evidence_id"])
        assert ids[0] != ids[1] and not new.json()["existed"]
        with Session(engine) as db:
            evidence = db.get(Evidence, ids[1])
            assert evidence.kpi["total_power_mw"] == evidence.power_breakdown["total_mw"]
            assert abs(evidence.kpi["total_power_ma"] * 3.9 - evidence.kpi["total_power_mw"]) < 1e-6
    finally:
        with Session(engine) as db:
            db.query(Evidence).filter(Evidence.id.in_(ids)).delete()
            db.query(SimConfigProfile).filter_by(id=cfg).delete()
            db.commit()



def test_measured_sw_drift_is_stale_and_evidence_retains_source(api_client, engine):
    from uuid import uuid4

    from scenario_db.db.models.definition import Scenario
    from scenario_db.db.models.exploration import ArchExplorationRun

    ref = f"meas-timing-{uuid4().hex}"
    base = {"scenario_id": S, "variant_id": V,
            "options": {"statistic": "mean", "runtime_scale": 0.1, "throughput_model": "pipelined", "warmup_frames": 4}}
    report = api_client.post("/api/v1/timing-budget/variant", json=base).json()["report"]
    task = next(i["task"] for s in report["stages"] for i in s["sw_items"] if i["kind"] == "sw")
    groups = {i["dvfs_group"] for i in report["ips"] if i.get("dvfs_group")}
    base["dvfs_tables"] = {g: {"domain": g, "levels": [{"level": 0, "speed_mhz": 1200, "voltages": {"4": 850}}]} for g in groups}
    base["measured"] = {"measurement_ref": ref, "sw": True}
    pid = rid = eid = None
    with Session(engine) as db:
        db.add(Evidence(id=ref, schema_version="2.2", kind="evidence.measurement", scenario_ref=S, variant_ref=V,
                        project_ref=db.get(Scenario, S).project_ref, execution_context=CTX, aggregation={"strategy": "single_run"},
                        kpi={"total_power_mw": 1000}, yaml_sha256="test",
                        sw_task_timing=[{"task": task, "mean_ms": 2, "min_ms": 1, "max_ms": 3}]))
        db.commit()
    try:
        preview = api_client.post("/api/v1/timing-budget/variant", json=base)
        assert preview.status_code == 200, preview.text
        rep = preview.json()["report"]
        assert rep["verdict"]["status"] != "fail", rep["verdict"]
        runtime = next(i["runtime_ms"] for s in rep["stages"] for i in s["sw_items"] if i["task"] == task)
        assert abs(runtime - 0.2) < 0.001
        guarded = base | {"expected_condition_hash": rep["condition_hash"]}
        reg = api_client.post("/api/v1/timing-budget/register", json=guarded | {"reason": "measured input regression"})
        assert reg.status_code == 200, reg.text
        pid, rid = reg.json()["promoted"][0]["id"], reg.json()["run_id"]
        fresh = api_client.get("/api/v1/arch/predictions/freshness", params={"scenario_id": S}).json()["rows"]
        assert next(r for r in fresh if r["prediction_id"] == pid)["status"] == "fresh"
        saved = api_client.post("/api/v1/timing-budget/evidence", json=guarded | {"execution_context": CTX})
        assert saved.status_code == 200, saved.text
        eid = saved.json()["evidence_id"]
        with Session(engine) as db:
            ev = db.get(Evidence, eid)
            assert ref in ev.derived_from and ev.run_info["timing_budget"]["measured"]["measurement_ref"] == ref
            assert ev.kpi["total_power_mw"] == rep["power"]["total_mw"]
            measurement = db.get(Evidence, ref)
            measurement.sw_task_timing = [{"task": task, "mean_ms": 3, "min_ms": 1, "max_ms": 4}]
            db.commit()
        fresh = api_client.get("/api/v1/arch/predictions/freshness", params={"scenario_id": S}).json()["rows"]
        assert next(r for r in fresh if r["prediction_id"] == pid)["status"] == "stale"
        for endpoint, extra in (("evidence", {"execution_context": CTX}), ("register", {"reason": "stale measurement"})):
            response = api_client.post(f"/api/v1/timing-budget/{endpoint}", json=guarded | extra)
            assert response.status_code == 409, response.text
    finally:
        with Session(engine) as db:
            if pid:
                db.query(Prediction).filter_by(id=pid).delete()
            if rid:
                db.query(ArchExplorationRun).filter_by(id=rid).delete()
            db.query(Evidence).filter(Evidence.id.in_([ref, eid] if eid else [ref])).delete()
            db.commit()
