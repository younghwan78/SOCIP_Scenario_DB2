from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scenario_db.api.schemas.simulation import SimulateRequest
from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services import model_basis as svc
from scenario_db.exceptions import UnprocessableError
from scenario_db.models.evidence.common import ExecutionContext

B = SimpleNamespace(id="basis-p-2", code="B2", project_ref="p", status="active", config_profile_ref="simcfg-p-v2",
                    power_params_ref="pmp-x-v2@2", dvfs_table_ref="dvfs-x-v0", engine_rev="arch-exploration/11", trial={})


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setattr(svc, "active_basis", lambda db, project: B)
    monkeypatch.setattr(svc, "get_basis", lambda db, bid: B)
    monkeypatch.setattr(svc, "_project_of", lambda db, req: "p")


def test_active_basis_fills_unset_inputs_and_is_recorded(active):
    r = TimingBudgetRequest(scenario_id="s", variant_id="v")
    assert svc.apply_basis(MagicMock(), r) is B
    assert (r.basis_ref, r.config_profile_ref, r.config.power_params_ref, r.dvfs_table_ref) == \
        ("basis-p-2", "simcfg-p-v2", "pmp-x-v2@2", "dvfs-x-v0")
    assert r.basis_overrides == []
    # recorded in the run's input selection (exclude_unset)
    dumped = r.model_dump(include={"config", "config_profile_ref", "dvfs_table_ref"}, exclude_unset=True)
    assert dumped["config"] == {"power_params_ref": "pmp-x-v2@2"}
    # idempotent
    svc.apply_basis(MagicMock(), r)
    assert r.basis_overrides == []


def test_explicit_inputs_win_and_mark_an_adhoc_condition(active):
    r = SimulateRequest(scenario_id="s", variant_id="v", execution_context=ExecutionContext(silicon_rev="a", sw_baseline_ref="sw-x", thermal="n/a"),
                        config_profile_ref="simcfg-p-v1", dvfs_table_ref="dvfs-other")
    r.config = r.config.model_copy(update={"power_params_ref": "pmp-x-v1"})
    svc.apply_basis(MagicMock(), r)
    assert r.basis_ref == "basis-p-2"
    assert r.basis_overrides == ["config_profile", "dvfs", "power_params"]
    assert r.config_profile_ref == "simcfg-p-v1" and r.config.power_params_ref == "pmp-x-v1"


def test_no_basis_leaves_request_unchanged(monkeypatch):
    monkeypatch.setattr(svc, "active_basis", lambda db, project: None)
    monkeypatch.setattr(svc, "_project_of", lambda db, req: "p")
    r = TimingBudgetRequest(scenario_id="s", variant_id="v")
    assert svc.apply_basis(MagicMock(), r) is None
    assert r.basis_ref is None and r.config_profile_ref is None


def test_diff_components_and_trial_summary():
    new = SimpleNamespace(**{**vars(B), "power_params_ref": "pmp-x-v3@3"})
    assert svc.diff_bases(B, new) == [{"field": "power_params_ref", "from": "pmp-x-v2@2", "to": "pmp-x-v3@3"}]
    assert svc.basis_components(B) == "cfg simcfg-p-v2 · pmp v2 · dvfs-x-v0 · e11"
    row = SimpleNamespace(trial={"total": 3, "items": {
        "a": {"status": "ok", "delta_mw": -10.0}, "b": {"status": "ok", "delta_mw": 4.0}, "c": {"status": "error"}}})
    s = svc.trial_summary(row)
    assert (s["total"], s["done"], s["failed"], s["delta_mw_sum"], s["delta_mw_min"]) == (3, 2, 1, -6.0, -10.0)


def test_trial_and_promote_refuse_non_draft(monkeypatch):
    monkeypatch.setattr(svc, "get_basis", lambda db, bid: B)  # active
    with pytest.raises(UnprocessableError):
        svc.start_trial(MagicMock(), "basis-p-2")
    with pytest.raises(UnprocessableError):
        svc.promote_basis(MagicMock(), "basis-p-2")


def test_run_trial_item_stores_the_dry_run(monkeypatch):
    draft = SimpleNamespace(**{**vars(B), "status": "draft", "trial": {"total": 1, "items": {
        "P1": {"prediction_id": "P1", "scenario_id": "s", "variant_id": "v", "status": "pending", "old_total_mw": 800.0}}}})
    monkeypatch.setattr(svc, "get_basis", lambda db, bid: draft)
    import scenario_db.api.services.recompute as rc
    calls = {}

    def fake(db, pid, **kw):
        calls.update(kw)
        return {"prediction_id": pid, "status": "ok", "run_id": "EXP-1", "case_key": None, "rule": "auto:min-power",
                "old_total_mw": 800.0, "new_total_mw": 780.0, "delta_mw": -20.0}
    monkeypatch.setattr(rc, "recompute_prediction", fake)
    out = svc.run_trial_item(MagicMock(), "basis-p-2", "P1")
    assert calls["basis"] is draft and calls["dry_run"] is True
    assert out["status"] == "ok" and out["run_id"] == "EXP-1" and out["delta_mw"] == -20.0
    assert draft.trial["items"]["P1"]["new_total_mw"] == 780.0
