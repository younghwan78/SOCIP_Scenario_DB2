from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from scenario_db.api.schemas.arch_exploration import ArchReportRequest, PowerOptionReviewRequest, PromoteRequest
from scenario_db.api.services import arch_exploration as svc
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.models.exploration import ArchExplorationRun, ArchReport, PowerOptionReview, Prediction
from scenario_db.exceptions import UnprocessableError
from scenario_db.sim.arch_exploration import DIST_KEYS


def summary(sid, value):
    case = dict.fromkeys(DIST_KEYS, 0.0) | {
        "key": "base", "total_mw": value, "cpu_mw": value, "compression": [], "dvfs": {},
        "dvfs_raise": 0, "statistic": "max", "runtime_scale": 1.0, "eligible": True,
        "verified": {"ok": True, "delta_pct": 0}, "lossy": False, "assumed_ratio": False,
    }
    obj = {"fps": 30, "period_ms": 33.333, "eis_on": False, "ips": [], "domains": [],
           "bw": {"total_mbs": 0, "hw_mbs": 0, "sw_mbs": 0},
           "power": {"bw_mw": 0, "bw_hw_mw": 0, "bw_sw_mw": 0}, "cpu_by_task": {"cpu": value},
           "verdict": {"status": "ok"}, "intervals": {}, "latency": {}, "stages": {}}
    return {"scenario_id": sid, "variant_id": "shared", "spec_ok": True, "spec_reasons": [],
            "recommended": case, "baseline": case, "alternatives": [], "buffers": [],
            "objective_slice": obj, "input_hash": sid, "distribution": {
                k: dict.fromkeys(("min", "p25", "median", "p75", "max"), case[k]) for k in DIST_KEYS},
            "counts": {"eligible": 1, "cases": 1}, "fps": 30, "eis_on": False,
            "sw_margin": {}, "warnings": [], "design_conditions": {}}


@pytest.fixture
def stored_run(engine):
    token = uuid4().hex
    ids = [f"uc-review-{token}-{i}" for i in range(2)]
    rid = f"EXP-test-{token}"
    with Session(engine) as db:
        project = db.query(Scenario.project_ref).first()[0]
        for sid in ids:
            db.add(Scenario(id=sid, project_ref=project, schema_version="1.0.0",
                            metadata_={"category": ["review"]}, pipeline={}, yaml_sha256="test"))
        db.flush()
        for sid in ids:
            db.add(ScenarioVariant(scenario_id=sid, id="shared", design_conditions={}))
        db.add(ArchExplorationRun(id=rid, title="Review", scenario_type="review", project_ref=project,
                                 spec={"objective": {}, "axes": {}, "constraints": {}},
                                 variants=[summary(ids[0], 10), summary(ids[1], 20)], errors=[],
                                 summary={"variants": 2}, engine_rev="test", input_hash="test"))
        db.commit()
    try:
        yield rid, ids
    finally:
        with Session(engine) as db:
            db.query(ArchReport).filter(ArchReport.exploration_run_refs.contains([rid])).delete(synchronize_session=False)
            db.query(PowerOptionReview).filter(PowerOptionReview.scenario_ref.in_(ids)).delete(synchronize_session=False)
            db.query(Prediction).filter(Prediction.scenario_ref.in_(ids)).delete(synchronize_session=False)
            db.query(ArchExplorationRun).filter_by(id=rid).delete()
            db.query(ScenarioVariant).filter(ScenarioVariant.scenario_id.in_(ids)).delete(synchronize_session=False)
            db.query(Scenario).filter(Scenario.id.in_(ids)).delete(synchronize_session=False)
            db.commit()


