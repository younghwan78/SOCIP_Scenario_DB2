from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import simulation as simulation_router


def test_simulation_run_endpoint(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    def _fake_run(db_arg, request):
        assert db_arg is db
        assert request.scenario_id == "uc-camera-recording"
        return {
            "evidence_id": "sim-uc-camera-recording-FHD30-SDR-H265-abc123",
            "status": "completed",
            "cached": False,
            "params_hash": "abc123",
            "warnings": ["isp0 has ppc=0"],
            "kpi": {"total_power_mw": 1.0},
            "result": None,
        }

    monkeypatch.setattr(simulation_router, "run_simulation_request", _fake_run)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/simulation/run",
        json={
            "scenario_id": "uc-camera-recording",
            "variant_id": "FHD30-SDR-H265",
            "execution_context": {
                "silicon_rev": "EVT0",
                "sw_baseline_ref": "sw-vendor-v1.2.3",
                "thermal": "hot",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_id"].startswith("sim-uc-camera-recording")
    assert body["cached"] is False
    assert body["warnings"] == ["isp0 has ppc=0"]
    assert body["kpi"]["total_power_mw"] == 1.0


def test_delete_simulation_result_endpoint(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    def _fake_delete(db_arg, evidence_id):
        assert db_arg is db
        assert evidence_id == "sim-1"
        return True

    monkeypatch.setattr(simulation_router, "delete_simulation_evidence", _fake_delete)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.delete("/api/v1/simulation/results/sim-1")

    assert response.status_code == 204
    db.commit.assert_called_once()


def test_delete_simulation_result_404(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    monkeypatch.setattr(simulation_router, "delete_simulation_evidence", lambda db_arg, evidence_id: False)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.delete("/api/v1/simulation/results/missing")

    assert response.status_code == 404
    db.commit.assert_not_called()
