"""Assumed IP loads (GPU / NPU …) declared in design_conditions (scenario_db.sim.assumed_loads)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim import timing_budget as tb  # noqa: E402
from scenario_db.sim.assumed_loads import assumed_loads  # noqa: E402


def test_parse_keeps_positive_numeric_loads_with_their_basis():
    got = assumed_loads({"assumed_gpu_mw": 350, "assumed_gpu_basis": "prev UHD120 GPU rail", "assumed_npu_mw": "120.5",
                         "assumed_dsp_mw": 0, "assumed_bad_mw": "n/a", "assumed_flag_mw": True, "fps": 120,
                         "assumed_big_core_mw": float("inf")})
    assert got == {"gpu": {"mw": 350.0, "basis": "prev UHD120 GPU rail"}, "npu": {"mw": 120.5, "basis": None}}
    assert assumed_loads(None) == {} and assumed_loads({"resolution": "UHD"}) == {}


@pytest.fixture(scope="module")
def graph_factory():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    raw = read(FIXTURE / "02_definition" / "uc-cam-recording-e2600.yaml")
    return lambda variant: graph_from_fixture(raw, variant, catalog)


def test_assumed_loads_add_a_constant_to_ip_and_total_power_only(graph_factory):
    g = graph_factory("cam-rec-r1-uhd120")
    base = tb.analyze_timing_budget(g)
    assert "assumed_by_ip" not in base["power"]  # nothing declared = output unchanged
    g.variant.design_conditions = {**(g.variant.design_conditions or {}), "assumed_gpu_mw": 300, "assumed_npu_mw": 50,
                                   "assumed_gpu_basis": "previous project GPU rail"}
    loaded = tb.analyze_timing_budget(g)
    p0, p1 = base["power"], loaded["power"]
    assert p1["assumed_by_ip"] == {"gpu": 300.0, "npu": 50.0}
    assert p1["assumed_basis"] == {"gpu": "previous project GPU rail"}
    assert p1["hw_mw"] == pytest.approx(p0["hw_mw"] + 350, abs=0.02)
    assert p1["total_mw"] == pytest.approx(p0["total_mw"] + 350, abs=0.02)
    assert (p1["cpu_mw"], p1["bw_mw"]) == (p0["cpu_mw"], p0["bw_mw"])
    assert p1["hw_by_ip"] == p0["hw_by_ip"]  # real pipeline nodes only
    assert loaded["verdict"]["status"] == base["verdict"]["status"]


def test_timing_budget_condition_hash_tracks_assumed_loads(monkeypatch):
    from types import SimpleNamespace

    from scenario_db.api.services import timing_budget as svc

    monkeypatch.setattr(svc, "build_simulation_inputs", lambda graph, config: None)
    monkeypatch.setattr(svc, "_request_hash", lambda *a, **k: "same-simulation-inputs")
    opts, shim = tb.TimingBudgetOptions(), SimpleNamespace(config=None)
    graph = lambda dc: SimpleNamespace(variant=SimpleNamespace(design_conditions=dc))  # noqa: E731
    base = svc._condition_hash(graph({"fps": 30}), opts, shim, {})
    assert svc._condition_hash(graph({"fps": 30, "assumed_gpu_basis": "note only"}), opts, shim, {}) == base
    gpu = svc._condition_hash(graph({"fps": 30, "assumed_gpu_mw": 50}), opts, shim, {})
    assert gpu != base and gpu != svc._condition_hash(graph({"fps": 30, "assumed_gpu_mw": 400}), opts, shim, {})


def test_dram_write_per_frame_sums_every_write_port(graph_factory):
    r = tb.analyze_timing_budget(graph_factory("cam-rec-r1-uhd30-sdr"))
    # UHD YUV420 8-bit is 12.4 MB a plane set; the whole camera chain writes several of those per frame
    assert r["bw"]["write_mb_frame"] > 12.4
    writes = sum(d["bw_mbs"] for d in r.get("dma") or [] if d.get("direction") == "write") if r.get("dma") else None
    if writes is not None:
        assert r["bw"]["write_mb_frame"] == pytest.approx(writes * r["period_ms"] / 1000, rel=1e-3)
