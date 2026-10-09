"""S5 end to end: fit -> new draft params version (base untouched) -> the new params change the prediction -> recompute."""

from uuid import uuid4

import pytest
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
    assert hw(new["params_ref"]) == pytest.approx(hw(base_ref) * k_ip, rel=1e-3)
    listed = api_client.get("/api/v1/calibration/power-params", params={"soc_ref": "soc-exynos2500"}).json()
    assert any(p["ref"] == new["params_ref"] and p["calibrated"] for p in listed)

    reg = api_client.post("/api/v1/timing-budget/register", json={"scenario_id": S, "variant_id": "FHD30-recording", "options": {"statistic": "mean", "runtime_scale": 0.1},
                                                                   "config": {"power_params_ref": base_ref}, "reason": "base"})
    assert reg.status_code == 200, reg.text
    old = reg.json()["promoted"][0]["id"]
    rc = api_client.post(f"/api/v1/arch/predictions/{old}/recompute", params={"power_params_ref": new["params_ref"]})
    assert rc.status_code == 200, rc.text
    out = rc.json()
    assert out["status"] == "recomputed" and out["new_prediction_id"] != old
    row = next(r for r in api_client.get("/api/v1/arch/predictions/board", params={"scenario_id": S}).json()["rows"] if r["id"] == out["new_prediction_id"])
    assert row["condition"]["power_params_ref"] == new["params_ref"] and row["previous"]["id"] == old


def test_params_validate_scope_lineage_and_scale_existing_ip_factors(api_client, engine):
    from scenario_db.db.models.evidence import Evidence

    pid = f"pmp-scope-{uuid4().hex[:6]}"
    with Session(engine) as db:
        db.add(Row(id=pid, schema_version="2.2", soc_ref="soc-exynos2500", version=1, status="draft",
                   params={"calibration": {"ip_power_scale": {"*": 1.2, "mfc": 0.8}}}, yaml_sha256="test"))
        db.commit()
        measurement = db.query(Evidence).filter(Evidence.kind == "evidence.measurement", Evidence.scenario_ref == S).first()
        ref = f"meas-fit-{uuid4().hex}"
        db.add(Evidence(id=ref, schema_version="2.2", kind="evidence.measurement", scenario_ref=S,
                        variant_ref=measurement.variant_ref, execution_context=measurement.execution_context,
                        aggregation=measurement.aggregation, kpi=measurement.kpi, vdd_power=measurement.vdd_power,
                        provenance={"data_origin": "synthetic"}, yaml_sha256="test"))
        db.commit()
    bad = api_client.post("/api/v1/calibration/power-params", json={"base_params_ref": f"{pid}@bad", "factors": {"ip": 0.5}})
    assert bad.status_code == 422
    bad = api_client.post("/api/v1/calibration/power-params", json={"base_params_ref": pid, "factors": {"ip": 0.5}, "source_evidence": ["missing"]})
    assert bad.status_code == 422
    new = api_client.post("/api/v1/calibration/power-params", json={"base_params_ref": pid, "factors": {"ip": 0.5}, "source_evidence": [ref], "synthetic_rows": 0})
    assert new.status_code == 200, new.text
    with Session(engine) as db:
        calibration = db.get(Row, new.json()["id"]).params["calibration"]
        assert calibration["ip_power_scale"] == {"*": 0.6, "mfc": 0.4}
        assert calibration["fit"]["synthetic_rows"] == 1
    wrong = api_client.post("/api/v1/calibration/power-fit", json={"project_ref": "missing", "base_params_ref": pid})
    assert wrong.status_code == 404
    with Session(engine) as db:
        db.delete(db.get(Evidence, ref))
        db.commit()
