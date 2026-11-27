from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from scenario_db.api.services import prediction_refresh as svc

T0 = datetime(2026, 11, 1)


def _run(rid, variants, *, kind="Camera Recording", age=0, spec=None):
    return SimpleNamespace(id=rid, scenario_type=kind, created_at=T0 + timedelta(days=age), spec=spec or {},
                           variants=[{"scenario_id": s, "variant_id": v} for s, v in variants])


def _pred(pid, scenario, variant, run, rule="auto:min-power-iq", mw=100.0):
    return SimpleNamespace(id=pid, scenario_ref=scenario, variant_ref=variant, exploration_run_ref=run,
                           selection_rule=rule, metrics={"power": {"total_mw": mw}})


def test_plan_groups_by_source_run_and_routes_special_registrations():
    runs = {
        "R1": _run("R1", [("s", "a"), ("s", "b"), ("s", "fail")]),
        "R2": _run("R2", [("t", "c")], kind="Video Playback", age=1),
        "TB": _run("TB", [("s", "d")], kind="timing-budget"),
        "OPT": _run("OPT", [("s", "e")], spec={"apply_options": ["x=1"]}),
    }
    preds = [_pred("P1", "s", "a", "R1"), _pred("P2", "s", "b", "R1"), _pred("P3", "t", "c", "R2"),
             _pred("P4", "s", "d", "TB"), _pred("P5", "s", "e", "OPT"), _pred("P6", "s", "f", "R1", rule="user:pick"),
             _pred("P7", "s", "g", "GONE")]
    plan = svc.plan_refresh(preds, runs)
    assert [(g.run_id, [p.id for p in g.registered], g.extra) for g in plan.groups] == [
        ("R1", ["P1", "P2"], [("s", "fail")]), ("R2", ["P3"], [])]
    assert [p.id for p in plan.timing_budget] == ["P4"]
    assert sorted(s["prediction_id"] for s in plan.skipped) == ["P5", "P6", "P7"]


def test_unregistered_variant_is_re_evaluated_once_by_the_newest_run():
    runs = {"OLD": _run("OLD", [("s", "a"), ("s", "x")]), "NEW": _run("NEW", [("s", "b"), ("s", "x")], age=3)}
    plan = svc.plan_refresh([_pred("P1", "s", "a", "OLD"), _pred("P2", "s", "b", "NEW")], runs)
    extra = {g.run_id: g.extra for g in plan.groups}
    assert extra == {"OLD": [], "NEW": [("s", "x")]}


def test_unregistered_variant_of_a_run_without_registrations_gets_its_own_group():
    # an fps-fail variant re-evaluated alone (no prediction from that run): the report reads it from there
    runs = {"SRC": _run("SRC", [("s", "a")]), "FAIL": _run("FAIL", [("s", "x")], age=2),
            "OLD": _run("OLD", [("s", "a"), ("s", "x"), ("s", "y")], age=-5),
            "TB": _run("TB", [("s", "z")], kind="timing-budget", age=4)}
    plan = svc.plan_refresh([_pred("P1", "s", "a", "SRC")], runs)
    assert [(g.run_id, [p.id for p in g.registered], g.extra) for g in plan.groups] == [
        ("OLD", [], [("s", "y")]), ("SRC", ["P1"], []), ("FAIL", [], [("s", "x")])]
    assert [(s["variant_id"], s["prediction_id"]) for s in plan.skipped] == [("z", None)]


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, preds, runs):
        self.preds, self.runs, self.committed, self.rolled_back = preds, runs, 0, 0

    def query(self, model):
        return _Query(self.preds if model.__name__ == "Prediction" else list(self.runs.values()))

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


@pytest.fixture
def engine(monkeypatch):
    import scenario_db.api.services.arch_exploration as ax

    calls = {"runs": [], "promotes": []}

    def run_exploration(db, req, user, *, commit, parallel):
        assert commit is False
        calls["runs"].append(req)
        rid = f"NEW{len(calls['runs'])}"
        return {"id": rid, "variants": [{"scenario_id": s, "variant_id": v, "spec_ok": v != "fail",
                                         "spec_reasons": ["fps"] if v == "fail" else []}
                                        for s in req.scenario_ids for v in req.variant_ids]}

    def promote(db, req, user, *, commit):
        assert commit is False
        calls["promotes"].append(req)
        return {"promoted": [{"variant_id": v, "total_mw": 90.0} for v in req.variant_ids if v != "b"],
                "skipped": [{"variant_id": "b", "reason": "no eligible case"}] if "b" in req.variant_ids else []}

    monkeypatch.setattr(ax, "run_exploration", run_exploration)
    monkeypatch.setattr(ax, "promote", promote)
    monkeypatch.setattr(ax, "default_case", lambda db, project, s: ({"total_mw": 80.0}, "auto:min-power-iq")
                        if s.get("spec_ok") else (None, None))
    return calls


def _project():
    runs = {"R1": _run("R1", [("s", "a"), ("s", "b"), ("s", "fail")])}
    return [_pred("P1", "s", "a", "R1"), _pred("P2", "s", "b", "R1")], runs


def test_refresh_stores_one_run_per_source_run_and_promotes_with_expected_current(engine):
    preds, runs = _project()
    db = _Db(preds, runs)
    out = svc.refresh_project(db, "p", user="u")
    assert db.committed == 1 and db.rolled_back == 0
    (req,) = engine["runs"]
    assert req.variant_ids == ["a", "b", "fail"] and req.max_variants == 3
    (prom,) = engine["promotes"]
    assert prom.variant_ids == ["a", "b"] and prom.expected_project_ref == "p"
    assert [(e.variant_id, e.prediction_id) for e in prom.expected_current] == [("a", "P1"), ("b", "P2")]
    rows = {r["variant_id"]: r for r in out["rows"]}
    assert rows["a"]["status"] == "recomputed" and rows["a"]["delta_mw"] == -10.0
    assert rows["b"]["status"] == "skipped" and rows["b"]["reason"] == "no eligible case"
    assert rows["fail"]["status"] == "evaluated" and rows["fail"]["spec_ok"] is False
    assert out["counts"] == {"recomputed": 1, "skipped": 1, "evaluated": 1}


def test_check_mode_registers_nothing_and_rolls_back(engine):
    preds, runs = _project()
    db = _Db(preds, runs)
    out = svc.refresh_project(db, "p", check=True)
    assert engine["promotes"] == [] and db.committed == 0 and db.rolled_back == 1
    assert {r["variant_id"]: r["new_total_mw"] for r in out["rows"] if r["prediction_id"]} == {"a": 80.0, "b": 80.0}


def test_a_failure_rolls_back_the_whole_exploration_part(engine, monkeypatch):
    import scenario_db.api.services.arch_exploration as ax

    def boom(*_a, **_k):
        raise RuntimeError("promote failed")

    monkeypatch.setattr(ax, "promote", boom)
    preds, runs = _project()
    db = _Db(preds, runs)
    with pytest.raises(RuntimeError):
        svc.refresh_project(db, "p")
    assert db.committed == 0 and db.rolled_back == 1


def test_empty_project_is_refused():
    from scenario_db.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        svc.refresh_project(_Db([], {}), "nope")
