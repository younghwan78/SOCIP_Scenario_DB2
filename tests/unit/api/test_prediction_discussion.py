from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from scenario_db.api import auth
from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import arch_exploration as router
from scenario_db.api.schemas.arch_exploration import LeverRegisterRequest, PowerOptionReviewRequest, PromoteRequest
from scenario_db.api.schemas.prediction_discussion import PredictionCommentRequest, PredictionNoteRequest
from scenario_db.api.schemas.timing_budget import TimingBudgetRegisterRequest
from scenario_db.api.services import arch_exploration, prediction_discussion, timing_budget
from scenario_db.api.services.recompute import recompute_prediction
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.models.exploration import PowerOptionReview, Prediction, PredictionComment
from scenario_db.exceptions import ConflictError, UnprocessableError


@pytest.fixture
def discussion_client(monkeypatch):
    settings = SimpleNamespace(
        mutation_auth_disabled=False, mutation_api_keys={},
        api_principals={role: SimpleNamespace(secret=SecretStr("test-secret"), roles={role})
                        for role in ("reader", "analyst", "writer", "admin")},
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    app = create_app()

    def test_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = test_db
    return TestClient(app)


def _headers(role):
    return {"X-ScenarioDB-Key-Id": role, "X-ScenarioDB-API-Key": "test-secret"}


@pytest.mark.parametrize("role,status", [("reader", 403), ("analyst", 403), ("writer", 200), ("admin", 200)])
def test_note_permission_and_server_actor(discussion_client, monkeypatch, role, status):
    seen = []
    monkeypatch.setattr(router.discussion, "put_notes",
                        lambda db, pid, req, actor: seen.append(actor) or {"revision": 1, "updated_by": actor})
    response = discussion_client.put("/api/v1/arch/predictions/p/notes", json={"expected_revision": 0},
                                     headers=_headers(role))
    assert response.status_code == status
    assert seen == ([role] if status == 200 else [])


@pytest.mark.parametrize("role,status", [("reader", 403), ("analyst", 200), ("writer", 200), ("admin", 200)])
def test_comment_permission_and_server_actor(discussion_client, monkeypatch, role, status):
    seen = []
    monkeypatch.setattr(router.discussion, "add_comment",
                        lambda db, pid, req, actor: seen.append(actor) or {"created_by": actor, "body": req.body})
    response = discussion_client.post("/api/v1/arch/predictions/p/comments", json={"body": "검토 의견"},
                                      headers=_headers(role))
    assert response.status_code == status
    assert seen == ([role] if status == 200 else [])


def test_discussion_rejects_spoofed_actor_and_unbounded_input(discussion_client, monkeypatch):
    monkeypatch.setattr(router.discussion, "add_comment", lambda *args: {})
    for body in ({"body": " ",}, {"body": "x" * 5001}, {"body": "ok", "created_by": "spoof"}):
        assert discussion_client.post("/api/v1/arch/predictions/p/comments", json=body,
                                      headers=_headers("writer")).status_code == 422
    for body in ({"expected_revision": 0, "title": "x" * 201},
                 {"expected_revision": 0, "updated_by": "spoof"},
                 {"expected_revision": 0, "tags": [" "]}, {"title": "missing revision"}):
        assert discussion_client.put("/api/v1/arch/predictions/p/notes", json=body,
                                     headers=_headers("writer")).status_code == 422
    note = PredictionNoteRequest(expected_revision=0, tags=[" UHD60 ", "UHD60"])
    assert note.tags == ["UHD60"]


def test_comment_pagination_and_append_only_routes(discussion_client, monkeypatch):
    seen = []
    monkeypatch.setattr(router.discussion, "list_comments",
                        lambda db, pid, **kw: seen.append(kw) or {"items": []})
    path = "/api/v1/arch/predictions/p/comments"
    assert discussion_client.get(path, params={"limit": 20, "offset": 40}).status_code == 200
    assert seen == [{"limit": 20, "offset": 40}]
    assert discussion_client.get(path, params={"limit": 201}).status_code == 422
    assert discussion_client.get(path, params={"offset": -1}).status_code == 422
    assert discussion_client.delete(path + "/c", headers=_headers("admin")).status_code == 404
    assert discussion_client.patch(path + "/c", json={"body": "edit"}, headers=_headers("admin")).status_code == 404


def test_stale_notes_are_http_conflicts(discussion_client, monkeypatch):
    def changed(*args):
        raise ConflictError("prediction notes changed; reload before saving")

    monkeypatch.setattr(router.discussion, "put_notes", changed)
    response = discussion_client.put("/api/v1/arch/predictions/p/notes", json={"expected_revision": 1},
                                     headers=_headers("writer"))
    assert response.status_code == 409


def test_registration_guards_keep_omission_and_explicit_null_distinct():
    legacy = TimingBudgetRegisterRequest(scenario_id="s", variant_id="v", reason="save")
    first = TimingBudgetRegisterRequest(scenario_id="s", variant_id="v", reason="save", expected_current_prediction_id=None)
    assert "expected_current_prediction_id" not in legacy.model_fields_set
    assert "expected_current_prediction_id" in first.model_fields_set
    assert PromoteRequest(run_id="r").expected_current is None
    duplicate = [{"scenario_id": "s", "variant_id": "v", "prediction_id": None}] * 2
    with pytest.raises(ValidationError, match="duplicate"):
        PromoteRequest(run_id="r", expected_current=duplicate)
    with pytest.raises(ValidationError, match="duplicate"):
        LeverRegisterRequest(run_id="r", scenario_id="s", variant_id="v", expected_current=duplicate)


@pytest.mark.parametrize("guard", ["omitted", None, "reviewed-prediction"])
def test_timing_registration_forwards_reviewed_current(monkeypatch, guard):
    monkeypatch.setattr(timing_budget, "_apply_config_profile", lambda *args: None)
    monkeypatch.setattr(timing_budget, "_load", lambda *args: (object(), {}, None))
    monkeypatch.setattr(timing_budget, "scenario_policy", lambda *args: None)
    monkeypatch.setattr(timing_budget, "apply_throughput", lambda options, policy: options)
    monkeypatch.setattr(timing_budget, "with_cpu_profile", lambda db, options, *args: options)
    monkeypatch.setattr(timing_budget, "_condition_hash", lambda *args: "hash")
    monkeypatch.setattr(arch_exploration, "run_exploration",
                        lambda *args: {"id": "run", "variants": [{"recommended": {"key": "base", "total_mw": 10}}]})
    seen = []
    monkeypatch.setattr(arch_exploration, "promote",
                        lambda db, req, *args, **kw: seen.append(req) or {"promoted": []})
    data = {"scenario_id": "s", "variant_id": "v", "reason": "save"}
    if guard != "omitted":
        data["expected_current_prediction_id"] = guard
    timing_budget.register_condition(MagicMock(), TimingBudgetRegisterRequest(**data), "writer")
    expected = seen[0].expected_current
    if guard == "omitted":
        assert expected is None
    else:
        assert [item.model_dump() for item in expected] == [{"scenario_id": "s", "variant_id": "v", "prediction_id": guard}]


@pytest.mark.parametrize("source", ["timing-budget", "exploration"])
def test_recompute_always_guards_original_prediction(monkeypatch, source):
    pred = SimpleNamespace(id="reviewed", status="current", exploration_run_ref="r", scenario_ref="s",
                           variant_ref="v", project_ref="proj", metrics={}, selection_rule="auto:min-power")
    run = SimpleNamespace(scenario_type=source, spec={"input_selection": {}})
    db = SimpleNamespace(get=lambda model, ref: pred if model is Prediction else run)
    seen = []
    monkeypatch.setattr(timing_budget, "register_condition",
                        lambda db, req, *args: seen.append(req) or {"promoted": [{"id": "new"}]})
    monkeypatch.setattr(arch_exploration, "run_exploration", lambda *args: {"id": "run"})
    monkeypatch.setattr(arch_exploration, "promote",
                        lambda db, req, *args: seen.append(req) or {"promoted": [{"id": "new"}]})
    assert recompute_prediction(db, "reviewed")["status"] == "recomputed"
    if source == "timing-budget":
        assert seen[0].expected_current_prediction_id == "reviewed"
    else:
        assert seen[0].expected_current[0].prediction_id == "reviewed"


def test_lever_registration_forwards_reviewed_current(monkeypatch):
    from scenario_db.sim import arch_exploration as engine

    run = SimpleNamespace(id="r", project_ref="proj", variants=[{"scenario_id": "s", "variant_id": "v"}])
    monkeypatch.setattr(arch_exploration, "_lock_lever_current", lambda *args: None)
    monkeypatch.setattr(arch_exploration, "get_run", lambda *args: run)
    monkeypatch.setattr(engine, "case_from_selection", lambda *args: {"key": "case"})
    seen = []
    monkeypatch.setattr(arch_exploration, "promote",
                        lambda db, req, *args, **kw: seen.append(req) or {"promoted": []})
    request = LeverRegisterRequest(run_id="r", scenario_id="s", variant_id="v",
                                   expected_current=[{"scenario_id": "s", "variant_id": "v", "prediction_id": "reviewed"}])
    arch_exploration.register_lever(MagicMock(), request, "writer")
    assert seen[0].expected_current[0].prediction_id == "reviewed"


def test_recompute_already_superseded_prediction_keeps_legacy_validation():
    db = SimpleNamespace(get=lambda *args: SimpleNamespace(status="superseded"))
    with pytest.raises(UnprocessableError, match="only the current"):
        recompute_prediction(db, "reviewed")


def _guarded_option_request(status="adopted"):
    return LeverRegisterRequest(run_id="source", scenario_id="s", variant_id="v", options=["knob:pyramid_l0=skip"],
        iq_results=[{"option_key": "knob:pyramid_l0=skip", "status": status, "note": "reviewed IQ"}],
        expected_current=[{"scenario_id": "s", "variant_id": "v", "prediction_id": "reviewed"}])


def _stub_option_run(monkeypatch):
    summary = {"scenario_id": "s", "variant_id": "v", "power_options": {
        "dimensions": [{"items": [{"key": "knob:pyramid_l0=skip"}]}]}}
    source = SimpleNamespace(id="source", project_ref="project", scenario_type="camera", spec={}, variants=[summary])
    monkeypatch.setattr(arch_exploration, "get_run", lambda *args: source)
    monkeypatch.setattr(arch_exploration, "_lock_lever_current", lambda *args: None)
    from scenario_db.sim import arch_exploration as engine

    monkeypatch.setattr(engine, "case_from_selection", lambda *args: {"key": "case"})
    return summary


def test_guarded_lever_defers_nested_commits_and_rolls_back_late_conflict(monkeypatch):
    summary = _stub_option_run(monkeypatch)
    db = MagicMock()
    review = MagicMock()
    calculate = MagicMock(return_value={"id": "new-run", "variants": [summary]})
    promote = MagicMock(side_effect=ConflictError("current prediction changed"))
    monkeypatch.setattr(arch_exploration, "set_option_review", review)
    monkeypatch.setattr(arch_exploration, "run_exploration", calculate)
    monkeypatch.setattr(arch_exploration, "promote", promote)
    with pytest.raises(ConflictError):
        arch_exploration.register_lever(db, _guarded_option_request(), "writer")
    assert review.call_args.kwargs["commit"] is False
    assert calculate.call_args.kwargs["commit"] is False
    assert promote.call_args.kwargs["commit"] is False
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_guarded_rejected_iq_still_commits_review_once_without_promoting(monkeypatch):
    _stub_option_run(monkeypatch)
    db = MagicMock()
    review, calculate, promote = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(arch_exploration, "set_option_review", review)
    monkeypatch.setattr(arch_exploration, "run_exploration", calculate)
    monkeypatch.setattr(arch_exploration, "promote", promote)
    result = arch_exploration.register_lever(db, _guarded_option_request("rejected"), "writer")
    assert result["status"] == "rejected" and result["promoted"] == []
    assert review.call_args.kwargs["commit"] is False
    calculate.assert_not_called()
    promote.assert_not_called()
    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_guarded_lever_persists_snapshot_selection_in_the_single_final_commit(monkeypatch):
    summary = _stub_option_run(monkeypatch)
    db = MagicMock()
    prediction = SimpleNamespace(metrics={"power": {"total_mw": 10}})
    db.get.return_value = prediction
    review = MagicMock()
    calculate = MagicMock(return_value={"id": "new-run", "variants": [summary]})
    promote = MagicMock(return_value={"promoted": [{"id": "new-prediction"}], "skipped": []})
    monkeypatch.setattr(arch_exploration, "set_option_review", review)
    monkeypatch.setattr(arch_exploration, "run_exploration", calculate)
    monkeypatch.setattr(arch_exploration, "promote", promote)
    committed = []
    db.commit.side_effect = lambda: committed.append(deepcopy(prediction.metrics))
    result = arch_exploration.register_lever(db, _guarded_option_request(), "writer")
    assert result["status"] == "registered"
    assert committed == [prediction.metrics]
    assert committed[0]["lever_selection"]["options"] == ["knob:pyramid_l0=skip"]
    assert review.call_args.kwargs["commit"] is calculate.call_args.kwargs["commit"] is promote.call_args.kwargs["commit"] is False
    db.commit.assert_called_once()
    db.rollback.assert_not_called()


@pytest.mark.parametrize("commit", [True, False])
def test_option_review_can_join_registration_transaction_without_lock_upgrade(commit):
    db = MagicMock()
    scenario_query, variant_query, review_query = MagicMock(), MagicMock(), MagicMock()
    row = PowerOptionReview(id="review", project_ref="project", scenario_ref="s", variant_ref="v",
        option_key="knob:pyramid_l0=skip", status="iq_eval", note="earlier note", history=[{"status": "iq_eval"}],
        updated_by="earlier-writer", updated_at=datetime.now(UTC))
    scenario_query.filter_by.return_value.with_for_update.return_value.one_or_none.return_value = SimpleNamespace(project_ref="project")
    variant_query.filter_by.return_value.one_or_none.return_value = SimpleNamespace(id="v")
    review_query.filter_by.return_value.with_for_update.return_value.one_or_none.return_value = row
    queries = {Scenario: scenario_query, ScenarioVariant: variant_query, PowerOptionReview: review_query}
    db.query.side_effect = lambda model: queries[model]
    result = arch_exploration.set_option_review(db, PowerOptionReviewRequest(scenario_id="s", variant_id="v",
        option_key="knob:pyramid_l0=skip", status="adopted", note="new IQ"), "writer", commit=commit)
    assert result["status"] == "adopted" and result["note"] == "new IQ" and len(result["history"]) == 2
    assert result["updated_by"] == "writer"
    scenario_query.filter_by.return_value.with_for_update.assert_called_once_with(key_share=not commit)
    db.flush.assert_called_once()
    if commit:
        db.commit.assert_called_once()
    else:
        db.commit.assert_not_called()


def test_comment_registration_sequence_remains_internal_to_the_database():
    row = PredictionComment(id="comment", prediction_ref="prediction", sequence=42, parent_ref=None,
        body="review", created_by="analyst", created_at=datetime(2026, 10, 14, tzinfo=UTC))
    assert prediction_discussion._comment_dict(row) == {
        "id": "comment", "prediction_id": "prediction", "parent_id": None, "body": "review",
        "created_by": "analyst", "created_at": "2026-10-14T00:00:00+00:00"}
