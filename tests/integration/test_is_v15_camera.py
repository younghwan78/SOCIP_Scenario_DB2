from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db

from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.evidence import upsert_simulation_evidence
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.etl.loader import load_yaml_dir
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.runner import build_simulation_evidence, run_simulation


FIXTURE = Path(__file__).resolve().parents[2] / "db_fixtures_Exynos2600_S26Plus"


@pytest.fixture
def isolated_connection(engine, api_client):
    # Keep full-board fixtures out of the shared integration database after this test.
    with engine.connect() as connection:
        transaction = connection.begin()
        previous = api_client.app.dependency_overrides[get_db]

        def get_test_db():
            with Session(connection, join_transaction_mode="create_savepoint") as db:
                yield db

        api_client.app.dependency_overrides[get_db] = get_test_db
        try:
            yield connection
        finally:
            api_client.app.dependency_overrides[get_db] = previous
            transaction.rollback()


def test_is_v15_strict_load_timing_persistence_and_view(isolated_connection, api_client):
    scenario_id, variant_id = "uc-camera-recording", "cam-rec-r1-fhd30-vdis"
    with Session(isolated_connection, join_transaction_mode="create_savepoint") as db:
        loaded = load_yaml_dir(FIXTURE, db, strict=True, validate=True)
        assert loaded.ok, loaded.to_dict()
        db.commit()
        graph = load_canonical_graph(db, scenario_id, variant_id)
        result = run_simulation(build_simulation_inputs(graph), dvfs_tables={})
        evidence = build_simulation_evidence(result, evidence_id="sim-is-v15-persistence-test",
            project_ref="proj-sm-s947b", execution_context=ExecutionContext(
                silicon_rev="EVT1", sw_baseline_ref="sw-vendor-v1.2.3", thermal="room", method="calculation",
            ))
        upsert_simulation_evidence(db, evidence)
        db.commit()
        db.expire_all()
        row = db.query(Evidence).filter_by(id=evidence.id).one()
        assert row.project_ref == "proj-sm-s947b"
        assert row.overall_feasibility == "exploration_only"
        crta = next(t for t in row.sw_task_timing if t["task"] == "post_crta")
        assert crta["min_ms"] == 0.1
        assert crta["start_jitter_mean_ms"] == 1.0
        assert crta["value_source"] == "assumed"
    endpoint = f"/api/v1/scenarios/{scenario_id}/variants/{variant_id}/view"
    for level in (0, 1, 2):
        response = api_client.get(endpoint, params={"level": level, "sim_evidence_id": evidence.id, **({"expand": "all"} if level == 2 else {})})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["nodes"] and body["edges"]
    response = api_client.get(f"/api/v1/simulation/results/{evidence.id}")
    assert response.status_code == 200, response.text
    assert len(response.json()["sw_task_timing"]) == 5
