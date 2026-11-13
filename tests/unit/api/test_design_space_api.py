"""Design-space request form and the lever catalog endpoint."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import arch_exploration as router
from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest
from scenario_db.api.services import arch_exploration as svc
from scenario_db.api.services.design_space import lever_catalog
from scenario_db.api.services.whatif_conditions import CHANGE_KINDS
from scenario_db.sim.arch_exploration import ArchExplorationSpec
from scenario_db.sim.design_space import BUILTIN_LEVERS, design_space_from_spec


def _client(monkeypatch, **fakes):
    app = create_app()

    def _override():
        yield MagicMock()

    app.dependency_overrides[get_db] = _override
    for name, fake in fakes.items():
        monkeypatch.setattr(router.svc, name, fake)
    return TestClient(app, raise_server_exceptions=False)


def _space(**spec):
    return design_space_from_spec(ArchExplorationSpec.model_validate(spec)).model_dump(mode="json", exclude_unset=True)


def test_design_space_request_runs_the_same_spec(monkeypatch):
    seen = {}

    def fake(db, request, user, *, release_connection=False):
        seen["req"] = request
        return {"id": "EXP-1", "variants": []}

    spec = {"axes": {"runtime_scales": [1.0, 1.3], "dvfs_headroom_levels": 2}, "objective": {"statistic": "mean"}}
    c = _client(monkeypatch, run_exploration=fake)
    res = c.post("/api/v1/arch/exploration/runs", json={"scenario_ids": ["uc-a"], "design_space": _space(**spec)})
    assert res.status_code == 200, res.text
    request = seen["req"]
    assert request.design_space is None
    assert request.spec.model_dump(mode="json") == ArchExplorationSpec.model_validate(spec).model_dump(mode="json")
    # the throughput judgement is still the project policy's when the caller did not choose one
    assert "throughput_model" not in request.spec.timing.model_fields_set


def test_design_space_request_survives_the_job_queue_round_trip():
    request = ArchExplorationRunRequest.model_validate({
        "scenario_ids": ["uc-a"], "design_space": _space(axes={"statistics": ["mean"]}, objective={"statistic": "mean"})})
    queued = request.model_dump(mode="json", exclude_unset=True)  # what exploration_jobs.submit stores
    again = ArchExplorationRunRequest.model_validate(queued)
    assert again.spec.model_dump(mode="json") == request.spec.model_dump(mode="json")
    assert again.spec.axes.statistics == ["mean"]
    assert "throughput_model" not in again.spec.timing.model_fields_set


@pytest.mark.parametrize("body, message", [
    ({"spec": {}, "design_space": {}}, "either spec or design_space"),
    ({"design_space": {"axes": [{"lever": "warp_drive", "values": [1]}]}}, "unknown lever: warp_drive"),
    ({"design_space": {"axes": [{"lever": "compression", "params": {"buffer_id": "b"}, "values": ["COMP_OFF"]}]}},
     "lever cannot be explored as an axis: compression"),
    ({"spec": {"axes": {"levers": [{"lever": "dvfs_level", "params": {"domain": "CAM"}, "values": [{"level": 3}]}]}}},
     "lever cannot be explored as an axis: dvfs_level"),
    ({"spec": {"axes": {"levers": [{"lever": "eis", "values": ["on"]}]}}}, "built-in axis"),
    ({"spec": {"axes": {"levers": [{"lever": "warp_drive", "values": [1]}]}}}, "unknown lever: warp_drive"),
    ({"spec": {"axes": {"levers": [{"lever": "fps", "values": ["fast"]}]}}}, "must be a number"),
    ({"spec": {"axes": {"levers": [{"lever": "fps", "values": [24, 24.0]}]}}}, "values must be distinct"),
    ({"spec": {"axes": {"levers": [{"lever": "fps", "values": [24]}, {"lever": "fps", "values": [60]}]}}},
     "more than once for the same target"),
    ({"spec": {"axes": {"levers": [{"lever": "chain_size", "values": [[1920, 1080]]}]}}}, "node changes require node_id"),
    ({"spec": {"axes": {"levers": [{"lever": "chain_size", "params": {"node_id": "a", "width": 64},
                                    "values": [[1920, 1080]]}]}}}, "width is set twice"),
    ({"spec": {"axes": {"lever_max_sets": 2, "levers": [{"lever": "fps", "values": [24, 48, 60]}]}}}, "3 combinations"),
    ({"design_space": {"axes": [{"lever": "dvfs_headroom", "values": [2]}]}}, "raise steps"),
    ({"design_space": {"schema_version": "sdb.designspace/9"}}, "sdb.designspace/1"),
])
def test_bad_design_space_requests_are_422(monkeypatch, body, message):
    c = _client(monkeypatch, run_exploration=lambda *a, **k: {"id": "x", "variants": []})
    for path in ("/api/v1/arch/exploration/runs", "/api/v1/arch/exploration/jobs"):
        res = c.post(path, json={"scenario_ids": ["uc-a"]} | body)
        assert res.status_code == 422, res.text
        assert message in res.text


def test_lever_catalog_lists_builtin_axes_and_every_whatif_kind(monkeypatch):
    catalog = lever_catalog()
    ids = [row["id"] for row in catalog["levers"]]
    assert len(ids) == len(set(ids))  # a built-in id never shadows a What-if target
    assert ids[: len(BUILTIN_LEVERS)] == list(BUILTIN_LEVERS)
    assert set(ids[len(BUILTIN_LEVERS):]) == set(CHANGE_KINDS)
    by_id = {row["id"]: row for row in catalog["levers"]}
    assert by_id["chain_size"] | {"description": ""} == {
        "id": "chain_size", "label": "IP crop · downscale", "group": "size", "shape": "size", "unit": "",
        "description": "", "source": "whatif", "evaluation": "resim", "explorable": True, "selector": "node_id",
        "selector_optional": False, "needs_param": False, "max_value": None, "iq": "required", "value_optional": False}
    assert by_id["buffer_compression"]["explorable"] and by_id["compression"]["source"] == "whatif"
    assert {row["id"] for row in catalog["levers"] if row["source"] == "whatif" and not row["explorable"]} == {
        "compression", "dvfs_level", "node_param", "sensor_binding"}

    c = _client(monkeypatch)
    res = c.get("/api/v1/arch/exploration/levers")
    assert res.status_code == 200 and res.json() == catalog
    assert c.get("/api/v1/arch/exploration/levers", headers={"If-None-Match": res.headers["etag"]}).status_code == 304


def test_run_detail_carries_the_design_space_of_its_spec():
    row = SimpleNamespace(
        id="EXP-1", title="t", scenario_type="camera", project_ref="p", soc_ref=None, dvfs_table_ref=None,
        engine_rev="arch-exploration/15", summary={}, created_by=None, created_at=None, errors=[], variants=[],
        spec=ArchExplorationSpec().model_dump(mode="json") | {"scenario_ids": ["uc-a"], "manifest": {"blobs": {}}})
    detail = svc.run_detail(row)
    assert [a["lever"] for a in detail["design_space"]["axes"]] == list(BUILTIN_LEVERS)
    assert detail["spec"]["axes"] == row.spec["axes"]  # the stored spec is still returned as is
