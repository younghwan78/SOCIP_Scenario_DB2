from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import exploration as exploration_router
from scenario_db.api.schemas.exploration import (
    ExplorationRecipeCompileRequest,
    ExplorationSweepCompileRequest,
    ExplorationSweepPreviewRequest,
    ExplorationTemplateSweepCompileRequest,
)
from scenario_db.api.services.exploration import (
    compile_recipe_request,
    compile_sweep_request,
    compile_template_sweep_request,
    preview_sweep_request,
)
from scenario_db.db.models.capability import IpCatalog, SocPlatform
from scenario_db.db.models.definition import Project


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


def test_exploration_recipe_compile_warns_when_selected_db_project_lacks_fixture_ips():
    db = _ExplorationDb(
        projects=[
            Project(
                id="proj-db",
                schema_version="2.2",
                metadata_={"soc_ref": "soc-db"},
                yaml_sha256="sha",
            )
        ],
        socs=[
            SocPlatform(
                id="soc-db",
                schema_version="2.2",
                ips=[{"ref": "ip-known"}],
                yaml_sha256="sha",
            )
        ],
        ips=[
            IpCatalog(
                id="ip-known",
                schema_version="2.2",
                category="camera",
                hierarchy={},
                capabilities={"sim": {"ppc": 4, "unit_power_mw_mp": 1.0}},
                yaml_sha256="sha",
            )
        ],
    )
    request = ExplorationRecipeCompileRequest(
        db_project_ref="proj-db",
        source_yaml="""
id: api-recipe
project_ref: fixture-project
source:
  node_id: sensor_src
  ip_ref: ip-sensor-missing
  width: 1920
  height: 1080
pipeline:
  - id: isp0
    template: isp
    ip_ref: ip-isp-missing
"""
    )

    response = compile_recipe_request(db, request)

    assert any("ip-sensor-missing" in warning for warning in response.warnings)
    assert any("ip-isp-missing" in warning for warning in response.warnings)
    assert response.import_bundle["import_report"]["ok"] is False


def test_exploration_sweep_preview_exposes_selected_db_catalog_warnings():
    db = _ExplorationDb(
        projects=[
            Project(
                id="proj-db",
                schema_version="2.2",
                metadata_={"soc_ref": "soc-db"},
                yaml_sha256="sha",
            )
        ],
        socs=[
            SocPlatform(
                id="soc-db",
                schema_version="2.2",
                ips=[{"ref": "ip-known"}],
                yaml_sha256="sha",
            )
        ],
        ips=[
            IpCatalog(
                id="ip-known",
                schema_version="2.2",
                category="camera",
                hierarchy={},
                capabilities={"sim": {"ppc": 4, "unit_power_mw_mp": 1.0}},
                yaml_sha256="sha",
            )
        ],
    )
    request = ExplorationSweepPreviewRequest(
        db_project_ref="proj-db",
        source_yaml="""
id: api-preview-sweep
base_recipe:
  id: api-preview-recipe
  project_ref: fixture-project
  source:
    node_id: sensor_src
    ip_ref: ip-sensor-missing
    width: 1920
    height: 1080
  pipeline:
    - id: isp0
      template: isp
      ip_ref: ip-isp-missing
axes: []
""",
    )

    response = preview_sweep_request(db, request)

    assert any("fixture-project" in warning and "proj-db" in warning for warning in response.warnings)
    assert any("ip-sensor-missing" in warning for warning in response.warnings)
    assert any("ip-isp-missing" in warning for warning in response.warnings)
    assert any("ip-isp-missing" in warning for warning in response.cases[0].warnings)
    assert response.import_bundle["import_report"]["ok"] is False


def test_exploration_sweep_compile_deduplicates_missing_ip_warnings_across_cases():
    db = _ExplorationDb(
        projects=[
            Project(
                id="proj-db",
                schema_version="2.2",
                metadata_={"soc_ref": "soc-db"},
                yaml_sha256="sha",
            )
        ],
        socs=[
            SocPlatform(
                id="soc-db",
                schema_version="2.2",
                ips=[],
                yaml_sha256="sha",
            )
        ],
        ips=[],
    )
    request = ExplorationSweepCompileRequest(
        db_project_ref="proj-db",
        source_yaml="""
id: api-sweep
base_recipe:
  id: api-sweep-recipe
  project_ref: fixture-project
  source:
    width: 1920
    height: 1080
  pipeline:
    - id: isp0
      template: isp
      ip_ref: ip-isp-missing
axes:
  - name: fps
    path: source.fps
    values: [30, 60]
""",
    )

    response = compile_sweep_request(db, request)

    assert len([warning for warning in response.warnings if "ip-isp-missing" in warning]) == 1


def test_exploration_template_sweep_compile_deduplicates_missing_ip_warnings_across_cases():
    db = _ExplorationDb(
        projects=[
            Project(
                id="proj-db",
                schema_version="2.2",
                metadata_={"soc_ref": "soc-db"},
                yaml_sha256="sha",
            )
        ],
        socs=[
            SocPlatform(
                id="soc-db",
                schema_version="2.2",
                ips=[],
                yaml_sha256="sha",
            )
        ],
        ips=[],
    )
    request = ExplorationTemplateSweepCompileRequest(
        db_project_ref="proj-db",
        source_yaml="""
kind: scenario.chain_template_sweep
id: api-template-sweep
base_template:
  kind: scenario.chain_template
  id: api-template
  version: 1.0.0
  schema_version: 1
  project_ref: fixture-project
  source:
    width: 1920
    height: 1080
  buffers:
    B0: [0, 0, 1920, 1080, YUV420, 8, COMP_OFF, 1.0]
  blocks:
    - {id: isp0, template: isp, ip_ref: ip-isp-missing}
  links:
    - "sensor_src:COUT -> isp0:CIN | OTF"
axes:
  - name: b0
    path: buffers.B0
    values:
      - {label: "off", value: [0, 0, 1920, 1080, YUV420, 8, COMP_OFF, 1.0]}
      - {label: sbwc, value: [0, 0, 1920, 1080, YUV420, 8, COMP_SBWC_LOSSLESS, 0.5]}
""",
    )

    response = compile_template_sweep_request(db, request)

    assert len([warning for warning in response.warnings if "ip-isp-missing" in warning]) == 1


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


class _ExplorationQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        return _ExplorationQuery(
            row
            for row in self._rows
            if all(getattr(row, key) == value for key, value in kwargs.items())
        )

    def all(self):
        return self._rows

    def one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise AssertionError("fake query expected at most one row")
        return self._rows[0]


class _ExplorationDb:
    def __init__(self, *, projects=None, socs=None, ips=None):
        self._projects = list(projects or [])
        self._socs = list(socs or [])
        self._ips = list(ips or [])

    def query(self, model):
        if model is Project:
            return _ExplorationQuery(self._projects)
        if model is SocPlatform:
            return _ExplorationQuery(self._socs)
        if model is IpCatalog:
            return _ExplorationQuery(self._ips)
        return _ExplorationQuery([])
