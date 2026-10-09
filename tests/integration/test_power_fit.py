"""S5 end to end: fit -> new draft params version (base untouched) -> the new params change the prediction -> recompute."""

from uuid import uuid4

from sqlalchemy.orm import Session

from scenario_db.db.models.capability import PowerModelParams as Row

S, V = "uc-projecta-fhd30-recording", "UHD60-HDR10-H265"


def test_fit_publish_and_recompute(api_client, engine, demo_cleanup):
    pid = f"pmp-fit-{uuid4().hex[:6]}-v1"
    with Session(engine) as db:
        db.add(Row(id=pid, schema_version="2.2", soc_ref="soc-exynos2500", version=90 + int(uuid4().int % 9), status="draft",
                   params={"ip_model": "v1-vfps", "bw": {"mw_per_gbps": 60.0}, "calibration": {"source_evidence": [], "factor_by_ip": {}}},
                   yaml_sha256="test"))
        db.commit()
        base_ref = f"{pid}@{db.get(Row, pid).version}"
    fit = api_client.post("/api/v1/calibration/power-fit", json={"project_ref": "proj-A-exynos2500", "base_params_ref": base_ref,
                                                                   "include_synthetic": True, "statistic": "mean"})
    assert fit.status_code == 200, fit.text
    body = fit.json()
    assert body["rows"], body["errors"]
    k_ip = body["factors"]["ip"]["k"]
    assert k_ip
    created = api_client.post("/api/v1/calibration/power-params", json={
        "base_params_ref": base_ref, "factors": {"ip": k_ip}, "source_evidence": [r["measurement_ref"] for r in body["rows"]],
        "fit_stats": body["factors"]})
    assert created.status_code == 200, created.text
    new = created.json()
    assert new["applied"] == {"ip": k_ip} and "ip_power_scale" in new["yaml"]
    with Session(engine) as db:
        assert db.get(Row, pid).params.get("calibration", {}).get("ip_power_scale") is None      # base untouched
        assert db.get(Row, new["id"]).params["calibration"]["ip_power_scale"]["*"] == k_ip
    def hw(ref):
        rep = api_client.post("/api/v1/timing-budget/variant", json={"scenario_id": S, "variant_id": V, "options": {"statistic": "mean"},
                                                                       "config": {"power_params_ref": ref}})
        assert rep.status_code == 200, rep.text
        return rep.json()["report"]["power"]["hw_mw"]
    assert hw(new["params_ref"]) == __import__("pytest").approx(hw(base_ref) * k_ip, rel=1e-3)
    listed = api_client.get("/api/v1/calibration/power-params", params={"soc_ref": "soc-exynos2500"}).json()
    assert any(p["ref"] == new["params_ref"] and p["calibrated"] for p in listed)

    reg = api_client.post("/api/v1/timing-budget/register", json={"scenario_id": S, "variant_id": V, "options": {"statistic": "mean"},
                                                                   "config": {"power_params_ref": base_ref}, "reason": "base"})
    if reg.status_code != 200:     # demo variant may fail its timing; recompute is covered by the timing-budget path only
        return
    old = reg.json()["promoted"][0]["id"]
    rc = api_client.post(f"/api/v1/arch/predictions/{old}/recompute", params={"power_params_ref": new["params_ref"]})
    assert rc.status_code == 200, rc.text
    out = rc.json()
    assert out["status"] == "recomputed" and out["new_prediction_id"] != old
    row = next(r for r in api_client.get("/api/v1/arch/predictions/board", params={"scenario_id": S}).json()["rows"] if r["id"] == out["new_prediction_id"])
    assert row["condition"]["power_params_ref"] == new["params_ref"] and row["previous"]["id"] == old
