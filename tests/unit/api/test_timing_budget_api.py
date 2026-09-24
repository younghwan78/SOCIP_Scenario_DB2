from __future__ import annotations

import pytest

from scenario_db.sim.timing_budget import CpuPowerConfig, TimingBudgetOptions


@pytest.mark.parametrize("values", [[], [1], [-1, 1, 1, 1], [float("inf")] * 4])
def test_cpu_coefficients_are_validated(values):
    with pytest.raises(ValueError):
        CpuPowerConfig(coeff_uw_per_mhz_v2=values)


def test_whatif_scales_cannot_bypass_growth_bounds():
    with pytest.raises(ValueError):
        TimingBudgetOptions(whatif_scales=[11])

import sys
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.routers import timing_budget as router
from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services import timing_budget as service

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402


def _client(monkeypatch, name, fake):
    app = create_app()
    db = MagicMock()

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    monkeypatch.setattr(router, name, fake)
    return TestClient(app, raise_server_exceptions=False)


def test_variant_endpoint(monkeypatch):
    seen = {}

    def fake(db, request):
        seen["req"] = request
        return {
            "scenario_id": request.scenario_id,
            "variant_id": request.variant_id,
            "report": {"verdict": {"status": "ok"}},
        }

    client = _client(monkeypatch, "analyze_timing_budget_request", fake)
    res = client.post(
        "/api/v1/timing-budget/variant",
        json={
            "scenario_id": "uc-camera-recording",
            "variant_id": "cam-rec-r1-uhd30-vdis",
            "options": {"statistic": "mean", "eis": "off", "runtime_scale": 1.2},
        },
    )
    assert res.status_code == 200
    assert seen["req"].options.statistic == "mean" and seen["req"].options.runtime_scale == 1.2


def test_fleet_endpoint(monkeypatch):
    client = _client(
        monkeypatch,
        "analyze_timing_budget_fleet",
        lambda db, request: {
            "scenario_id": request.scenario_id,
            "rows": [{"variant_id": "a"}],
            "errors": [],
        },
    )
    res = client.post("/api/v1/timing-budget/fleet", json={"scenario_id": "uc-camera-recording"})
    assert res.status_code == 200 and res.json()["rows"][0]["variant_id"] == "a"


def test_variant_endpoint_rejects_bad_options(monkeypatch):
    client = _client(monkeypatch, "analyze_timing_budget_request", lambda db, request: None)
    res = client.post(
        "/api/v1/timing-budget/variant",
        json={"scenario_id": "s", "variant_id": "v", "options": {"statistic": "p99"}},
    )
    assert res.status_code == 422


def test_service_runs_read_only_with_default_dvfs_lookup(monkeypatch):
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
        "cam-rec-r1-uhd30-vdis",
        catalog,
    )
    monkeypatch.setattr(service, "load_canonical_graph", lambda db, s, v: graph)
    monkeypatch.setattr(service, "_graph_soc_ref", lambda g: None)
    db = MagicMock()
    res = service.analyze_timing_budget_request(
        db,
        TimingBudgetRequest(scenario_id="uc-camera-recording", variant_id="cam-rec-r1-uhd30-vdis"),
    )
    assert res.report["verdict"]["status"] in {"ok", "clock_up", "fail"}
    assert res.dvfs_table_ref is None
    db.add.assert_not_called()
    db.commit.assert_not_called()
