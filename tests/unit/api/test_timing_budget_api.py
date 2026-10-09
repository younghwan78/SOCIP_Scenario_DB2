from __future__ import annotations

import pytest

from scenario_db.sim.timing_budget import CpuPowerConfig, TimingBudgetOptions


@pytest.mark.parametrize("values", [[], [-1, 1, 1, 1], [float("inf")] * 4])
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


def test_dvfs_whatif_enforces_configured_frame_limit(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(router, "get_settings", lambda: SimpleNamespace(
        exploration_max_request_bytes=100000, simulation_max_timeline_frames=6,
        simulation_max_concurrent_runs=1,
    ))
    service_call = MagicMock(return_value={"rows": []})
    client = _client(monkeypatch, "analyze_dvfs_whatif_request", service_call)
    response = client.post("/api/v1/timing-budget/dvfs-whatif", json={
        "scenario_id": "s", "variant_id": "v", "options": {"frames": 7},
    })
    assert response.status_code == 422
    service_call.assert_not_called()
    valid = client.post("/api/v1/timing-budget/dvfs-whatif", json={
        "scenario_id": "s", "variant_id": "v", "options": {"frames": 6},
    })
    assert valid.status_code == 200
    service_call.assert_called_once()


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
        read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml"),
        "cam-rec-r1-uhd30-vdis",
        catalog,
    )
    monkeypatch.setattr(service, "load_canonical_graph", lambda db, s, v: graph)
    monkeypatch.setattr(service, "_graph_soc_ref", lambda g: None)
    db = MagicMock()
    res = service.analyze_timing_budget_request(
        db,
        TimingBudgetRequest(scenario_id="uc-cam-recording-e2600", variant_id="cam-rec-r1-uhd30-vdis"),
    )
    assert res.report["verdict"]["status"] in {"ok", "clock_up", "fail"}
    assert res.dvfs_table_ref is None
    db.add.assert_not_called()
    db.commit.assert_not_called()


def _uhd30_graph_and_dvfs():
    import yaml
    from scenario_db.sim.models import DVFSTable

    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    graph = graph_from_fixture(read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml"), "cam-rec-r1-uhd30-vdis", catalog)
    doc = yaml.safe_load((FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml").read_text(encoding="utf-8"))
    return graph, {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}


def test_rt_clock_follows_sensor_readout_and_nrt_reports_each_dvfs_domain():
    from scenario_db.sim.timing_budget import analyze_timing_budget, stage_driver

    graph, dvfs = _uhd30_graph_and_dvfs()
    base = analyze_timing_budget(graph, TimingBudgetOptions(), dvfs_tables=dvfs)
    rt = {d["domain"]: d for d in base["stage_domains"]["rt"]}
    # RT (8 PPC): min clock whose HW time fits the read-out (120.8 MHz -> CAM floor L7 133), HW time = read-out window
    assert rt["CAM"]["basis"] == "sensor_readout" and rt["CAM"]["set_mhz"] == 133 and rt["CAM"]["required_mhz"] == 120.8
    stage = {s["id"]: s for s in base["stages"]}
    assert stage["rt"]["hw_ms"] == 10.18
    # NRT spans two DVFS domains, never merged into one clock
    nrt = {d["domain"]: d for d in base["stage_domains"]["nrt"]}
    assert set(nrt) == {"CAM", "INTCAM"}
    assert nrt["INTCAM"]["set_mhz"] == 133 and nrt["INTCAM"]["set_reason"] == "dvfs_floor"
    assert nrt["CAM"]["set_mhz"] == 133 and nrt["CAM"]["set_reason"] == "dvfs_floor"
    # OTF chain mtnr -> msnr (INTCAM) -> yuvp -> mcsc (CAM): rate-locked across domains, one group time
    ips = {i["node"]: i for i in base["ips"]}
    assert ips["yuvp"]["otf_group"] == ips["mtnr"]["otf_group"] is not None
    assert ips["yuvp"]["hw_ms"] == ips["mtnr"]["hw_ms"] == 18.489
    assert nrt["CAM"]["hw_ms"] == nrt["INTCAM"]["hw_ms"]
    # LME runs inside the pre_me_rta SW stage: it never drives the NRT clock
    assert stage_driver(base["ips"], "nrt")["node"] in {"mtnr", "msnr", "yuvp", "mcsc"}   # OTF chain, never LME

    grown = analyze_timing_budget(graph, TimingBudgetOptions(runtime_scale=1.4), dvfs_tables=dvfs)
    intcam = next(d for d in grown["stage_domains"]["nrt"] if d["domain"] == "INTCAM")
    assert intcam["required_mhz"] == 135.2 and intcam["set_mhz"] == 266 and intcam["level"] == 4
    # CAM is now lifted by the NRT need (YUVP), and the RT members follow the shared domain
    rt_cam = next(d for d in grown["stage_domains"]["rt"] if d["domain"] == "CAM")
    assert rt_cam["set_mhz"] == 266 and rt_cam["set_reason"] == "domain" and rt_cam["domain_leader"] == "yuvp"
    assert grown["verdict"]["status"] == "clock_up" and grown["verdict"]["reasons"] == []
    assert any("INTCAM" in n and "266" in n for n in grown["verdict"]["notes"])

    # SW margin: RT is read-out bound, Output sits on the INT floor -> clocks unchanged, only the RT budget moves
    wide = analyze_timing_budget(graph, TimingBudgetOptions(rt_margin=0.35, output_margin=0.35), dvfs_tables=dvfs)
    assert [i["set_clock_mhz"] for i in wide["ips"]] == [i["set_clock_mhz"] for i in base["ips"]]
    assert next(s for s in wide["stages"] if s["id"] == "rt")["budget_ms"] < stage["rt"]["budget_ms"]
    out = next(d for d in wide["stage_domains"]["output"] if d["domain"] == "INT")
    assert out["set_reason"] == "dvfs_floor"
