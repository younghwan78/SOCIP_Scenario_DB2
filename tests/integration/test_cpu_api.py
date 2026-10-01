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