def test_promote_duplicate_variant_names_preserves_scenarios_and_report(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        result = svc.promote(db, PromoteRequest(run_id=rid))
        assert {p["scenario_id"] for p in result["promoted"]} == set(ids)
        board = svc.board(db)
        assert {r["power"]["total_mw"] for r in board["rows"] if r["scenario_id"] in ids} == {10, 20}
        report = svc.create_report(db, ArchReportRequest(run_id=rid, title="<script>alert(1)</script>"))
        values = {r["scenario_id"]: r["power"]["total_mw"] for r in report["snapshot"]["scenarios"]}
        assert values == dict(zip(ids, (10, 20)))
        html = svc.get_report(db, report["id"]).rendered_html
        assert "<script>" not in html and "&lt;script&gt;" in html
        assert not svc.report_stale(db, report["id"])["stale"]
        svc.set_report_status(db, report["id"], "published")
        assert svc.report_detail(svc.get_report(db, report["id"]))["status"] == "published"
        svc.promote(db, PromoteRequest(run_id=rid, scenario_id=ids[0], variant_ids=["shared", "shared"]))
        assert len(svc.history(db, ids[0], "shared")) == 2
        assert svc.report_stale(db, report["id"])["stale"]
        assert svc.compare(db, scenario_id=ids[0], variant_id="shared")["attribution"]["delta_mw"] == 0
        assert svc.report_detail(svc.get_report(db, report["id"]))["snapshot"] == report["snapshot"]


def test_report_classification_uses_run_snapshot_after_catalog_edit(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        run = db.get(ArchExplorationRun, rid)
        variants = deepcopy(run.variants)
        variants[0]['design_conditions'] = {'resolution': 'FHD', 'codec_mfc': 'H264'}
        run.variants = variants
        db.get(ScenarioVariant, (ids[0], 'shared')).design_conditions = {'resolution': 'UHD', 'codec_mfc': 'APV'}
        db.commit()
        report = svc.create_report(db, ArchReportRequest(run_id=rid))
        cls = report['snapshot']['scenarios'][0]['cls']
        assert cls['resolution'] == 'FHD' and cls['codec'] == 'H264'


def test_ambiguous_or_unrelated_prediction_selection_rejected(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        with pytest.raises(UnprocessableError, match="ambiguous"):
            svc.promote(db, PromoteRequest(run_id=rid, variant_ids=["shared"]))
        assert svc.promote(db, PromoteRequest(run_id=rid, variant_ids=[]))["promoted"] == []
        rows = svc.promote(db, PromoteRequest(run_id=rid))["promoted"]
        with pytest.raises(UnprocessableError, match="same scenario"):
            svc.compare(db, old_id=rows[0]["id"], new_id=rows[1]["id"])


def test_concurrent_first_promotions_form_one_current_history_chain(engine, stored_run):
    rid, ids = stored_run
    barrier = Barrier(2)

    def promote():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return svc.promote(db, PromoteRequest(run_id=rid, scenario_id=ids[0]))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(promote) for _ in range(2)]
        for future in futures:
            assert len(future.result(timeout=20)["promoted"]) == 1
    with Session(engine) as db:
        rows = db.query(Prediction).filter_by(scenario_ref=ids[0]).all()
        assert len(rows) == 2
        current = [r for r in rows if r.status == "current"]
        assert len(current) == 1 and current[0].supersedes_ref in {r.id for r in rows if r.status == "superseded"}


def test_failed_verification_cannot_be_promoted(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        row = svc.get_run(db, rid)
        variants = deepcopy(row.variants)
        variants[0]["recommended"]["verified"]["ok"] = False
        row.variants = variants
        db.commit()
        with pytest.raises(UnprocessableError, match="verification"):
            svc.promote(db, PromoteRequest(run_id=rid, scenario_id=ids[0]))


BCROP, L0 = "knob:crop_strategy=byrp_bcrop", "knob:pyramid_l0=skip"


def test_concurrent_first_option_reviews_preserve_both_history_entries(engine, stored_run):
    _, ids = stored_run
    barrier = Barrier(2)

    def save(status):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return svc.set_option_review(db, PowerOptionReviewRequest(
                scenario_id=ids[0], option_key=BCROP, status=status))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, status) for status in ('candidate', 'iq_eval')]
        saved = [future.result(timeout=20) for future in futures]
    assert saved[0]['id'] == saved[1]['id']
    with Session(engine) as db:
        (review,) = svc.list_option_reviews(db, scenario_id=ids[0])
        assert {h['status'] for h in review['history']} == {'candidate', 'iq_eval'}


def _options(total):
    def res(items, delta):
        return {"key": "+".join(sorted(items)), "items": items, "labels": items, "kinds": ["knob"],
                "iq_eval": "required", "spec_ok": True, "spec_reasons": [], "total_mw": total + delta,
                "delta_mw": delta, "delta_pct": round(100 * delta / total, 2), "delta_bw_mbs": -1.0,
                "raw_delta_mw": delta, "raw_delta_pct": None, "attribution": {"by_category": {"BW traffic": delta}},
                "fill_pct": {}}
    return {"status": "ok", "notes": [], "sets": 3, "max_sets": 64, "errors": [], "best": f"{BCROP}+{L0}",
            "dimensions": [{"id": "knob:crop_strategy", "kind": "knob", "label": "BYRP bayer crop", "current": "mcsc_crop",
                            "items": [{"key": BCROP, "kind": "knob", "label": "BYRP bayer crop: byrp_bcrop",
                                       "value": "byrp_bcrop", "from": "mcsc_crop", "iq_eval": "required"}]},
                           {"id": "knob:pyramid_l0", "kind": "knob", "label": "MTNR L0 skip", "current": "use",
                            "items": [{"key": L0, "kind": "knob", "label": "MTNR L0 skip: skip", "value": "skip",
                                       "from": "use", "iq_eval": "required"}]}],
            "results": [res([BCROP, L0], -3.0), res([L0], -2.0), res([BCROP], -1.0)]}


def test_power_options_ride_with_the_prediction_and_follow_iq_review(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        run = svc.get_run(db, rid)
        variants = deepcopy(run.variants)
        variants[0]["power_options"] = _options(10.0)
        run.variants = variants
        db.commit()
        svc.promote(db, PromoteRequest(run_id=rid))
        rows = {r["scenario_id"]: r for r in svc.board(db)["rows"] if r["scenario_id"] in ids}
        po = rows[ids[0]]["power_options"]
        assert po["best"]["key"] == f"{BCROP}+{L0}" and po["best"]["delta_mw"] == -3.0
        assert po["best"]["review_status"] == "candidate" and po["reference"]["rule"] == "auto:min-power"
        assert rows[ids[1]]["power_options"]["status"] == "not_explored"
        # scenario-wide rejection of bcrop drops every set that contains it
        svc.set_option_review(db, PowerOptionReviewRequest(scenario_id=ids[0], option_key=BCROP, status="rejected",
                                                           note="edge sharpness"), "iq")
        svc.set_option_review(db, PowerOptionReviewRequest(scenario_id=ids[0], option_key=L0, status="iq_eval"), "iq")
        po = next(r for r in svc.board(db)["rows"] if r["scenario_id"] == ids[0])["power_options"]
        assert po["best"] == {"key": L0, "labels": [L0], "delta_mw": -2.0, "delta_pct": -20.0, "review_status": "iq_eval"}
        status = {r["key"]: r["review_status"] for r in po["results"]}
        assert status == {f"{BCROP}+{L0}": "rejected", L0: "iq_eval", BCROP: "rejected"}
        # a variant-specific decision overrides the scenario-wide one
        svc.set_option_review(db, PowerOptionReviewRequest(scenario_id=ids[0], variant_id="shared", option_key=BCROP,
                                                           status="adopted"), "iq")
        svc.set_option_review(db, PowerOptionReviewRequest(scenario_id=ids[0], variant_id="shared", option_key=L0,
                                                           status="adopted"), "iq")
        po = next(r for r in svc.board(db)["rows"] if r["scenario_id"] == ids[0])["power_options"]
        assert po["best"]["key"] == f"{BCROP}+{L0}" and po["best"]["review_status"] == "adopted"
        reviews = svc.list_option_reviews(db, scenario_id=ids[0])
        assert len(reviews) == 4
        bcrop = next(r for r in reviews if r["option_key"] == BCROP and r["variant_id"] == "*")
        svc.set_option_review(db, PowerOptionReviewRequest(scenario_id=ids[0], option_key=BCROP, status="iq_eval"), "iq")
        again = next(r for r in svc.list_option_reviews(db, scenario_id=ids[0])
                     if r["option_key"] == BCROP and r["variant_id"] == "*")
        assert again["id"] == bcrop["id"] and [h["status"] for h in again["history"]] == ["rejected", "iq_eval"]


def test_model_status_counts_predictions_from_older_engine(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        svc.promote(db, PromoteRequest(run_id=rid))
        project = db.query(Scenario.project_ref).filter(Scenario.id == ids[0]).scalar()
        status = svc.model_status(db, project_ref=project)
        assert status["engine_rev"] == svc.ENGINE_REV
        assert status["predictions"]["engines"].get("test", 0) >= 2  # stored_run uses engine_rev="test"
        assert status["predictions"]["stale_engine"] >= 2
        assert set(status["measurements"]) == {"real", "synthetic"}
        assert all(set(d) == {"ref", "sample", "predictions"} for d in status["dvfs"])
