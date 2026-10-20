from uuid import uuid4

import pytest

from sqlalchemy.orm import Session

from scenario_db.api.services import analysis_inputs
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


def test_freshness_replays_explicit_settings_and_preserves_throughput_override(engine, stored_run, monkeypatch):
    from scenario_db.sim import arch_exploration as ax

    rid, ids = stored_run
    calls = []
    def load(selection, _db):
        shim, defaults = selection.request, selection.use_default_dvfs
        calls.append((shim.config.vbat, shim.dvfs_table_ref, defaults))
        return analysis_inputs.AnalysisInputs(object(), {}, None)
    monkeypatch.setattr(analysis_inputs.AnalysisSelection, "load", load)
    monkeypatch.setattr(ax, "input_manifest", lambda _g, cfg, _t, *, timing: (
        {"config": str(cfg.vbat), "timing_inputs": timing.throughput_model}, {}))
    with Session(engine) as db:
        run = db.get(ArchExplorationRun, rid)
        run.engine_rev = svc.ENGINE_REV
        run.spec = run.spec | {"input_selection": {"config": {"vbat": 3.9}, "dvfs_table_ref": "dvfs-explicit",
                               "use_default_dvfs": False}, "timing": {"throughput_model": "stage"}, "throughput_from_policy": False}
        run.variants = [s | {"input_sections": {"config": "3.9", "timing_inputs": "stage"}, "throughput_model": "stage"}
                        for s in run.variants]
        project = db.get(Project, run.project_ref)
        original = project.globals_
        try:
            project.globals_ = {"review_policy": {"throughput_model": "pipelined"}}
            db.commit()
            svc.promote(db, PromoteRequest(run_id=rid))
            assert svc.prediction_freshness(db, scenario_id=ids[0])["rows"][0]["status"] == "fresh"
            assert calls[-1] == (3.9, "dvfs-explicit", False)
            run.spec = run.spec | {"input_selection": {"config": {"vbat": 4.0}, "use_default_dvfs": False}}
            db.commit()
            changed = svc.prediction_freshness(db, scenario_id=ids[0])["rows"][0]
            assert changed["status"] == "stale" and changed["changed"] == ["config"]
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


def test_previous_project_silicon_measurement_wins_over_its_prediction(engine):
    """REF-01: a previous project in production is judged against its silicon, then its prediction, then synthetic."""
    from datetime import datetime, timezone

    from scenario_db.db.models.evidence import Evidence

    token = uuid4().hex[:10]
    prev, cur, sid, rid = f"proj-prev-{token}", f"proj-cur-{token}", f"uc-prev-{token}", f"EXP-prev-{token}"
    with Session(engine) as db:
        soc = db.query(Project.metadata_).first()[0]["soc_ref"]
        db.add(Project(id=prev, schema_version="2.2", metadata_={"name": "prev", "soc_ref": soc}, yaml_sha256="test"))
        db.add(Project(id=cur, schema_version="2.2", metadata_={"name": "cur", "soc_ref": soc}, yaml_sha256="test",
                       globals_={"review_policy": {"power_reference": {"project_ref": prev, "tolerance_pct": 3}}}))
        db.flush()
        db.add(Scenario(id=sid, project_ref=prev, schema_version="1.0.0", metadata_={}, pipeline={}, yaml_sha256="test"))
        db.flush()
        for vid in ("both", "pred_only", "synthetic", "unknown"):
            db.add(ScenarioVariant(scenario_id=sid, id=vid, design_conditions={}))
        db.add(ArchExplorationRun(id=rid, title="prev", scenario_type="prev", project_ref=prev,
                                 spec={"objective": {}, "axes": {}, "constraints": {}},
                                 variants=[summary(sid, 10) | {"variant_id": v} for v in ("both", "pred_only", "synthetic")],
                                 errors=[], summary={"variants": 3}, engine_rev="test", input_hash="test"))
        db.flush()
        for vid, origin, mw in (("both", {"collection_method": "power_monitor", "device_id": "EVT1-01"}, 13.0),
                                ("synthetic", {"collection_method": "synthetic_fixture", "device_id": "SYNTHETIC"}, 7.0),
                                ("unknown", {}, 6.0)):
            db.add(Evidence(id=f"{sid}-{vid}", scenario_ref=sid, variant_ref=vid, project_ref=None, schema_version="1.0.0",
                            kind="evidence.measurement", measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc), provenance=origin,
                            execution_context={}, aggregation={}, kpi={"total_power_mw": mw}, yaml_sha256="test"))
        db.commit()
    try:
        with Session(engine) as db:
            svc.promote(db, PromoteRequest(run_id=rid))
            refs = review.power_references(db, cur)["references"]
            assert refs["both"]["source"] == "measurement" and refs["both"]["mw"] == 13.0
            assert refs["pred_only"]["source"] == "prediction"
            assert refs["synthetic"]["source"] == "prediction"   # synthetic measurements come last
            assert 'unknown' not in refs  # missing provenance cannot establish a baseline
            project = db.get(Project, cur)
            project.globals_ = {"review_policy": {"power_reference": {"project_ref": prev, "source_priority": ["prediction"]}}}
            db.commit()
            assert review.power_references(db, cur)["references"]["both"]["source"] == "prediction"
            # REF-02/03: conditions and power split of the previous variant; a mapping for a renamed variant
            db.query(ScenarioVariant).filter_by(scenario_id=sid, id="both").update({"design_conditions": {"fps": 30, "resolution": "UHD"}})
            project.globals_ = {"review_policy": {"power_reference": {"project_ref": prev, "mapping": {"renamed": "pred_only"}}}}
            db.commit()
            refs = review.power_references(db, cur)["references"]
            assert refs["both"]["conditions"] == {"fps": 30, "resolution": "UHD"} and refs["both"]["split"]["total_mw"] == 10
            assert refs["renamed"]["prev_variant"] == "pred_only" and refs["renamed"]["source"] == "prediction"
            assert 'pred_only' not in refs
            project.globals_ = {"review_policy": {"power_reference": {"project_ref": prev, "mapping": {"renamed": "missing"}}}}
            db.commit()
            with pytest.raises(UnprocessableError, match='mapping target'):
                review.power_references(db, cur)
    finally:
        with Session(engine) as db:
            db.query(Evidence).filter(Evidence.scenario_ref == sid).delete(synchronize_session=False)
            db.query(Prediction).filter(Prediction.scenario_ref == sid).delete(synchronize_session=False)
            db.query(ArchExplorationRun).filter_by(id=rid).delete()
            db.query(ScenarioVariant).filter(ScenarioVariant.scenario_id == sid).delete(synchronize_session=False)
            db.query(Scenario).filter_by(id=sid).delete()
            db.query(Project).filter(Project.id.in_([cur, prev])).delete(synchronize_session=False)
            db.commit()
