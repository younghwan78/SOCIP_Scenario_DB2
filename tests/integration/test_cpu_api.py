"""CPU analysis routes resolve versioned topologies from PostgreSQL."""
import pytest
from sqlalchemy.orm import Session

from scenario_db.db.models.capability import PowerModelParams

pytestmark = pytest.mark.integration


@pytest.fixture
def cpu_topology(engine):
    with Session(engine) as db:
        row = PowerModelParams(
            id="pmp-cpu-api-test", schema_version="2.2", soc_ref="soc-exynos2500", version=9876,
            status="draft", yaml_sha256="test", params={"cpu": {"clusters": [
                {"name": "BIG", "cores": 2, "opps": [{"mhz": 1000, "mv": 700, "mw_per_core": 100}]}]}},
        )
        db.add(row)
        db.commit()
        yield row.id
        db.delete(row)
        db.commit()


def test_cpu_inputs_and_analysis_use_postgres_topology(api_client, cpu_topology):
    inputs = api_client.get("/api/v1/cpu/inputs")
    assert inputs.status_code == 200
    assert any(t["id"] == cpu_topology and t["clusters"] == ["BIG"] for t in inputs.json()["topologies"])
    request = {"power_params_ref": f"{cpu_topology}@9876", "cpu_profile": {
        "tasks": [{"task": "ui", "cluster": "BIG", "cycles": 1000000}],
        "clusters": {"BIG": {"freq_residency": {"1000": 1}}},
    }}
    for route in ("whatif", "sweep"):
        response = api_client.post(f"/api/v1/cpu/{route}", json=request)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        reference = result["base"] if route == "whatif" else result["reference"]
        assert reference["feasible"] and reference["total_mw"] > 0
        invalid = api_client.post(f"/api/v1/cpu/{route}", json={**request, "growth": {"ui": -1}})
        assert invalid.status_code == 422
        wrong_version = api_client.post(f"/api/v1/cpu/{route}", json={**request, "power_params_ref": f"{cpu_topology}@1"})
        assert wrong_version.status_code == 422
    unknown = api_client.post("/api/v1/cpu/sweep", json={**request, "sweep_clusters": {"ui": ["typo"]}})
    assert unknown.status_code == 422
    coupled = api_client.post("/api/v1/cpu/rebalance", json=request | {"timing_coupling": "stage_slack"})
    assert coupled.status_code == 422 and "inline" in coupled.text


def test_rebalance_growth_sweep(api_client, engine):
    """CPU-02..05: the same rebalance over SW growth factors (inline profile, no timing coupling)."""
    with Session(engine) as db:
        db.add(PowerModelParams(id="pmp-cpu-sweep-test", schema_version="2.2", soc_ref="soc-exynos2500", version=9877,
                                status="draft", yaml_sha256="test", params={"cpu": {"clusters": [
                                    {"name": name, "cores": 2, "opps": [{"mhz": 400, "mv": 600, "mw_per_core": 20},
                                                                        {"mhz": 1600, "mv": 750, "mw_per_core": 120}]}
                                    for name in ("MID0", "MID1")]}}))
        db.commit()
    try:
        request = {"power_params_ref": "pmp-cpu-sweep-test@9877", "cpu_profile": {
            "tasks": [{"task": "a", "cluster": "MID0", "cycles": 3_000_000}, {"task": "b", "cluster": "MID0", "cycles": 3_000_000}],
            "clusters": {"MID0": {"freq_residency": {"1600": 1}}}}}
        sweep = api_client.post("/api/v1/cpu/rebalance/sweep", json=request | {"growths": [1.0, 2.0, 4.0]})
        assert sweep.status_code == 200, sweep.text
        body = sweep.json()
        assert [p["growth"] for p in body["points"]] == [1.0, 2.0, 4.0]
        totals = [p["reference"]["total_mw"] for p in body["points"]]
        assert totals == sorted(totals) and totals[0] > 0
        assert body["limits"]["timing_at"] is None and isinstance(body["events"], list)
        # CPU-09: inline profile → builtin BW coefficient; points carry the CPU-caused BW power
        assert body["bw_power"]["source"] == "builtin" and body["workers"] >= 1
        assert all(p["bw_mw"] is None or p["bw_mw"] >= 0 for p in body["points"])
        single = api_client.post("/api/v1/cpu/rebalance", json=request).json()["result"]
        assert single["bw_power"]["source"] == "builtin" and {c["target"] for c in single["ratio_curves"]} == {"MID1"}
        assert api_client.post("/api/v1/cpu/rebalance/sweep", json=request | {"growths": [1.0]}).status_code == 422
    finally:
        with Session(engine) as db:
            db.delete(db.get(PowerModelParams, "pmp-cpu-sweep-test"))
            db.commit()


@pytest.mark.parametrize("request_owned", [False, True])
@pytest.mark.parametrize("kind", ["whatif", "sweep", "rebalance", "growth"])
def test_cpu_compute_connection_boundary_preserves_results(engine, cpu_topology, monkeypatch, request_owned, kind):
    """Only HTTP-owned clean reads release PostgreSQL before the CPU phase."""
    from scenario_db.api.schemas.cpu import (
        CpuRebalanceRequest, CpuRebalanceSweepRequest, CpuSweepRequest, CpuWhatIfRequest,
    )
    from scenario_db.api.services import cpu
    from scenario_db.api.services.compute_session import REQUEST_OWNED

    with Session(engine) as setup:
        row = setup.get(PowerModelParams, cpu_topology)
        row.params = {"cpu": {"clusters": row.params["cpu"]["clusters"] + [
            {"name": "MID", "cores": 2, "opps": [{"mhz": 800, "mv": 650, "mw_per_core": 50}]},
        ]}}
        setup.commit()

    schema, service, compute_name = {
        "whatif": (CpuWhatIfRequest, cpu.run_cpu_whatif, "cpu_whatif"),
        "sweep": (CpuSweepRequest, cpu.run_cpu_sweep, "cpu_sweep"),
        "rebalance": (CpuRebalanceRequest, cpu.run_cpu_rebalance, "_rebalance_compute"),
        "growth": (CpuRebalanceSweepRequest, cpu.run_cpu_rebalance_sweep, "_compute_points"),
    }[kind]
    body = {"power_params_ref": f"{cpu_topology}@9876", "cpu_profile": {
        "tasks": [{"task": "ui", "cluster": "BIG", "cycles": 1000000}],
        "clusters": {"BIG": {"freq_residency": {"1000": 1}}},
    }}
    if kind == "growth":
        body["growths"] = [1, 1.5, 2]
    request = schema.model_validate(body)
    monkeypatch.setattr(cpu, "_sweep_workers", lambda _: 1)

    def payload(result):
        value = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        value.pop("elapsed_ms", None)
        return value

    with Session(engine) as baseline:
        expected = payload(service(baseline, request))

    original = getattr(cpu, compute_name)
    observed = []
    with Session(engine) as db:
        if request_owned:
            db.info[REQUEST_OWNED] = True

        def checked_compute(*args, **kwargs):
            observed.append(db.in_transaction())
            assert db.in_transaction() is not request_owned
            return original(*args, **kwargs)

        monkeypatch.setattr(cpu, compute_name, checked_compute)
        assert payload(service(db, request)) == expected
    assert observed
