from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import simulation as simulation_router
from scenario_db.api.schemas.simulation import API_MAX_SW_MARGIN_SAMPLES, SwMarginRequest
from scenario_db.sim import service

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402


def _client(monkeypatch, fake):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    monkeypatch.setattr(simulation_router, "analyze_sw_margin_request", fake)
    return TestClient(app, raise_server_exceptions=False)


def test_sw_margin_endpoint_returns_report(monkeypatch):
    seen = {}

    def fake(db, request):
        seen["request"] = request
        return {
            "scenario_id": request.scenario_id,
            "variant_id": request.variant_id,
            "report": {"required": {"margin": 0.12}},
        }

    client = _client(monkeypatch, fake)
    response = client.post(
        "/api/v1/simulation/sw-margin",
        json={
            "scenario_id": "uc-camera-recording",
            "variant_id": "cam-rec-r1-uhd30-vdis",
            "options": {"statistic": "max", "growth": {"runtime_scale": 1.2}},
        },
    )
    assert response.status_code == 200
    assert response.json()["report"]["required"]["margin"] == 0.12
    assert seen["request"].options.growth.runtime_scale == 1.2


def test_sw_margin_endpoint_limits_monte_carlo_samples(monkeypatch):
    client = _client(monkeypatch, lambda db, request: None)
    response = client.post(
        "/api/v1/simulation/sw-margin",
        json={
            "scenario_id": "s",
            "variant_id": "v",
            "options": {"monte_carlo_samples": API_MAX_SW_MARGIN_SAMPLES + 1},
        },
    )
    assert response.status_code == 422


def test_analyze_sw_margin_request_runs_read_only(monkeypatch):
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(
            id=d["id"],
            schema_version=d["schema_version"],
            category=d["category"],
            hierarchy=d["hierarchy"],
            capabilities=d["capabilities"],
            yaml_sha256="fixture",
        )
    graph = graph_from_fixture(
        read(FIXTURE / "02_definition" / "uc-camera-recording.yaml"),
        "cam-rec-r1-fhd60-sdr",
        catalog,
    )
    monkeypatch.setattr(service, "load_canonical_graph", lambda db, s, v: graph)
    db = MagicMock()
    request = SwMarginRequest(
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-r1-fhd60-sdr",
        options={
            "growth_sweep": [1.0],
            "per_ip_plan": False,
            "grid_step": 0.05,
            "constraints": {"frames": 8},
        },
    )
    response = service.analyze_sw_margin_request(db, request)
    assert response.report["required"]["status"] == "solved"
    assert response.dvfs_table_ref is None
    db.add.assert_not_called()
    db.commit.assert_not_called()
