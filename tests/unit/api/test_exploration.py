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
    assert "template:camera_minimal_otf_v1" in ids
    assert "template:camera_recording_pyramid_v1" in ids
    assert "template_sweep:camera_recording_pyramid_full_sbwc_template_sweep" in ids
    assert "template_sweep:camera_recording_pyramid_sbwc_template_sweep" in ids


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


def test_exploration_template_compile_endpoint_from_yaml():
    client, _ = _client_with_db()

    response = client.post(
        "/api/v1/exploration/templates/compile",
        json={
            "source_yaml": """
kind: scenario.chain_template
id: api-template
version: 1.0.0
schema_version: 1
project_ref: proj-next
source:
  width: 1920
  height: 1080
buffers:
  B0: [0, 0, 1920, 1080, YUV420, 8, COMP_OFF, 1.0]
blocks:
  - {id: isp0, template: isp, ip_ref: ip-isp-v12}
  - {id: dpu0, template: dpu, ip_ref: ip-dpu-v9}
links:
  - "sensor_src:COUT -> isp0:CIN | OTF"
  - "isp0:WDMA0 -> B0 | M2M"
  - "B0 -> dpu0:RDMA0 | M2M"
"""
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert body["scenario"]["id"] == "uc-api-template"
    assert body["scenario"]["variants"][0]["design_conditions"]["template_ref"] == "api-template@1.0.0"
    assert body["import_bundle"]["import_report"]["generated"]["chain_template"] == 1


def test_exploration_template_sweep_compile_endpoint_from_yaml():
    client, _ = _client_with_db()

    response = client.post(
        "/api/v1/exploration/template-sweeps/compile",
        json={
            "source_yaml": """
kind: scenario.chain_template_sweep
id: api-template-sweep
base_template:
  kind: scenario.chain_template
  id: api-template
  version: 1.0.0
  schema_version: 1
  project_ref: proj-next
  source:
    width: 1920
    height: 1080
  buffers:
    B0: [0, 0, 1920, 1080, YUV420, 8, COMP_OFF, 1.0]
  blocks:
    - {id: isp0, template: isp, ip_ref: ip-isp-v12}
    - {id: dpu0, template: dpu, ip_ref: ip-dpu-v9}
  links:
    - "sensor_src:COUT -> isp0:CIN | OTF"
    - "isp0:WDMA0 -> B0 | M2M"
    - "B0 -> dpu0:RDMA0 | M2M"
axes:
  - name: b0
    path: buffers.B0
    values:
      - {label: "off", value: [0, 0, 1920, 1080, YUV420, 8, COMP_OFF, 1.0]}
      - {label: sbwc, value: [0, 0, 1920, 1080, YUV420, 8, COMP_SBWC_LOSSLESS, 0.5]}
"""
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["persisted"] is False
    assert len(body["cases"]) == 2
    assert body["cases"][0]["variant_id"] == "api-template-1p0p0-b0-off"
    assert body["cases"][1]["variant_id"] == "api-template-1p0p0-b0-sbwc"
    assert body["import_bundle"]["import_report"]["generated"]["chain_template_sweep_case"] == 2


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


def test_exploration_template_preview_endpoint(monkeypatch):
    client, db = _client_with_db()

    def _fake_preview(db_arg, request):
        assert db_arg is db
        assert request.include_results is False
        return {
            "persisted": False,
            "baseline_case_id": "template-fhd30",
            "cases": [],
            "comparison": [{"case_id": "template-fhd30", "template": "api-template@1.0.0"}],
            "import_bundle": {"kind": "scenario.import_bundle"},
        }

    monkeypatch.setattr(exploration_router, "preview_template_request", _fake_preview)

    response = client.post(
        "/api/v1/exploration/templates/preview",
        json={
            "template": {
                "kind": "scenario.chain_template",
                "id": "api-template",
                "version": "1.0.0",
                "schema_version": 1,
                "project_ref": "proj-next",
                "source": {"width": 1920, "height": 1080},
                "buffers": {"B0": [0, 0, 1920, 1080, "YUV420", 8, "COMP_OFF", 1.0]},
                "blocks": [{"id": "isp0", "template": "isp", "ip_ref": "ip-isp-v12"}],
                "links": ["sensor_src:COUT -> isp0:CIN | OTF"],
            },
            "include_results": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["baseline_case_id"] == "template-fhd30"
    assert body["comparison"][0]["template"] == "api-template@1.0.0"


def test_exploration_template_sweep_preview_endpoint(monkeypatch):
    client, db = _client_with_db()

    def _fake_preview(db_arg, request):
        assert db_arg is db
        assert request.include_results is False
        return {
            "persisted": False,
            "baseline_case_id": "template-b0-off",
            "cases": [],
            "comparison": [{"case_id": "template-b0-off", "total_power_mw": 1.0}],
            "import_bundle": {"kind": "scenario.import_bundle"},
        }

    monkeypatch.setattr(exploration_router, "preview_template_sweep_request", _fake_preview)

    response = client.post(
        "/api/v1/exploration/template-sweeps/preview",
        json={
            "sweep": {
                "kind": "scenario.chain_template_sweep",
                "id": "api-template-sweep",
                "base_template": {
                    "kind": "scenario.chain_template",
                    "id": "api-template",
                    "version": "1.0.0",
                    "schema_version": 1,
                    "project_ref": "proj-next",
                    "source": {"width": 1920, "height": 1080},
                    "buffers": {"B0": [0, 0, 1920, 1080, "YUV420", 8, "COMP_OFF", 1.0]},
                    "blocks": [{"id": "isp0", "template": "isp", "ip_ref": "ip-isp-v12"}],
                    "links": ["sensor_src:COUT -> isp0:CIN | OTF"],
                },
                "axes": [],
            },
            "include_results": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["baseline_case_id"] == "template-b0-off"
