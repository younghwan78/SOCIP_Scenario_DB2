"""Timing Budget as the prediction workbench: SW-variance spread, condition evidence, condition registration."""

from sqlalchemy.orm import Session

from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import Prediction

S, V = "uc-projecta-fhd30-recording", "FHD30-recording"
CTX = {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "nominal", "method": "calculation"}


def test_condition_evidence_register_and_board(api_client, engine):
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
