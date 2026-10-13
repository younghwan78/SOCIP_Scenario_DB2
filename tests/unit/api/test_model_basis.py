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
    monkeypatch.setattr(svc, "_assert_inputs", lambda db, row: None)


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


def test_same_params_id_with_other_version_is_an_override(active):
    r = TimingBudgetRequest(scenario_id="s", variant_id="v", config={"power_params_ref": "pmp-x-v2@1"})
    svc.apply_basis(MagicMock(), r)
    assert r.basis_overrides == ["power_params"]


def test_explicit_dvfs_version_and_model_coefficients_are_preserved(active):
    r = TimingBudgetRequest(scenario_id="s", variant_id="v", dvfs_version=99,
                            config={"bw_power_mw_per_gbps": 12})
    svc.apply_basis(MagicMock(), r)
    assert r.dvfs_table_ref is None and r.dvfs_version == 99
    assert r.basis_overrides == ["config", "dvfs"]


def test_diff_components_and_trial_summary():
    new = SimpleNamespace(**{**vars(B), "power_params_ref": "pmp-x-v3@3"})
    assert svc.diff_bases(B, new) == [{"field": "power_params_ref", "from": "pmp-x-v2@2", "to": "pmp-x-v3@3"}]
    assert svc.basis_components(B) == "cfg v2 · pmp v2 · dvfs-x-v0 · e11"
    row = SimpleNamespace(trial={"total": 3, "items": {
        "a": {"status": "ok", "delta_mw": -10.0}, "b": {"status": "ok", "delta_mw": 4.0}, "c": {"status": "error"}}})
    s = svc.trial_summary(row)
    assert (s["total"], s["done"], s["failed"], s["delta_mw_sum"], s["delta_mw_min"]) == (3, 2, 1, -6.0, -10.0)


def test_trial_and_promote_refuse_non_draft(monkeypatch):
    monkeypatch.setattr(svc, "get_basis", lambda db, bid: B)  # active
    monkeypatch.setattr(svc, "_locked_basis", lambda db, bid: B)
    with pytest.raises(UnprocessableError):
        svc.start_trial(MagicMock(), "basis-p-2")
    with pytest.raises(UnprocessableError):
        svc.promote_basis(MagicMock(), "basis-p-2")


def test_run_trial_item_stores_the_dry_run(monkeypatch):
    draft = SimpleNamespace(**{**vars(B), "status": "draft", "trial": {"total": 1, "items": {
        "P1": {"prediction_id": "P1", "scenario_id": "s", "variant_id": "v", "status": "pending", "old_total_mw": 800.0}}}})
    monkeypatch.setattr(svc, "get_basis", lambda db, bid: draft)
    monkeypatch.setattr(svc, "_locked_basis", lambda db, bid: draft)
    monkeypatch.setattr(svc, "_assert_inputs", lambda db, row: None)
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


@pytest.fixture
def catalogs():
    from scenario_db.db.models.capability import PowerModelParams, SimConfigProfile, SocDvfsTable
    from scenario_db.db.models.definition import Project

    rows = {
        Project: SimpleNamespace(metadata_={"soc_ref": "soc-exynos2600"}, globals_={}),
        SimConfigProfile: SimpleNamespace(version=2, project_ref="p", soc_ref="soc-exynos2600",
                                         run_config={"fps": 30, "sw_margin": 1.1}),
        PowerModelParams: SimpleNamespace(version=2, soc_ref="soc-exynos2600", params={"bw": {"a": 10}}),
        SocDvfsTable: SimpleNamespace(id="dvfs", dvfs_version=1, soc_ref="soc-exynos2600", domains={},
                                     compatibility_scope="soc", source_project_ref=None),
    }
    db = MagicMock()
    db.get.side_effect = lambda cls, key: rows.get(cls)

    def query(cls):
        q = MagicMock()
        for method in ("filter_by", "populate_existing", "order_by"):
            getattr(q, method).return_value = q
        q.one_or_none.return_value = q.first.return_value = rows.get(cls)
        return q

    db.query.side_effect = query
    return db, rows


def test_basis_stamp_is_canonical_and_detects_same_version_coefficient_edit(catalogs):
    from scenario_db.db.models.capability import SimConfigProfile
    from scenario_db.sim.arch_exploration import ENGINE_REV

    db, rows = catalogs
    stamp = svc._input_stamp(db, "p", "cfg", "pmp@2", "dvfs")
    rows[SimConfigProfile].run_config = {"sw_margin": 1.1, "fps": 30}
    assert svc._input_stamp(db, "p", "cfg", "pmp@2", "dvfs") == stamp
    basis = SimpleNamespace(project_ref="p", config_profile_ref="cfg", power_params_ref="pmp@2",
                            dvfs_table_ref="dvfs", input_stamp=stamp, engine_rev=ENGINE_REV)
    svc._assert_inputs(db, basis)
    rows[SimConfigProfile].run_config = {"fps": 60}
    with pytest.raises(UnprocessableError, match="inputs changed"):
        svc._assert_inputs(db, basis)


@pytest.mark.parametrize("component,field,value", [
    ("SimConfigProfile", "project_ref", "foreign"),
    ("SimConfigProfile", "soc_ref", "foreign-soc"),
    ("PowerModelParams", "soc_ref", "foreign-soc"),
    ("SocDvfsTable", "soc_ref", "foreign-soc"),
])
def test_stamp_rejects_component_scope_mismatch(catalogs, component, field, value):
    import scenario_db.db.models.capability as models

    db, rows = catalogs
    setattr(rows[getattr(models, component)], field, value)
    with pytest.raises(UnprocessableError, match="another"):
        svc._input_stamp(db, "p", "cfg", "pmp@2", "dvfs")


def test_project_only_dvfs_and_missing_catalog_cannot_be_used(catalogs):
    from scenario_db.db.models.capability import SocDvfsTable
    from scenario_db.exceptions import NotFoundError

    db, rows = catalogs
    rows[SocDvfsTable].compatibility_scope = "project"
    rows[SocDvfsTable].source_project_ref = "foreign"
    with pytest.raises(UnprocessableError, match="another project"):
        svc._input_stamp(db, "p", None, None, "dvfs")
    rows[SocDvfsTable] = None
    with pytest.raises(NotFoundError):
        svc._input_stamp(db, "p", None, None, "missing")


def test_catalog_version_selection_is_exact(catalogs):
    db, _ = catalogs
    assert svc._normalize_profile(db, "cfg@2") == "cfg"
    assert svc._normalize_power_params(db, "pmp") == "pmp@2"
    with pytest.raises(UnprocessableError):
        svc._normalize_profile(db, "cfg@1")
    with pytest.raises(UnprocessableError):
        svc._normalize_power_params(db, "pmp@1")
