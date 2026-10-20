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
        "bw_mbs": 0,
    }
    obj = {"fps": 30, "period_ms": 33.333, "eis_on": False, "ips": [], "domains": [],
           "bw": {"total_mbs": 0, "hw_mbs": 0, "sw_mbs": 0},
           "power": {"hw_mw": value, "bw_mw": 0, "bw_hw_mw": 0, "bw_sw_mw": 0}, "cpu_by_task": {"cpu": value},
           "verdict": {"status": "ok"}, "intervals_ok": True, "intervals": {}, "latency": {}, "stages": {}}
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


def test_report_and_calibration_choose_the_same_scoped_representative_on_timestamp_ties(engine, stored_run):
    from datetime import UTC, datetime

    from scenario_db.api.services.calibration import calibration_summary
    from scenario_db.db.models.evidence import Evidence

    rid, ids = stored_run
    with Session(engine) as db:
        svc.promote(db, PromoteRequest(run_id=rid))
        try:
            # Insert the larger ID first; both paths read measured_at DESC NULLS LAST, id, so the
            # timestamp tie resolves by the database order, not by insertion order.
            for sid in ids:
                for tag, origin, year, total in (
                    ("z-physical", "physical_capture", 2025, 10),
                    ("a-physical", "physical_capture", 2025, 10),
                    ("new-unknown", "unknown", 2026, 10),
                    ("new-synthetic", "synthetic", 2026, 10),
                    ("missing-total", "physical_capture", 2026, None),
                ):
                    db.add(Evidence(
                        id=f"{sid}-{tag}", scenario_ref=sid, variant_ref="shared",
                        kind="evidence.measurement", schema_version="1.0.0",
                        measured_at=datetime(year, 1, 1, tzinfo=UTC),
                        execution_context={}, aggregation={},
                        provenance={"data_origin": origin},
                        kpi={"total_power_mw": {"mean": total}}, yaml_sha256="test",
                    ))
            db.commit()
            summaries = {sid: calibration_summary(db, scenario_id=sid)["rows"][0]["measurement_id"] for sid in ids}
            report = svc.create_report(db, ArchReportRequest(run_id=rid))
            captured = {r["scenario_id"]: r["measurement_id"] for r in report["snapshot"]["calibration"]}
            assert summaries == captured == {sid: f"{sid}-a-physical" for sid in ids}
            assert all(r["origin"] == "physical_capture" for r in report["snapshot"]["calibration"])
        finally:
            db.rollback()
            db.query(Evidence).filter(Evidence.scenario_ref.in_(ids)).delete(synchronize_session=False)
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
        with pytest.raises(UnprocessableError):
            svc.set_report_status(db, report["id"], "published")  # no reviewer / note
        svc.set_report_status(db, report["id"], "published", reviewer="Joo", note="spec 확인", user="tester")
        meta = svc.report_detail(svc.get_report(db, report["id"]))
        assert meta["status"] == "published" and meta["review"]["reviewer"] == "Joo" and meta["review_count"] == 1
        data, name = svc.report_xlsx(db, report["id"])
        assert data[:2] == b"PK" and name.endswith(".xlsx")
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


def test_reports_are_created_as_drafts_and_keep_concurrent_review_history(engine, stored_run):
    rid, _ = stored_run
    with Session(engine) as db:
        with pytest.raises(UnprocessableError, match="draft"):
            svc.create_report(db, ArchReportRequest.model_construct(run_id=rid, status="published"))
        report = svc.create_report(db, ArchReportRequest(run_id=rid))
        assert report["status"] == "draft"
        assert report["snapshot"]["spec_summary"]["power_sources"] == {"registered": 0, "recommended": 2}
        assert "등록 예측" not in report["snapshot"]["conclusion"]["headline"]
    barrier = Barrier(2)

    def review(reviewer):
        with Session(engine) as db:
            held = svc.get_report(db, report["id"])
            assert held.review_history == []
            barrier.wait(timeout=10)
            return svc.set_report_status(db, report["id"], "published", reviewer=reviewer, note="spec checked")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(review, reviewer) for reviewer in ("reviewer-a", "reviewer-b")]
        for future in futures:
            assert future.result(timeout=20)["status"] == "published"
    with Session(engine) as db:
        history = svc.get_report(db, report["id"]).review_history
        assert len(history) == 2 and {r["reviewer"] for r in history} == {"reviewer-a", "reviewer-b"}


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


