"""Preview persistence must reject input drift and converge on one saved result."""
from uuid import uuid4

from sqlalchemy.orm import Session

from scenario_db.db.models.capability import SimConfigProfile
from scenario_db.db.models.definition import Scenario
from scenario_db.db.models.evidence import Evidence


def test_preview_save_rejects_profile_drift_and_deduplicates(api_client, engine):
    token = uuid4().hex
    cfg_id = f"simcfg-save-{token}"
    sid, vid = "uc-projecta-fhd30-recording", "UHD60-HDR10-H265"
    with Session(engine) as db:
        db.add(SimConfigProfile(id=cfg_id, schema_version="2.2", project_ref=db.get(Scenario, sid).project_ref,
                               run_config={"vbat": 4.0}, yaml_sha256="test"))
        db.commit()
    request = {"scenario_id": sid, "variant_id": vid, "config_profile_ref": cfg_id,
               "execution_context": {"silicon_rev": f"save-{token}", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "normal"}}
    evidence_id = None
    try:
        preview = api_client.post("/api/v1/simulation/run", json=request)
        assert preview.status_code == 200, preview.text
        original = preview.json()
        evidence_id = original["evidence_id"]
        assert not original["persisted"]
        save = request | {"persist": True, "expected_params_hash": original["params_hash"]}
        with Session(engine) as db:
            profile = db.get(SimConfigProfile, cfg_id)
            profile.run_config = {"vbat": 3.9}
            db.commit()
        for force in (False, True):
            rejected = api_client.post("/api/v1/simulation/run", json=save | {"force": force})
            assert rejected.status_code == 409, rejected.text
        with Session(engine) as db:
            assert db.get(Evidence, evidence_id) is None
            profile = db.get(SimConfigProfile, cfg_id)
            profile.run_config = {"vbat": 4.0}
            db.commit()
        saved = api_client.post("/api/v1/simulation/run", json=save)
        assert saved.status_code == 200, saved.text
        assert saved.json()["persisted"] and saved.json()["evidence_id"] == evidence_id
        assert saved.json()["params_hash"] == original["params_hash"] and saved.json()["kpi"] == original["kpi"]
        again = api_client.post("/api/v1/simulation/run", json=save).json()
        assert again["cached"] and again["persisted"] and again["evidence_id"] == evidence_id
    finally:
        with Session(engine) as db:
            if evidence_id:
                db.query(Evidence).filter_by(id=evidence_id).delete()
            db.query(SimConfigProfile).filter_by(id=cfg_id).delete()
            db.commit()
