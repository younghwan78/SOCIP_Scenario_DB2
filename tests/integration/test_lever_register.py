"""Lever selector -> prediction: IQ-keeping case, lossy needs a reason, options need IQ results and are re-explored."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.etl.loader import load_yaml_dir

ROOT = Path(__file__).resolve().parents[2]
SC, VAR = "uc-cam-recording-e2600", "cam-rec-r1-uhd30-vdis"


@pytest.fixture
def e2600(engine, api_client):
    with engine.connect() as connection:
        tx = connection.begin()
        previous = api_client.app.dependency_overrides[get_db]

        def test_db():
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                yield session

        api_client.app.dependency_overrides[get_db] = test_db
        try:
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                assert load_yaml_dir(ROOT / "db_Exynos2600_SM-S947B", session, strict=True, validate=True).ok
            yield api_client
        finally:
            api_client.app.dependency_overrides[get_db] = previous
            tx.rollback()


def test_lever_selection_registers_with_iq_results(e2600):
    c = e2600
    run = c.post("/api/v1/arch/exploration/runs", json={"scenario_ids": [SC], "variant_ids": [VAR], "project_ref": "proj-sm-s947b"})
    assert run.status_code == 200, run.text
    run = run.json()
    v = run["variants"][0]
    base = {"run_id": run["id"], "scenario_id": SC, "variant_id": VAR}
    keep = v["tiers"]["keep"]["best"]

    r = c.post("/api/v1/arch/predictions/lever", json=base | {"compression": keep["compression_modes"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rule"] == "lever:iq-keep" and body["promoted"][0]["total_mw"] == pytest.approx(keep["total_mw"], abs=0.01)

    lossy = {b: m.replace("LOSSLESS", "LOSSY") for b, m in keep["compression_modes"].items()}
    assert c.post("/api/v1/arch/predictions/lever", json=base | {"compression": lossy}).status_code == 422

    opts = ["knob:pyramid_l0=skip"]
    no_iq = c.post("/api/v1/arch/predictions/lever", json=base | {"compression": {}, "options": opts})
    assert no_iq.status_code == 422 and "IQ" in no_iq.text

    rejected = c.post("/api/v1/arch/predictions/lever", json=base | {"compression": {}, "options": opts,
        "iq_results": [{"option_key": opts[0], "status": "rejected", "note": "eval #1 detail loss"}]}).json()
    assert rejected["status"] == "rejected" and rejected["promoted"] == []

    adopted = c.post("/api/v1/arch/predictions/lever", json=base | {"compression": {"PYRAMID_L1": "COMP_YUV_LOSSLESS"}, "options": opts,
        "iq_results": [{"option_key": opts[0], "status": "adopted", "note": "eval #2 OK"}]})
    assert adopted.status_code == 200, adopted.text
    a = adopted.json()
    assert a["rule"] == "lever:iq-adopted" and a["run_id"] != run["id"]
    point = next(p for p in v["levers"]["points"] if p["option_keys"] == opts and p["comp"] == {"PYRAMID_L1": "COMP_YUV_LOSSLESS"})
    assert a["promoted"][0]["total_mw"] == pytest.approx(point["total_mw"], abs=0.05)   # re-explored = the evaluated point
    pred = c.get(f"/api/v1/arch/predictions/{a['promoted'][0]['id']}").json()
    sel = (pred.get("metrics") or {}).get("lever_selection") or {}
    assert sel.get("options") == opts and sel["iq_results"][opts[0]]["status"] == "adopted"
    reviews = c.get("/api/v1/arch/power-options/reviews", params={"scenario_id": SC}).json()
    assert any(rv["option_key"] == opts[0] and rv["status"] == "adopted" for rv in reviews)
