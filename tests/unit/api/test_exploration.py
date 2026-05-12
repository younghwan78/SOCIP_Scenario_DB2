from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import exploration as exploration_router


def _client_with_db(db: MagicMock | None = None) -> tuple[TestClient, MagicMock]:
    app = create_app()
    db = db or MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app, raise_server_exceptions=False), db


def test_exploration_examples_list_endpoint():
    client, _ = _client_with_db()

    response = client.get("/api/v1/exploration/examples")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 6
    ids = {item["id"] for item in body["items"]}
    assert "recipe:camera_crop_scale_m2m" in ids
    assert "sweep:camera_fps_format_sweep" in ids


def test_exploration_example_detail_endpoint():
    client, _ = _client_with_db()

    response = client.get("/api/v1/exploration/examples/recipe:camera_crop_scale_m2m")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "recipe:camera_crop_scale_m2m"
    assert body["type"] == "recipe"
    assert body["payload"]["id"] == "explore-camera-crop-scale-m2m"
    assert "pipeline:" in body["yaml_text"]


def test_exploration_example_detail_404():
    client, _ = _client_with_db()

    response = client.get("/api/v1/exploration/examples/recipe:missing")

    assert response.status_code == 404


def test_exploration_recipe_compile_endpoint_from_yaml():
    client, _ = _client_with_db()

    response = client.post(
        "/api/v1/exploration/recipes/compile",
        json={
            "source_yaml": """
id: api-recipe
project_ref: proj-next
source:
  width: 1920
  height: 1080
pipeline:
  - id: isp0
    template: isp
    ip_ref: ip-isp-v12
"""
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert body["scenario"]["id"] == "uc-api-recipe"
    assert body["scenario"]["variants"][0]["id"] == "explore-0"
    assert body["import_bundle"]["kind"] == "scenario.import_bundle"


def test_exploration_recipe_compile_endpoint_422_for_missing_payload():
    client, _ = _client_with_db()

    response = client.post("/api/v1/exploration/recipes/compile", json={})

    assert response.status_code == 422


def test_exploration_sweep_compile_endpoint_from_dict():
    client, _ = _client_with_db()

    response = client.post(
        "/api/v1/exploration/sweeps/compile",
        json={
            "sweep": {
                "id": "api-sweep",
                "base_recipe": {
                    "id": "api-sweep-recipe",
                    "project_ref": "proj-next",
                    "source": {"width": 1920, "height": 1080},
                    "pipeline": [{"id": "isp0", "template": "isp", "ip_ref": "ip-isp-v12"}],
                },
                "axes": [{"name": "fps", "path": "source.fps", "values": [30, 60]}],
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert len(body["cases"]) == 2
    assert body["cases"][0]["axis_values"]["fps"] == 30.0


def test_exploration_sweep_preview_endpoint(monkeypatch):
    client, db = _client_with_db()

    def _fake_preview(db_arg, request):
        assert db_arg is db
        assert request.include_results is False
        assert request.config.include_timeline is False
        return {
            "persisted": False,
            "baseline_case_id": "explore-fps-30",
            "cases": [],
            "comparison": [{"case_id": "explore-fps-30", "total_power_mw": 1.0}],
            "import_bundle": {"kind": "scenario.import_bundle"},
        }

    monkeypatch.setattr(exploration_router, "preview_sweep_request", _fake_preview)

    response = client.post(
        "/api/v1/exploration/sweeps/preview",
        json={
            "sweep": {
                "id": "api-preview",
                "base_recipe": {
                    "id": "api-preview-recipe",
                    "project_ref": "proj-next",
                    "source": {"width": 1920, "height": 1080},
                    "pipeline": [{"id": "isp0", "template": "isp", "ip_ref": "ip-isp-v12"}],
                },
            },
            "include_results": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert body["comparison"][0]["total_power_mw"] == 1.0
