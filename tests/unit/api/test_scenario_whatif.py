from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from scenario_db.api.services import analysis_inputs
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
    monkeypatch.setattr(analysis_inputs.AnalysisSelection, "load", lambda *a: analysis_inputs.AnalysisInputs(graph, {}, None))
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda *a: None)
    monkeypatch.setattr(service, "scenario_policy", lambda *a: None)


def test_preview_uses_timing_budget_and_explains_model_subtotal(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    db = MagicMock()
    out = service.preview(db, _request(graph))
    assert out["candidate"]["metrics"]["modeled_power_mw"] < out["baseline"]["metrics"]["modeled_power_mw"]
    assert out["candidate"]["metrics"]["cpu_power_mw"] > 0
    # complete = every IP of the modeled scope has a model; the whole-device total stays out of scope
    assert out["candidate"]["metrics"]["total_power_mw"] is None
    coverage = out["candidate"]["coverage"]
    assert coverage["complete"] is (not coverage["missing_components"]) and coverage["excluded_components"]
    assert out["model_lineage"]["engine"] == "timing-budget"
    assert out["candidate"]["metrics"]["latency_ms"] == max(v for k, v in out["candidate"]["report"]["latency"].items() if k.endswith("_ms"))
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_analysis_identity_tracks_power_option_definitions(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    req = _request(graph)
    baseline = service._baseline(MagicMock(), req, req)
    graph.scenario.power_options = {"knobs": [{"id": "changed"}]}
    with pytest.raises(ConflictError, match="model settings changed"):
        service._baseline(MagicMock(), req, req.model_copy(update={"expected_analysis_hash": baseline["analysis_hash"]}))


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
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    base = next(n["clock_mhz"] for n in service.targets(MagicMock(), service.WhatIfScope(**scope))["nodes"] if n["id"] == "mfc_enc")
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


def test_relative_fps_uses_resolved_profile_and_explicit_reopened_settings(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    def profile(db, shim):
        if "fps" not in shim.config.model_fields_set:
            shim.config = shim.config.model_copy(update={"fps": 60})
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", profile)
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    assert service.targets(MagicMock(), service.WhatIfScope(**scope))["fps"] == 60
    for config, expected in [({}, 30), ({"fps": 120}, 60)]:
        out = service.plan(MagicMock(), service.WhatIfPlanRequest(**scope, query="FPS 절반", config=config))
        assert out["changes"] == [{"target": "fps", "value": expected}]
        assert out["scope"] == scope


@pytest.mark.parametrize("query,expected", [
    ("MFC clock 100% 낮추면", "unsupported"),
    ("MFC clock 200% 낮추면, FPS 60", "partial"),
    ("GDC clock 100% 낮추면", "unsupported"),
    ("MFC clock 100배", "unsupported"),
])
def test_invalid_relative_clocks_are_ignored_without_shifting_sources(monkeypatch, query, expected):
    graph = _graph()
    _service(monkeypatch, graph)
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    available = service.targets(MagicMock(), service.WhatIfScope(**scope))
    for node in available["nodes"]:
        node["clock_mhz"] = 600
    monkeypatch.setattr(service, "targets", lambda *a: available)
    out = service.plan(MagicMock(), service.WhatIfPlanRequest(**scope, query=query))
    assert out["status"] == expected and out["ignored"] and not out["clarifications"]
    assert len(out["sources"]) == len(out["changes"])
    if out["changes"]:
        assert out["changes"] == [{"target": "fps", "value": 60}]
        assert out["sources"] == ["FPS 60"]


def test_plan_shares_simulation_admission_and_frame_limits(monkeypatch):
    from scenario_db.api.resource_limits import admission_slot
    app = create_app()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[require_api_principal] = lambda: ApiPrincipal("analyst", frozenset({"analyst"}))
    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        exploration_max_request_bytes=100000, simulation_max_timeline_frames=12, simulation_max_concurrent_runs=1))
    fake = MagicMock(return_value={"status": "ready"})
    monkeypatch.setattr(service, "plan", fake)
    request = {"project_ref": "p", "scenario_id": "s", "variant_id": "v", "query": "clock 절반"}
    with TestClient(app) as client:
        with admission_slot("simulation", 1):
            assert client.post("/api/v1/scenario-whatif/plan", json=request).status_code == 429
        assert client.post("/api/v1/scenario-whatif/plan", json={**request, "options": {"frames": 13}}).status_code == 422
        assert client.post("/api/v1/scenario-whatif/plan", json={**request, "config": {"measured_clock_ref": "measured"}}).status_code == 422
        assert client.post("/api/v1/scenario-whatif/plan", json=request).status_code == 200
    fake.assert_called_once()


def test_relative_clock_uses_requested_model_options_and_checks_profile_frames(monkeypatch):
    from fastapi import HTTPException
    graph = _graph()
    _service(monkeypatch, graph)
    scope = service.WhatIfScope(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    settings = service.WhatIfPlanRequest(**scope.model_dump(), query="clock 절반", config={"fps": 60}, options={"statistic": "mean"})
    fake = MagicMock(return_value={"metrics": {}, "coverage": {}, "report": {"ips": [{"node": "mfc_enc", "set_clock_mhz": 600}]}})
    monkeypatch.setattr(service, "_case", fake)
    assert next(n["clock_mhz"] for n in service.targets(MagicMock(), scope, settings)["nodes"] if n["id"] == "mfc_enc") == 600
    assert fake.call_args.args[1].fps == 60
    assert fake.call_args.args[2].statistic == "mean"
    fake.reset_mock()
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda db, shim: setattr(shim, "config", shim.config.model_copy(update={"timeline_frame_count": 100000})))
    with pytest.raises(HTTPException) as exc:
        service.targets(MagicMock(), scope, settings)
    assert exc.value.status_code == 422
    fake.assert_not_called()


def test_ask_reuses_one_baseline_but_separate_preview_and_save_recalculate(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    request = service.WhatIfAskRequest(**scope, changes=[{"target": "fps", "value": 60}])
    original = deepcopy(request.model_dump())
    original_graph = baseline_fingerprint(graph)
    calculate = MagicMock(wraps=service.analyze_timing_budget)
    monkeypatch.setattr(service, "analyze_timing_budget", calculate)
    asked = service.ask(MagicMock(), request)
    assert calculate.call_count == 2  # exactly baseline + candidate, with the real engine
    preview_request = WhatIfPreviewRequest(**scope, changes=request.changes,
                                          expected_baseline_hash=asked["baseline_hash"])
    previewed = service.preview(MagicMock(), preview_request)
    assert calculate.call_count == 4
    assert asked["result"] == previewed
    saved = service.save_experiment(
        MagicMock(), WhatIfExperimentRequest(preview_request=preview_request,
            expected_condition_hash=previewed["condition_hash"], title="same condition"), "analyst")
    assert calculate.call_count == 6
    assert saved["result"] == previewed
    assert request.model_dump() == original
    assert baseline_fingerprint(graph) == original_graph


def test_legacy_relative_clock_plan_evaluates_baseline_only_once(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    calculate = MagicMock(wraps=service.analyze_timing_budget)
    monkeypatch.setattr(service, "analyze_timing_budget", calculate)
    out = service.plan(MagicMock(), service.WhatIfPlanRequest(**scope, query="MFC clock 20% 낮추면"))
    calculate.assert_called_once()
    assert out["status"] == "ready" and out["changes"][0]["target"] == "node_clock_mhz"
    assert out["changes"][0]["value"] > 0


def test_stale_preview_stops_before_timing_evaluation(monkeypatch):
    graph = _graph()
    _service(monkeypatch, graph)
    calculate = MagicMock()
    monkeypatch.setattr(service, "analyze_timing_budget", calculate)
    with pytest.raises(ConflictError, match="baseline changed"):
        service.preview(MagicMock(), _request(graph).model_copy(update={"expected_baseline_hash": "0" * 64}))
    calculate.assert_not_called()


@pytest.mark.parametrize("kind", ["targets", "plan", "ask", "preview"])
def test_profile_restrictions_are_checked_before_loading_graph(monkeypatch, kind):
    graph = _graph()
    _service(monkeypatch, graph)
    load = MagicMock()
    monkeypatch.setattr(analysis_inputs.AnalysisSelection, "load", load)
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda db, resolved: setattr(
        resolved, "config", resolved.config.model_copy(update={"clock_basis": "measured"})))
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    request = {
        "targets": service.WhatIfScope(**scope),
        "plan": service.WhatIfPlanRequest(**scope, query="FPS 절반"),
        "ask": service.WhatIfAskRequest(**scope, changes=[{"target": "fps", "value": 60}]),
        "preview": _request(graph),
    }[kind]
    with pytest.raises(UnprocessableError, match="measured clock/CPU replay"):
        getattr(service, kind)(MagicMock(), request)
    load.assert_not_called()


def test_ask_candidate_lookup_failure_keeps_not_found_translation(monkeypatch):
    from scenario_db.exceptions import NotFoundError

    graph = _graph()
    _service(monkeypatch, graph)
    scope = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id, variant_id=graph.variant_id)
    monkeypatch.setattr(service, "apply_whatif_changes", MagicMock(side_effect=LookupError("missing candidate")))
    with pytest.raises(NotFoundError, match="missing candidate"):
        service.ask(MagicMock(), service.WhatIfAskRequest(**scope, changes=[{"target": "fps", "value": 60}]))


def test_preview_keeps_pre_refactor_contract_frame_limit_and_validation_model(monkeypatch):
    """Standalone preview: no service-level frame check (targets/plan/ask keep it) and the
    resolved config is validated as the preview request, as before the shared baseline."""
    graph = _graph()
    _service(monkeypatch, graph)
    limit = MagicMock()
    monkeypatch.setattr(service, "enforce_timeline_frame_limit", limit)
    service.preview(MagicMock(), _request(graph))
    limit.assert_not_called()
    scope = service.WhatIfScope(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id,
                                variant_id=graph.variant_id)
    service.targets(MagicMock(), scope)
    limit.assert_called_once()
    monkeypatch.setattr(analysis_inputs, "_apply_config_profile", lambda db, resolved: setattr(
        resolved, "config", resolved.config.model_copy(update={"clock_basis": "measured"})))
    with pytest.raises(UnprocessableError, match="WhatIfPreviewRequest"):
        service.preview(MagicMock(), _request(graph))
