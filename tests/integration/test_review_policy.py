from uuid import uuid4

import pytest

from sqlalchemy.orm import Session

from scenario_db.api.schemas.arch_exploration import PromoteRequest
from scenario_db.api.services import arch_exploration as svc
from scenario_db.api.services import review
from scenario_db.api.services.review_policy import project_policy, scenario_policy
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.exploration import ArchExplorationRun, Prediction
from tests.integration.test_arch_exploration import summary
from tests.integration.test_arch_exploration import stored_run as stored_run
from scenario_db.exceptions import UnprocessableError


def test_previous_project_reference_does_not_guess_between_scenarios(engine, stored_run):
    rid, _ = stored_run
    with Session(engine) as db:
        svc.promote(db, PromoteRequest(run_id=rid))
        project = db.get(Project, db.get(ArchExplorationRun, rid).project_ref)
        original = project.globals_
        try:
            project.globals_ = {"review_policy": {"power_reference": {"project_ref": project.id}}}
            db.commit()
            assert "shared" not in review.power_references(db, project.id)["references"]
        finally:
            project.globals_ = original
            db.commit()


def test_policy_registers_the_iq_keeping_case_and_builds_the_thermal_watch(engine):
    token = uuid4().hex[:10]
    pid, sid, rid = f"proj-rp-{token}", f"uc-rp-{token}", f"EXP-rp-{token}"
    policy = {"throughput_model": "pipelined", "register_baseline": "iq_keep",
              "power_reference": {"values_mw": {"shared": 11.0}, "tolerance_pct": 5},
              "thermal_watch": [{"scenario_ref": sid, "variant_ref": "shared", "label": "watch", "reduction_pct": [10, 30]}]}
    s = summary(sid, 10)
    keep = dict(s["recommended"]) | {"key": "keep", "total_mw": 12.0, "cpu_mw": 12.0}
    s["recommended"] = s["recommended"] | {"lossy": True, "compression": ["BUF"]}
    s["tiers"] = {"keep": {"best": keep}, "trade": {"best": s["recommended"]}, "trade_gain": {"delta_mw": -2.0}}
    s["power_options"] = {"status": "ok", "results": [], "best": None, "marginal": [
        {"key": "knob:k=v", "label": "K", "dimension": "knob:k", "mean_mw": -1.0, "min_mw": -1.2, "max_mw": -0.8,
         "always_beneficial": True}]}
    s["throughput_model"] = "pipelined"
    with Session(engine) as db:
        soc = db.query(Project.metadata_).first()[0]["soc_ref"]
        db.add(Project(id=pid, schema_version="2.2", metadata_={"name": "rp", "soc_ref": soc},
                       globals_={"review_policy": policy}, yaml_sha256="test"))
        db.flush()
        db.add(Scenario(id=sid, project_ref=pid, schema_version="1.0.0", metadata_={}, pipeline={}, yaml_sha256="test"))
        db.flush()
        db.add(ScenarioVariant(scenario_id=sid, id="shared", design_conditions={}))
        db.add(ArchExplorationRun(id=rid, title="rp", scenario_type="rp", project_ref=pid,
                                 spec={"objective": {}, "axes": {}, "constraints": {}}, variants=[s], errors=[],
                                 summary={"variants": 1}, engine_rev="test", input_hash="test"))
        db.commit()
    try:
        with Session(engine) as db:
            assert project_policy(db, pid).throughput_model == "pipelined"
            assert scenario_policy(db, sid).register_baseline == "iq_keep"
            out = svc.promote(db, PromoteRequest(run_id=rid))
            pred = db.get(Prediction, out["promoted"][0]["id"])
            assert pred.selection_rule == "auto:min-power-iq" and pred.selected_by == "auto"
            assert pred.metrics["power"]["total_mw"] == 12.0 and pred.metrics["throughput_model"] == "pipelined"
            fresh = svc.prediction_freshness(db, scenario_id=sid)["rows"][0]   # PRED-04
            assert fresh["status"] == "stale" and any("engine" in r for r in fresh["reasons"])  # fixture run engine_rev="test"
            board = svc.board(db, scenario_id=sid)["rows"][0]
            assert board["throughput_model"] == "pipelined"

            refs = review.power_references(db, pid)
            assert refs["references"]["shared"]["mw"] == 11.0 and refs["tolerance_pct"] == 5
            tw = review.thermal_watch(db, pid)
            item = tw["items"][0]
            assert item["baseline"] == "iq_keep" and item["current_mw"] == 12.0 and not item["registered_lossy"]
            assert item["reference"]["status"] == "over"          # 12 vs 11 = +9.1 % > 5 %
            assert [m["key"] for m in item["menu"]] == ["lossy", "knob:k=v"]
            assert item["plans"][0]["achieved"] and item["plans"][0]["picked"] == ["lossy"]
            assert not item["plans"][1]["achieved"] and any("부족" in n for n in item["notes"])

            # A different simulation baseline must not contribute savings to this baseline.
            mismatched = review.thermal_watch(db, pid, dvfs_whatif=lambda *_: {
                "base": {"total_mw": 100}, "rows": [{"domain": "CAM", "shift": -1, "level": 5,
                "mhz": 333, "verdict": "ok", "delta_mw": -50}]})
            assert not any(m["kind"] == "dvfs" for m in mismatched["items"][0]["menu"])

            # IQ policy never silently falls back to the lossy optimum.
            run = db.get(ArchExplorationRun, rid)
            run.variants = [s | {"tiers": {"keep": None}}]
            db.commit()
            assert not svc.promote(db, PromoteRequest(run_id=rid))["promoted"]
            assert db.get(Prediction, pred.id).status == "current"

            # A watch list cannot import another project's scenario.
            project = db.get(Project, pid)
            other_sid = db.query(Scenario.id).filter(Scenario.project_ref != pid).first()[0]
            project.globals_ = {"review_policy": policy | {"thermal_watch": [{"scenario_ref": other_sid, "variant_ref": "shared"}]}}
            db.commit()
            with pytest.raises(UnprocessableError, match="selected project"):
                review.thermal_watch(db, pid)
    finally:
        with Session(engine) as db:
            db.query(Prediction).filter(Prediction.scenario_ref == sid).delete(synchronize_session=False)
            db.query(ArchExplorationRun).filter_by(id=rid).delete()
            db.query(ScenarioVariant).filter(ScenarioVariant.scenario_id == sid).delete(synchronize_session=False)
            db.query(Scenario).filter_by(id=sid).delete()
            db.query(Project).filter_by(id=pid).delete()
            db.commit()
