from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest
from scenario_db.api.schemas.timing_budget import TimingBudgetFleetRequest, TimingBudgetRequest
from scenario_db.api.services import arch_exploration as svc
from scenario_db.api.services import timing_budget as timing
from scenario_db.exceptions import NotFoundError, UnprocessableError


def scenario(sid="uc-a", project="proj-a"):
    return SimpleNamespace(id=sid, project_ref=project, metadata_={"category": ["camera"], "name": sid})


def test_scope_rejects_cross_project_and_missing_scenarios():
    db = MagicMock()
    query = db.query.return_value
    query.order_by.return_value.all.return_value = [scenario(), scenario("uc-b", "proj-b")]
    with pytest.raises(UnprocessableError, match="one project"):
        svc._scenarios(db, ArchExplorationRunRequest(category="camera"))
    with pytest.raises(NotFoundError, match="scenario not found"):
        svc._scenarios(db, ArchExplorationRunRequest(scenario_ids=["uc-missing"]))
    with pytest.raises(NotFoundError, match="no scenario"):
        svc._scenarios(db, ArchExplorationRunRequest(category="audio"))


def test_derived_variants_use_parent_reference_not_only_name():
    db = MagicMock()
    db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [
        ("base", None), ("custom-name", "base"), ("old-timing-max", None),
    ]
    req = ArchExplorationRunRequest(category="camera")
    assert svc._variant_ids(db, "uc-a", req) == ["base"]
    req.include_derived = True
    req.variant_ids = ["custom-name"]
    assert svc._variant_ids(db, "uc-a", req) == ["custom-name"]


def test_run_persists_summary_and_reports_partial_failure(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(svc, "_scenarios", lambda *a: [scenario()])
    monkeypatch.setattr(svc, "_variant_ids", lambda *a: ["good", "bad"])
    monkeypatch.setattr(svc, "_apply_config_profile", lambda *a: None)
    graph = SimpleNamespace()
    def load(db, shim, default):
        if shim.variant_id == "bad":
            raise ValueError("broken pipeline")
        return graph, {}, "dvfs-test"
    monkeypatch.setattr(svc, "_load", load)
    monkeypatch.setattr(svc, "_graph_soc_ref", lambda g: "soc-test")
    value = {"scenario_id": "uc-a", "variant_id": "good", "spec_ok": True, "input_hash": "hash",
             "counts": {"cases": 12, "eligible": 4}, "recommended": {"total_mw": 10, "verified": {"ok": True}}}
    monkeypatch.setattr(svc, "explore_variant", lambda *a, **kw: deepcopy(value))
    request = ArchExplorationRunRequest(category="camera")
    result = svc.run_exploration(db, request, "reviewer")
    assert result["project_ref"] == "proj-a" and result["created_by"] == "reviewer"
    assert result["summary"] == {"variants": 1, "errors": 1, "spec_ok": 1, "cases": 12,
                                  "eligible_cases": 4, "verified": 1, "recommended_power_mw": [10, 10]}
    assert result["errors"] == [{"scenario_id": "uc-a", "variant_id": "bad", "error": "broken pipeline"}]
    db.commit.assert_called_once()
    with pytest.raises(UnprocessableError, match="max_variants"):
        svc.run_exploration(db, request.model_copy(update={"max_variants": 1}))
    monkeypatch.setattr(svc, "_variant_ids", lambda *a: ["bad"])
    with pytest.raises(UnprocessableError, match="every variant failed"):
        svc.run_exploration(db, request)
    monkeypatch.setattr(svc, "_variant_ids", lambda *a: [])
    with pytest.raises(NotFoundError, match="no variants"):
        svc.run_exploration(db, request)


def test_fleet_rejects_unbounded_implicit_scope_before_simulation(monkeypatch):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [
        (str(i), None) for i in range(201)
    ]
    load = MagicMock()
    monkeypatch.setattr(timing, "_load", load)
    with pytest.raises(UnprocessableError, match="200 variants"):
        timing.analyze_timing_budget_fleet(db, TimingBudgetFleetRequest(scenario_id="uc-a"))
    load.assert_not_called()


def test_fleet_deduplicates_explicit_selection_and_preserves_partial_errors(monkeypatch):
    monkeypatch.setattr(timing, "_apply_config_profile", lambda *a: "simcfg-test")
    def load(db, shim, default):
        if shim.variant_id == "bad":
            raise LookupError("missing")
        return shim.variant_id, {}, "dvfs-test"
    monkeypatch.setattr(timing, "_load", load)
    analyze = MagicMock(return_value={"variant_id": "good"})
    monkeypatch.setattr(timing, "analyze_timing_budget", analyze)
    monkeypatch.setattr(timing, "fleet_row", lambda report: report)
    result = timing.analyze_timing_budget_fleet(MagicMock(), TimingBudgetFleetRequest(
        scenario_id="uc-a", variant_ids=["good", "good", "bad"]))
    assert result.rows == [{"variant_id": "good"}]
    assert result.errors == [{"variant_id": "bad", "error": "missing"}]
    analyze.assert_called_once()


@pytest.mark.parametrize("error, expected", [(LookupError("missing"), NotFoundError), (ValueError("invalid"), UnprocessableError)])
def test_variant_loader_errors_are_domain_errors(monkeypatch, error, expected):
    monkeypatch.setattr(timing, "_apply_config_profile", lambda *a: None)
    monkeypatch.setattr(timing, "_load", MagicMock(side_effect=error))
    with pytest.raises(expected):
        timing.analyze_timing_budget_request(MagicMock(), TimingBudgetRequest(scenario_id="uc-a", variant_id="v"))
