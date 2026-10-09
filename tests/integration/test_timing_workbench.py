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
