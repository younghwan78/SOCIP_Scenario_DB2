"""Real PostgreSQL regression coverage for collaboration persistence and registration races."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scenario_db.api.schemas.arch_exploration import LeverRegisterRequest, PromoteRequest
from scenario_db.api.schemas.prediction_discussion import PredictionCommentRequest, PredictionNoteRequest
from scenario_db.api.services import arch_exploration as svc
from scenario_db.api.services import prediction_discussion as discussion
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.db.models.exploration import Prediction, PredictionComment, PredictionNote
from scenario_db.exceptions import ConflictError, NotFoundError, UnprocessableError
from tests.integration.test_arch_exploration import stored_run as stored_run
from tests.integration.test_lever_register import SC, VAR
from tests.integration.test_lever_register import e2600 as e2600


def _expected(sid, pid=None):
    return {"scenario_id": sid, "variant_id": "shared", "prediction_id": pid}


def _promote(db, rid, sid, pid=None):
    return svc.promote(db, PromoteRequest(run_id=rid, scenario_id=sid, expected_current=[_expected(sid, pid)]),
                       user="registered-writer")["promoted"][0]["id"]


def test_notes_persist_with_revision_actor_and_immutable_prediction(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        pid = _promote(db, rid, ids[0])
        pred = svc.get_prediction(db, pid)
        snapshot = deepcopy(pred)
        assert discussion.get_notes(db, pid)["revision"] == 0
        saved = discussion.put_notes(db, pid, PredictionNoteRequest(
            expected_revision=0, title="UHD60 후보", purpose="소비전력 검토", description="크기 변경 후 검토",
            assumptions="센서 입력 유지", conclusion="실측 확인 필요", tags=["UHD60", "EIS"]), "writer-a")
        assert saved["revision"] == 1 and saved["created_by"] == saved["updated_by"] == "writer-a"
    with Session(engine) as db:
        assert discussion.get_notes(db, pid) == saved
        updated = discussion.put_notes(db, pid, PredictionNoteRequest(expected_revision=1, title="검토 완료"), "writer-b")
        assert updated["revision"] == 2 and updated["created_by"] == "writer-a" and updated["updated_by"] == "writer-b"
        with pytest.raises(ConflictError, match="revision 2"):
            discussion.put_notes(db, pid, PredictionNoteRequest(expected_revision=1, title="오래된 편집"), "writer-a")
        db.rollback()
        assert discussion.get_notes(db, pid)["title"] == "검토 완료"
        assert svc.get_prediction(db, pid) == snapshot


def test_comments_replies_pagination_and_prediction_delete_cascade(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        pid = _promote(db, rid, ids[0])
        discussion.put_notes(db, pid, PredictionNoteRequest(expected_revision=0, title="검토"), "writer")
        first = discussion.add_comment(db, pid, PredictionCommentRequest(body="센서 크기도 변경되나요?"), "analyst")
        second = discussion.add_comment(db, pid, PredictionCommentRequest(body="출력 크기만 변경합니다", parent_id=first["id"]), "writer")
        third = discussion.add_comment(db, pid, PredictionCommentRequest(body="화질 검증 필요"), "reviewer")
    with Session(engine) as db:
        page = discussion.list_comments(db, pid, limit=1, offset=1)
        assert page["total"] == 3 and page["items"] == [second]
        assert second["parent_id"] == first["id"] and second["created_by"] == "writer"
        assert discussion.list_comments(db, pid)["items"] == [first, second, third]
        db.query(Prediction).filter_by(id=pid).delete()
        db.commit()
        assert db.query(PredictionNote).filter_by(prediction_ref=pid).count() == 0
        assert db.query(PredictionComment).filter_by(prediction_ref=pid).count() == 0


def test_cross_prediction_reply_is_rejected_by_service_and_database(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        a = _promote(db, rid, ids[0])
        b = _promote(db, rid, ids[1])
        comment = discussion.add_comment(db, a, PredictionCommentRequest(body="원본 의견"), "analyst")
        with pytest.raises(UnprocessableError, match="same prediction"):
            discussion.add_comment(db, b, PredictionCommentRequest(body="잘못된 답글", parent_id=comment["id"]), "writer")
        db.rollback()
        db.add(PredictionComment(id=f"PCOM-{uuid4().hex}", prediction_ref=b, parent_ref=comment["id"],
                                 body="직접 삽입도 거절", created_by="writer"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        assert discussion.list_comments(db, b)["total"] == 0


def test_missing_prediction_discussion_is_not_created(engine):
    with Session(engine) as db:
        for operation in (
            lambda: discussion.get_notes(db, "missing"),
            lambda: discussion.put_notes(db, "missing", PredictionNoteRequest(expected_revision=0), "writer"),
            lambda: discussion.list_comments(db, "missing"),
            lambda: discussion.add_comment(db, "missing", PredictionCommentRequest(body="note"), "analyst"),
        ):
            with pytest.raises(NotFoundError):
                operation()
            db.rollback()


def test_concurrent_first_note_saves_return_one_conflict(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        pid = _promote(db, rid, ids[0])
    barrier = Barrier(2)

    def save(actor):
        with Session(engine) as db:
            assert discussion.get_notes(db, pid)["revision"] == 0
            barrier.wait(timeout=10)
            try:
                return discussion.put_notes(db, pid, PredictionNoteRequest(expected_revision=0, title=actor), actor)
            except ConflictError:
                db.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, actor) for actor in ("writer-a", "writer-b")]
        results = [future.result(timeout=20) for future in futures]
    assert results.count("conflict") == 1
    with Session(engine) as db:
        saved = discussion.get_notes(db, pid)
        assert saved["revision"] == 1 and saved["title"] == saved["created_by"]


def test_concurrent_first_registration_with_expected_null_returns_one_conflict(engine, stored_run):
    rid, ids = stored_run
    barrier = Barrier(2)

    def promote():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                return _promote(db, rid, ids[0])
            except ConflictError:
                db.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(promote) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert results.count("conflict") == 1
    with Session(engine) as db:
        rows = db.query(Prediction).filter_by(scenario_ref=ids[0]).all()
        assert len(rows) == 1 and rows[0].status == "current" and rows[0].supersedes_ref is None


def test_changed_current_registration_and_stale_batch_are_atomic(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        initial = {sid: _promote(db, rid, sid) for sid in ids}
        current = _promote(db, rid, ids[0], initial[ids[0]])
        with pytest.raises(ConflictError, match="current prediction changed"):
            svc.promote(db, PromoteRequest(run_id=rid, expected_current=[_expected(sid, initial[sid]) for sid in ids]))
        db.rollback()
        rows = db.query(Prediction).filter(Prediction.scenario_ref.in_(ids)).all()
        assert len(rows) == 3
        assert {row.scenario_ref: row.id for row in rows if row.status == "current"} == {ids[0]: current, ids[1]: initial[ids[1]]}
        with pytest.raises(ConflictError):
            _promote(db, rid, ids[0], initial[ids[0]])
        db.rollback()
        with pytest.raises(ConflictError):
            _promote(db, rid, ids[0], None)
        db.rollback()


def test_guard_requires_all_selected_pairs_and_legacy_registration_stays_supported(engine, stored_run):
    rid, ids = stored_run
    with Session(engine) as db:
        with pytest.raises(UnprocessableError, match="every selected"):
            svc.promote(db, PromoteRequest(run_id=rid, expected_current=[_expected(ids[0])]))
        db.rollback()
        assert db.query(Prediction).filter(Prediction.scenario_ref.in_(ids)).count() == 0
        assert len(svc.promote(db, PromoteRequest(run_id=rid))["promoted"]) == 2


@pytest.fixture
def lever_review(e2600):
    client = e2600
    source = client.post("/api/v1/arch/exploration/runs", json={"scenario_ids": [SC], "variant_ids": [VAR],
                        "project_ref": "proj-sm-s947b"})
    assert source.status_code == 200, source.text
    run = source.json()
    base = {"run_id": run["id"], "scenario_id": SC, "variant_id": VAR,
            "compression": run["variants"][0]["tiers"]["keep"]["best"]["compression_modes"]}
    first = client.post("/api/v1/arch/predictions/lever", json=base)
    assert first.status_code == 200, first.text
    pid = first.json()["promoted"][0]["id"]
    option = "knob:pyramid_l0=skip"
    review = client.put("/api/v1/arch/power-options/reviews", json={"scenario_id": SC, "variant_id": VAR,
        "option_key": option, "status": "iq_eval", "note": "existing review"})
    assert review.status_code == 200, review.text
    note = client.put(f"/api/v1/arch/predictions/{pid}/notes", json={"expected_revision": 0, "title": "existing explanation"})
    assert note.status_code == 200, note.text
    comment = client.post(f"/api/v1/arch/predictions/{pid}/comments", json={"body": "existing discussion"})
    assert comment.status_code == 200, comment.text
    payload = {**base, "compression": {}, "options": [option],
        "iq_results": [{"option_key": option, "status": "adopted", "note": "new IQ result"}],
        "expected_current": [{"scenario_id": SC, "variant_id": VAR, "prediction_id": pid}]}
    return client, payload, pid


def _lever_state(client, pid):
    return {"reviews": client.get("/api/v1/arch/power-options/reviews", params={"scenario_id": SC}).json(),
        "runs": client.get("/api/v1/arch/exploration/runs", params={"project_ref": "proj-sm-s947b", "limit": 200}).json(),
        "history": client.get("/api/v1/arch/predictions/history", params={"scenario_id": SC, "variant_id": VAR}).json(),
        "notes": client.get(f"/api/v1/arch/predictions/{pid}/notes").json(),
        "comments": client.get(f"/api/v1/arch/predictions/{pid}/comments").json()}


def test_stale_lever_registration_preserves_iq_history_and_metadata(lever_review):
    client, payload, pid = lever_review
    replacement = client.post("/api/v1/arch/predictions/lever", json={key: payload[key] for key in (
        "run_id", "scenario_id", "variant_id", "compression")})
    assert replacement.status_code == 200, replacement.text
    before = _lever_state(client, pid)
    refused = client.post("/api/v1/arch/predictions/lever", json=payload)
    assert refused.status_code == 409, refused.text
    assert _lever_state(client, pid) == before


def test_late_lever_conflict_rolls_back_new_run_and_review_history(lever_review, monkeypatch):
    from scenario_db.db.models.exploration import ArchExplorationRun, PowerOptionReview

    client, payload, pid = lever_review
    before = _lever_state(client, pid)
    pending = []

    def conflict_after_calculation(db, request, user=None, *, rule=None, commit=True):
        assert commit is False
        # The real option review and re-exploration have already flushed their rows.
        assert request.run_id != payload["run_id"]
        assert db.get(ArchExplorationRun, request.run_id) is not None
        review = db.query(PowerOptionReview).filter_by(scenario_ref=SC, variant_ref=VAR,
            option_key=payload["options"][0]).one()
        assert review.note == "new IQ result" and len(review.history) == 2
        pending.append(request.run_id)
        raise ConflictError("current prediction changed at final registration")

    monkeypatch.setattr(svc, "promote", conflict_after_calculation)
    refused = client.post("/api/v1/arch/predictions/lever", json=payload)
    assert refused.status_code == 409, refused.text
    assert len(pending) == 1
    assert _lever_state(client, pid) == before


def test_guarded_rejected_iq_preserves_the_review_registration_contract(lever_review):
    client, payload, pid = lever_review
    before = _lever_state(client, pid)
    payload["iq_results"][0]["status"] = "rejected"
    rejected = client.post("/api/v1/arch/predictions/lever", json=payload)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected" and rejected.json()["promoted"] == []
    after = _lever_state(client, pid)
    assert {key: value for key, value in after.items() if key != "reviews"} == {
        key: value for key, value in before.items() if key != "reviews"}
    assert after["reviews"][0]["status"] == "rejected" and len(after["reviews"][0]["history"]) == 2


def test_guarded_adopted_lever_commits_the_run_review_and_snapshot_together(lever_review):
    client, payload, pid = lever_review
    registered = client.post("/api/v1/arch/predictions/lever", json=payload)
    assert registered.status_code == 200, registered.text
    result = registered.json()
    assert result["status"] == "registered" and result["run_id"] != payload["run_id"]
    prediction = client.get(f"/api/v1/arch/predictions/{result['promoted'][0]['id']}").json()
    assert prediction["supersedes"] == pid
    assert prediction["metrics"]["lever_selection"]["options"] == payload["options"]
    assert client.get(f"/api/v1/arch/exploration/runs/{result['run_id']}").status_code == 200
    reviews = client.get("/api/v1/arch/power-options/reviews", params={"scenario_id": SC}).json()
    assert reviews[0]["status"] == "adopted" and len(reviews[0]["history"]) == 2


def test_guarded_lever_parent_lock_does_not_deadlock_with_ordinary_promotion(engine, stored_run, monkeypatch):
    rid, ids = stored_run
    variant_locked, scenario_locked = Event(), Event()
    actual_lock = svc._lock_lever_current

    def observed_lock(db, request):
        connection = db.connection()

        def observe(conn, cursor, statement, parameters, context, executemany):
            if "FROM scenarios" in statement and "FOR " in statement:
                scenario_locked.set()

        event.listen(connection, "after_cursor_execute", observe)
        try:
            return actual_lock(db, request)
        finally:
            event.remove(connection, "after_cursor_execute", observe)

    monkeypatch.setattr(svc, "_lock_lever_current", observed_lock)

    def ordinary():
        with Session(engine) as db:
            db.query(ScenarioVariant).filter_by(scenario_id=ids[0], id="shared").with_for_update().one()
            variant_locked.set()
            assert scenario_locked.wait(timeout=10)
            return svc.promote(db, PromoteRequest(run_id=rid, scenario_id=ids[0]))

    def guarded():
        assert variant_locked.wait(timeout=10)
        with Session(engine) as db:
            with pytest.raises(ConflictError, match="current prediction changed"):
                svc.register_lever(db, LeverRegisterRequest(run_id=rid, scenario_id=ids[0], variant_id="shared",
                                   expected_current=[_expected(ids[0])]), "guarded-writer")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ordinary)
        second = pool.submit(guarded)
        assert len(first.result(timeout=20)["promoted"]) == 1
        second.result(timeout=20)
    with Session(engine) as db:
        assert db.query(Prediction).filter_by(scenario_ref=ids[0], status="current").count() == 1