def test_explicit_promotion_cannot_bypass_incomplete_power_budget(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        run = svc.get_run(db, rid)
        variants = deepcopy(run.variants)
        variants[0] |= {"spec_ok": False, "status": {"power_budget_status": "unknown"}}
        run.variants = variants
        run.spec = dict(run.spec) | {"constraints": {"power_budget_mw": 100}}
        db.commit()
        request = PromoteRequest(run_id=rid, scenario_id=ids[0], variant_ids=["shared"])
        with pytest.raises(UnprocessableError, match="incomplete power model"):
            svc.promote(db, request)
        assert db.query(Prediction).filter_by(scenario_ref=ids[0]).count() == 0
        run.spec = dict(run.spec) | {"constraints": {"power_budget_mw": 100, "require_complete_power_for_budget": False}}
        db.commit()
        assert len(svc.promote(db, request)["promoted"]) == 1


def test_pareto_only_candidate_is_persisted_as_a_user_selection(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        run = svc.get_run(db, rid)
        variants = deepcopy(run.variants)
        variants[0]["pareto"] = [dict(variants[0]["recommended"]) | {"key": "pareto-only"}]
        run.variants = variants
        db.commit()
        result = svc.promote(db, PromoteRequest(run_id=rid, scenario_id=ids[0], variant_ids=["shared"],
                                                case_key="pareto-only", reason="headroom review"))
        assert len(result["promoted"]) == 1
        prediction = db.get(Prediction, result["promoted"][0]["id"])
        assert prediction.case_key == "pareto-only" and prediction.selection_rule == "user:pareto-1"


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
        variants[0]["input_sections"] = {"config": "review-config"}
        run.variants = variants
        run.spec = dict(run.spec) | {"manifest": {"blobs": {
            "review-config": {"vbat": 3.8, "pmic_efficiency": 0.91},
        }}}
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
        frozen = svc.create_report(db, ArchReportRequest(run_id=rid))
        frozen_options = frozen["snapshot"]["power_options"][0]
        assert frozen_options["best"]["review_status"] == "rejected"
        assert {r["key"]: r["review_status"] for r in frozen_options["singles"]} == {
            L0: "iq_eval", BCROP: "rejected",
        }
        assert frozen["snapshot"]["review_context"]["battery"] == {
            "vbat": 3.8, "pmic_efficiency": 0.91, "source": "run",
        }
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
        updated = svc.create_report(db, ArchReportRequest(run_id=rid))
        assert updated["snapshot"]["power_options"][0]["best"]["review_status"] == "adopted"
        assert svc.get_report(db, frozen["id"]).snapshot["power_options"][0]["best"]["review_status"] == "rejected"


def test_model_status_counts_predictions_from_older_engine(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        svc.promote(db, PromoteRequest(run_id=rid))
        project = db.query(Scenario.project_ref).filter(Scenario.id == ids[0]).scalar()
        status = svc.model_status(db, project_ref=project)
        assert status["engine_rev"] == svc.ENGINE_REV
        assert status["predictions"]["engines"].get("test", 0) >= 2  # stored_run uses engine_rev="test"
        assert status["predictions"]["stale_engine"] >= 2
        assert set(status["measurements"]) == {"real", "synthetic", "empty", "unknown"}
        assert status["dvfs_unrecorded"] >= 0
        assert all(set(d) == {"ref", "sample", "predictions"} for d in status["dvfs"])


def test_report_package_and_run_manifest(engine, stored_run):
    import io
    import json
    from zipfile import ZipFile
    rid, ids = stored_run
    with Session(engine) as db:
        svc.promote(db, PromoteRequest(run_id=rid, expected_project_ref=svc.get_run(db, rid).project_ref))
        report = svc.create_report(db, ArchReportRequest(run_id=rid))
        svc.set_report_status(db, report["id"], "published", reviewer="Kim", note="검토 완료", user="tester")
        data, name = svc.report_package(db, report["id"])
        z = ZipFile(io.BytesIO(data))
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["body"]["integrity_ok"] and manifest["report"]["status"] == "published"
        assert manifest["review_history"][-1]["reviewer"] == "Kim"
        assert manifest["runs"][0]["run_id"] == rid and manifest["runs"][0]["input_hash"] == "test"
        assert z.read("report.html").decode() == svc.get_report(db, report["id"]).rendered_html
        m = svc.run_manifest(db, rid)
        assert m["run_id"] == rid and not m["available"]  # stored before manifests existed
        assert "manifest" not in svc.run_detail(svc.get_run(db, rid))["spec"]
        with pytest.raises(UnprocessableError, match="belongs to project"):
            svc.promote(db, PromoteRequest(run_id=rid, expected_project_ref="proj-other"))


def test_run_summary_view_variant_detail_and_gzip(engine, stored_run):
    from fastapi.testclient import TestClient
    from scenario_db.api.app import create_app
    from scenario_db.api.deps import get_db
    from scenario_db.exceptions import NotFoundError
    rid, ids = stored_run
    with Session(engine) as db:
        summary_view = svc.run_detail(svc.get_run(db, rid), "summary")
        assert summary_view["view"] == "summary" and all(v["detail"] is False for v in summary_view["variants"])
        one = svc.run_variant(db, rid, ids[1], "shared")
        assert one["scenario_id"] == ids[1] and one["detail"] is True
        with pytest.raises(NotFoundError):
            svc.run_variant(db, rid, ids[1], "missing")
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        res = TestClient(app).get(f"/api/v1/arch/exploration/runs/{rid}", params={"view": "summary"},
                                  headers={"Accept-Encoding": "gzip"})
        assert res.status_code == 200 and res.json()["view"] == "summary"
        if len(res.content) >= 1024:
            assert res.headers.get("content-encoding") == "gzip"


def test_sql_run_summary_matches_python_trimming(engine, stored_run):
    rid, _ = stored_run
    with Session(engine) as db:
        py = svc.run_detail(svc.get_run(db, rid), "summary")
        sql = svc.run_summary(db, rid)
        assert sql["variants"] == py["variants"]
        assert {k: v for k, v in sql.items() if k != "variants"} == {k: v for k, v in py.items() if k != "variants"}


def test_project_report_merges_current_predictions_and_syncs_risk_register(engine):
    """RPT-01/04/05: a project report spans the runs of its current predictions; risks keep their IDs."""
    from scenario_db.api.services import review_risks
    from scenario_db.db.models.definition import Project
    from scenario_db.db.models.exploration import ReviewRisk

    token = uuid4().hex[:10]
    pid, sa, sb = f"proj-rpt-{token}", f"uc-rpt-a-{token}", f"uc-rpt-b-{token}"
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version="1.0", metadata_={}, yaml_sha256="test"))
        db.flush()
        for sid in (sa, sb):
            db.add(Scenario(id=sid, project_ref=pid, schema_version="1.0.0", metadata_={}, pipeline={}, yaml_sha256="test"))
        db.flush()
        for sid in (sa, sb):
            db.add(ScenarioVariant(scenario_id=sid, id="shared", design_conditions={}))
        failing = summary(sb, 30) | {"spec_ok": False, "spec_reasons": ["nrt: sw 11.1 ms > period 8.33 ms"]}
        db.add(ArchExplorationRun(id=f"EXP-old-{token}", title="old", scenario_type="review", project_ref=pid,
                                  spec={"objective": {}, "axes": {}, "constraints": {}}, variants=[summary(sa, 10), failing],
                                  errors=[], summary={}, engine_rev="test", input_hash="test"))
        db.commit()  # the newer run gets a later created_at (now() is per transaction)
        db.add(ArchExplorationRun(id=f"EXP-new-{token}", title="new", scenario_type="review", project_ref=pid,
                                  spec={"objective": {}, "axes": {}, "constraints": {}}, variants=[summary(sa, 12)],
                                  errors=[], summary={}, engine_rev="test", input_hash="test"))
        db.commit()
        svc.promote(db, PromoteRequest(run_id=f"EXP-old-{token}", scenario_id=sa))
        with pytest.raises(ValueError):
            ArchReportRequest()
        rep = svc.create_report(db, ArchReportRequest(project_ref=pid))
        snap = rep["snapshot"]
        assert rep["scope"] == "project" and snap["scope"]["kind"] == "project"
        assert {r["id"] for r in snap["scope"]["runs"]} == {f"EXP-old-{token}", f"EXP-new-{token}"}
        rows = {r["scenario_id"]: r for r in snap["scenarios"]}
        assert rows[sa]["prediction_id"] and rows[sa]["power"]["total_mw"] == 10   # from its prediction's run
        assert rows[sb]["spec_ok"] is False                                           # unregistered: newest run with it
        assert snap["criteria"]["fps"] == {"ok": 1, "total": 2, "fail": ["shared"], "basis": "stage"}
        assert snap["basis"]["throughput_model"] == "stage" and "Risk register" in svc.get_report(db, rep["id"]).rendered_html
        reg = {r["key"]: r for r in snap["risk_register"]}
        assert reg["fps_drop"]["severity"] == "critical" and reg["fps_drop"]["label"] == "R-01" and reg["fps_drop"]["trend"] == "new"
        assert rep["summary"]["risks"]["critical"] == 1 and rep["summary"]["fps"] == {"ok": 1, "total": 2}
        # people own owner / status / note; the next report keeps them and the ID
        risk_id = reg["fps_drop"]["id"]
        upd = review_risks.update_risk(db, risk_id, owner="sw-arch", status="mitigating", note="2-frame batch", user="t")
        assert upd["owner"] == "sw-arch" and [h["field"] for h in upd["history"][-3:]] == ["owner", "status", "note"]
        assert svc.report_stale(db, rep["id"])["stale"] is False
        svc.promote(db, PromoteRequest(run_id=f"EXP-new-{token}", scenario_id=sa))
        stale = svc.report_stale(db, rep["id"])
        assert stale["stale"] and stale["changed"][0]["variant_id"] == "shared"
        # CPU-11: a recorded CPU what-if result is frozen into the next report (and its tolerance rule fires)
        from scenario_db.api.services import review_cpu
        from scenario_db.db.models.exploration import ReviewCpuSnapshot

        db.add(ReviewCpuSnapshot(id=f"CPUSNAP-{token}", project_ref=pid, scenario_ref=sa, variant_ref="shared",
                                 profile_ref="meas-x", power_params_ref="pmp-x", status="active", request={},
                                 summary={"tolerance": 1.1, "binding": "timing", "points": [], "best_at_start": {}}))
        db.commit()
        assert [c["id"] for c in review_cpu.list_cpu_snapshots(db, pid)] == [f"CPUSNAP-{token}"]
        rep2 = svc.create_report(db, ArchReportRequest(project_ref=pid))
        reg2 = {r["key"]: r for r in rep2["snapshot"]["risk_register"]}
        assert reg2["fps_drop"]["id"] == risk_id and reg2["fps_drop"]["trend"] == "ongoing"
        assert reg2["fps_drop"]["owner"] == "sw-arch" and reg2["fps_drop"]["status"] == "mitigating"
        assert rep2["snapshot"]["scenarios"][0]["power"]["total_mw"] == 12
        # RPT-11: frozen comparison with the previous project report
        prev = rep2["snapshot"]["previous"]
        assert prev["report"]["id"] == rep["id"]
        assert prev["power"]["changed"][0]["prev_mw"] == 10 and prev["power"]["changed"][0]["cur_mw"] == 12
        assert [c["variant_id"] for c in rep2["snapshot"]["cpu"]] == ["shared"] and "cpu_growth_tolerance" in reg2
        html2 = svc.get_report(db, rep2["id"]).rendered_html
        assert "이전 보고서 대비" in html2 and "Scenario dossier" in html2 and "Tier 1" in html2 and "×1.1" in html2
        assert review_cpu.withdraw_cpu_snapshot(db, f"CPUSNAP-{token}")["status"] == "withdrawn"
        assert review_cpu.list_cpu_snapshots(db, pid) == []
        db.query(ReviewCpuSnapshot).filter(ReviewCpuSnapshot.project_ref == pid).delete(synchronize_session=False)
        with pytest.raises(UnprocessableError):
            review_risks.update_risk(db, risk_id, status="bogus")
        # RISK-03: closing needs closure evidence; the due date is kept and cleared with ""
        with pytest.raises(UnprocessableError, match="closure evidence"):
            review_risks.update_risk(db, risk_id, status="closed", user="t")
        upd = review_risks.update_risk(db, risk_id, due_date="2026-11-05", user="t")
        assert upd["due_date"] == "2026-11-05" and upd["priority"] > 0
        with pytest.raises(UnprocessableError, match='invalid due_date'):
            review_risks.update_risk(db, risk_id, due_date='2026-02-30', owner='must-not-change')
        upd = review_risks.update_risk(db, risk_id, status="closed", closure_evidence="silicon fps 240 OK", due_date="", user="t")
        assert upd["status"] == "closed" and upd["closure_evidence"] == "silicon fps 240 OK" and upd["due_date"] is None
        with pytest.raises(UnprocessableError, match='closure evidence'):
            review_risks.update_risk(db, risk_id, closure_evidence='')
        # AUTO-02: a blocking gap (uncovered KPI) must be acknowledged before publishing
        project = db.get(Project, pid)
        project.globals_ = {"review_policy": {"kpi": [{"variant_ref": "shared", "scenario_ref": "uc-missing-scenario"}]}}
        db.commit()
        rep3 = svc.create_report(db, ArchReportRequest(project_ref=pid))
        assert rep3["summary"]["blockers"] == 1
        with pytest.raises(UnprocessableError, match="게시 전 확인"):
            svc.set_report_status(db, rep3["id"], "published", reviewer="r", note="n")
        pub = svc.set_report_status(db, rep3["id"], "published", reviewer="r", note="APV는 다음 탐색", acknowledge_gaps=True)
        assert pub["status"] == "published" and pub["review"]["acknowledged_gaps"] == ["kpi_uncovered"]
        db.query(ArchReport).filter(ArchReport.project_ref == pid).delete(synchronize_session=False)
        db.query(ReviewRisk).filter(ReviewRisk.project_ref == pid).delete(synchronize_session=False)
        db.query(Prediction).filter(Prediction.project_ref == pid).delete(synchronize_session=False)
        db.query(ArchExplorationRun).filter(ArchExplorationRun.project_ref == pid).delete(synchronize_session=False)
        db.query(ScenarioVariant).filter(ScenarioVariant.scenario_id.in_([sa, sb])).delete(synchronize_session=False)
        db.query(Scenario).filter(Scenario.id.in_([sa, sb])).delete(synchronize_session=False)
        db.query(Project).filter(Project.id == pid).delete()
        db.commit()


def test_project_report_keeps_latest_calculation_failure(engine, stored_run):
    from datetime import UTC, datetime, timedelta

    rid, ids = stored_run
    new_id = f'{rid}-failed'
    with Session(engine) as db:
        old = svc.get_run(db, rid)
        error = {'scenario_id': ids[1], 'variant_id': 'shared', 'stage': 'load', 'error': 'missing input'}
        db.add(ArchExplorationRun(id=new_id, title='latest', project_ref=old.project_ref,
                                  scenario_type='review', spec={}, variants=[summary(ids[0], 12)], errors=[error],
                                  summary={}, engine_rev='test', input_hash='test',
                                  created_at=datetime.now(UTC) + timedelta(seconds=1)))
        db.commit()
        try:
            run, _, _ = svc._project_run(db, old.project_ref, 'review')
            assert [(v['scenario_id'], v['variant_id']) for v in run['variants']] == [(ids[0], 'shared')]
            assert run['errors'] == [error]
            assert run['source_run_ids'] == [new_id]
            with pytest.raises(ValueError, match='all scenario types'):
                ArchReportRequest(project_ref=old.project_ref, scenario_type='review')
        finally:
            db.query(ArchExplorationRun).filter_by(id=new_id).delete()
            db.commit()


def test_concurrent_first_risk_sync_allocates_distinct_ids(engine):
    from scenario_db.api.services.review_risks import sync_risks
    from scenario_db.db.models.definition import Project
    from scenario_db.db.models.exploration import ReviewRisk

    pid = f'proj-risk-race-{uuid4().hex}'
    with Session(engine) as db:
        db.add(Project(id=pid, schema_version='1.0', metadata_={}, yaml_sha256='test'))
        db.commit()
    barrier = Barrier(2)

    def sync(key):
        risk = {'key': key, 'rule': key, 'severity': 'high', 'category': 'test', 'title': key,
                'detail': '', 'affected': [], 'mitigation': None}
        with Session(engine) as db:
            barrier.wait(timeout=10)
            rows = sync_risks(db, pid, [risk], report_ref=None, user='reviewer')
            db.commit()
            return next(r['id'] for r in rows if r['key'] == key)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(sync, ['first', 'second']))
        assert len(set(ids)) == 2
        with Session(engine) as db:
            assert sorted(r.seq for r in db.query(ReviewRisk).filter_by(project_ref=pid)) == [1, 2]
    finally:
        with Session(engine) as db:
            db.query(ReviewRisk).filter_by(project_ref=pid).delete()
            db.query(Project).filter_by(id=pid).delete()
            db.commit()
