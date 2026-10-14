from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.auth import ApiPrincipal, require_api_principal
from scenario_db.api.deps import get_db
from scenario_db.api.routers import scenario_whatif as router
from scenario_db.api.schemas.scenario_whatif import WhatIfChange, WhatIfExperimentRequest, WhatIfPreviewRequest
from scenario_db.api.services import scenario_whatif as service
from scenario_db.db.models.definition import Project
from scenario_db.exceptions import ConflictError, UnprocessableError
from scenario_db.sim.measured_timing import baseline_fingerprint
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph


def _graph():
    g = _exynos2600_generated_graph("uc-cam-recording-e2600", "cam-rec-r1-uhd30-vdis")
    g.project = Project(id=g.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    return g


def _request(graph, **kwargs):
    return WhatIfPreviewRequest(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id,
               variant_id=graph.variant_id, expected_baseline_hash=baseline_fingerprint(graph),
               changes=[dict(target="output_size", anchor_id="record_out", width=1920, height=1080)], **kwargs)


def _service(monkeypatch, graph):
    monkeypatch.setattr(service, "_load", lambda *a: (graph, {}, None))
    monkeypatch.setattr(service, "_apply_config_profile", lambda *a: None)
    monkeypatch.setattr(service, "scenario_policy", lambda *a: None)


def test_preview_uses_timing_budget_and_explains_model_subtotal(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    db = MagicMock()
    out = service.preview(db, _request(graph))
    assert out["candidate"]["metrics"]["modeled_power_mw"] < out["baseline"]["metrics"]["modeled_power_mw"]
    assert out["candidate"]["metrics"]["cpu_power_mw"] > 0
    assert out["candidate"]["metrics"]["total_power_mw"] is None
    assert not out["candidate"]["coverage"]["complete"]
    assert out["model_lineage"]["engine"] == "timing-budget"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_project_ownership_and_coefficient_drift_rejected(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    request = _request(graph)
    with pytest.raises(UnprocessableError, match="own"):
        service.preview(MagicMock(), request.model_copy(update={"project_ref": "other"}))
    ip = next(iter(graph.ip_catalog.values()))
    ip.capabilities = {**ip.capabilities, "model_revision": "new"}
    with pytest.raises(ConflictError, match="baseline changed"):
        service.preview(MagicMock(), request)


def test_save_recomputes_and_rejects_client_condition_hash(monkeypatch):
    graph = _graph()
    request = WhatIfExperimentRequest(preview_request=_request(graph), expected_condition_hash="a" * 64, title="test")
    rerun = MagicMock(return_value={"condition_hash": "b" * 64})
    monkeypatch.setattr(service, "preview", rerun)
    db = MagicMock()
    with pytest.raises(ConflictError, match="calculation inputs changed"):
        service.save_experiment(db, request, "alice")
    rerun.assert_called_once_with(db, request.preview_request)
    db.add.assert_not_called()
    with pytest.raises(ValueError):
        WhatIfExperimentRequest(**request.model_dump(), result={"power_mw": 0})


def test_roles_and_frame_admission(monkeypatch):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[require_api_principal] = lambda: ApiPrincipal("reader", frozenset({"reader"}))
    request = _request(_graph()).model_dump(mode="json")
    client = TestClient(app)
    assert client.post("/api/v1/scenario-whatif/preview", json=request).status_code == 403
    app.dependency_overrides[require_api_principal] = lambda: ApiPrincipal("analyst", frozenset({"analyst"}))
    fake = MagicMock(return_value={"candidate": {}})
    monkeypatch.setattr(service, "preview", fake)
    assert client.post("/api/v1/scenario-whatif/preview", json=request).status_code == 200
    assert client.post("/api/v1/scenario-whatif/preview", json={**request, "changes": [{"target": "fps", "value": 500}]}).status_code == 422
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        exploration_max_request_bytes=100000, simulation_max_timeline_frames=6,
        simulation_max_concurrent_runs=1))
    assert client.post("/api/v1/scenario-whatif/preview", json={**request, "options": {"frames": 7, "timeline_frames": 1}}).status_code == 422
    assert client.post("/api/v1/scenario-whatif/preview", json={**request, "options": {"frames": 4, "timeline_frames": 3}}).status_code == 422
    fake.assert_called_once()


def test_condition_hash_tracks_power_params_not_mutating_original(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    request = _request(graph)
    before = deepcopy(request.model_dump())
    first = service.preview(MagicMock(), request)
    second = service.preview(MagicMock(), request.model_copy(update={"config": request.config.model_copy(update={"bw_power_coeff": 90})}))
    assert first["condition_hash"] != second["condition_hash"]
    assert request.model_dump() == before


def test_condition_hash_keeps_baseline_config_when_candidate_overrides_it(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    request = _request(graph, config={"fps": 60}).model_copy(update={
        "changes": [WhatIfChange(target="fps", value=30)]})
    alternative = request.model_copy(update={"config": request.config.model_copy(update={"fps": 20})})
    first = service.preview(MagicMock(), request)
    second = service.preview(MagicMock(), alternative)
    assert first["candidate"]["metrics"] == second["candidate"]["metrics"]
    assert first["baseline"]["metrics"]["modeled_power_mw"] != second["baseline"]["metrics"]["modeled_power_mw"]
    assert first["condition_hash"] != second["condition_hash"]
    db = MagicMock()
    with pytest.raises(ConflictError, match="calculation inputs changed"):
        service.save_experiment(db, WhatIfExperimentRequest(preview_request=alternative,
                expected_condition_hash=first["condition_hash"], title="changed baseline"), "alice")
    db.add.assert_not_called()


def test_plan_resolves_relative_clock_against_baseline_set_clock(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    monkeypatch.setattr(service, "_graph", lambda db, scope: graph)
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    base = service._baseline_clocks(MagicMock(), service.WhatIfScope(**scope))["mfc_enc"]
    out = service.plan(MagicMock(), service.WhatIfPlanRequest(**scope, query="MFC 클럭 20% 낮추면 timing 여유는?"))
    assert out["status"] == "ready"
    assert out["changes"] == [{"target": "node_clock_mhz", "node_id": "mfc_enc", "value": round(base * 0.8, 1)}]
    assert any("× 0.8" in note for note in out["notes"])
    # every clarification choice is a complete, previewable change (no unresolved scale left)
    out = service.plan(MagicMock(), service.WhatIfPlanRequest(**scope, query="GDC 클럭 10% 올리면"))
    assert out["status"] == "clarification"
    changes = [c["change"] for cl in out["clarifications"] for c in cl["choices"]]
    assert changes and all("scale" not in c and c["value"] > 0 for c in changes)
    WhatIfPreviewRequest(**scope, expected_baseline_hash=out["baseline_hash"], changes=[changes[0]])
