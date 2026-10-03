from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import arch_exploration as router


def _client(monkeypatch, **fakes):
    app = create_app()
    db = MagicMock()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    for name, fake in fakes.items():
        monkeypatch.setattr(router.svc, name, fake)
    return TestClient(app, raise_server_exceptions=False)


def test_create_run_passes_spec(monkeypatch):
    seen = {}

    def fake(db, request, user):
        seen["req"] = request
        return {"id": "EXP-1"}

    c = _client(monkeypatch, run_exploration=fake)
    res = c.post("/api/v1/arch/exploration/runs", json={
        "scenario_ids": ["uc-camera-recording"],
        "spec": {"axes": {"runtime_scales": [1.0, 1.3], "dvfs_headroom_levels": 2}, "objective": {"statistic": "mean"}},
    })
    assert res.status_code == 200 and res.json()["id"] == "EXP-1"
    spec = seen["req"].spec
    assert spec.axes.runtime_scales == [1.0, 1.3] and spec.axes.dvfs_headroom_levels == 2
    assert spec.objective.statistic == "mean"


def test_create_run_requires_scope(monkeypatch):
    c = _client(monkeypatch, run_exploration=lambda *a: {})
    assert c.post("/api/v1/arch/exploration/runs", json={}).status_code == 422
    bad = {"category": "camera", "spec": {"axes": {"runtime_scales": [0]}}}
    assert c.post("/api/v1/arch/exploration/runs", json=bad).status_code == 422


def test_promote_case_key_needs_single_variant(monkeypatch):
    c = _client(monkeypatch, promote=lambda db, req, user: {"promoted": [], "skipped": []})
    ok = c.post("/api/v1/arch/predictions/promote", json={"run_id": "EXP-1"})
    assert ok.status_code == 200
    bad = c.post("/api/v1/arch/predictions/promote", json={"run_id": "EXP-1", "case_key": "k"})
    assert bad.status_code == 422


def test_report_html_and_compare(monkeypatch):
    row = MagicMock(rendered_html="<html><body>report</body></html>")
    c = _client(monkeypatch, get_report=lambda db, rid: row,
                compare=lambda db, **kw: {"attribution": {"delta_mw": 1.0}, "kw": kw})
    res = c.get("/api/v1/arch/reports/RPT-1/html")
    assert res.status_code == 200 and "text/html" in res.headers["content-type"] and "report" in res.text
    cmp = c.get("/api/v1/arch/predictions/compare", params={"scenario_id": "s", "variant_id": "v"}).json()
    assert cmp["kw"]["scenario_id"] == "s" and cmp["kw"]["old_id"] is None


def test_power_option_review_routes(monkeypatch):
    seen = {}

    def fake_set(db, request, user):
        seen["req"] = request
        return {"id": "POR-1", "status": request.status}

    c = _client(monkeypatch, set_option_review=fake_set,
                list_option_reviews=lambda db, project_ref=None, scenario_id=None: [{"scenario_id": scenario_id}])
    ok = c.put("/api/v1/arch/power-options/reviews", json={
        "scenario_id": "uc-cam-recording-e2700", "option_key": "knob:crop_strategy=byrp_bcrop", "status": "iq_eval"})
    assert ok.status_code == 200 and seen["req"].variant_id == "*"
    bad_status = {"scenario_id": "uc", "option_key": "knob:a=b", "status": "done"}
    assert c.put("/api/v1/arch/power-options/reviews", json=bad_status).status_code == 422
    bad_key = {"scenario_id": "uc", "option_key": "bcrop", "status": "adopted"}
    assert c.put("/api/v1/arch/power-options/reviews", json=bad_key).status_code == 422
    got = c.get("/api/v1/arch/power-options/reviews", params={"scenario_id": "uc-x"})
    assert got.status_code == 200 and got.json() == [{"scenario_id": "uc-x"}]


def test_list_runs_passes_project_scope(monkeypatch):
    seen = {}

    def fake(db, **kw):
        seen.update(kw)
        return []

    c = _client(monkeypatch, list_runs=fake)
    assert c.get("/api/v1/arch/exploration/runs", params={"project_ref": "proj-a"}).status_code == 200
    assert seen["project_ref"] == "proj-a"
