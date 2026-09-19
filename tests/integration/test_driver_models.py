from pathlib import Path
import pytest
from sqlalchemy.orm import Session
from scenario_db.etl.loader import load_yaml_dir
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.runner import run_simulation, params_hash
from scenario_db.sim.driver_models import evaluate_graph

FIXTURES = Path(__file__).parents[2] / "db_fixtures_Exynos2600_S26Plus"


@pytest.fixture(scope="module")
def imported(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(connection, join_transaction_mode="create_savepoint") as db:
                assert load_yaml_dir(FIXTURES, db, validate=True, strict=True).ok
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def driver_client(api_client, imported):
    from scenario_db.api.deps import get_db

    original = api_client.app.dependency_overrides[get_db]

    def get_driver_db():
        with Session(imported, join_transaction_mode="create_savepoint") as db:
            yield db

    api_client.app.dependency_overrides[get_db] = get_driver_db
    try:
        yield api_client
    finally:
        api_client.app.dependency_overrides[get_db] = original


def test_report_api_and_exploration(imported, driver_client):
    query = {"scenario_id": "uc-game-play", "variant_id": "game-fhd-60fps-m2m-upscale"}
    response = driver_client.get("/api/v1/driver-models", params=query)
    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    scaler = next(r for r in rows if r["model"] == "mscl")
    assert scaler["status"] == "calculated", scaler
    inputs = {**scaler["inputs"], "fps": 120}
    out = driver_client.post(
        "/api/v1/driver-models/explore", json={**query, "overrides": {"m2m_scaler": inputs}}
    )
    assert out.status_code == 200, out.text
    other = next(r for r in out.json()["rows"] if r["model"] == "mscl")
    assert other["read_bytes_s"] == 2 * scaler["read_bytes_s"]
    assert other["required_clock_khz"] == 2 * scaler["required_clock_khz"]
    assert other["input_basis"] == "exploration"
    assert (
        driver_client.post(
            "/api/v1/driver-models/explore", json={**query, "overrides": {"missing": inputs}}
        ).status_code
        == 422
    )
    assert (
        driver_client.get(
            "/api/v1/driver-models", params={**query, "variant_id": "missing"}
        ).status_code
        == 404
    )


def test_report_persists_in_simulation_trace_and_changes_hash(imported):
    with Session(imported, join_transaction_mode="create_savepoint") as db:
        graph = load_canonical_graph(db, "uc-audio-mp3-playback", "audio-mp3-screen-on")
        inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))
        result = run_simulation(inputs)
        assert result.calculation_trace["driver_models"]["rows"]
        changed = build_simulation_inputs(
            graph,
            SimulationRunConfig(
                include_timeline=False,
                driver_model_overrides={"storage": {"model": "ufs", "bitrate_mbps": 1}},
            ),
        )
        assert params_hash(changed) != params_hash(inputs)
        assert changed.driver_model_report["rows"] != inputs.driver_model_report["rows"]
        assert result.total_power_mw == run_simulation(changed).total_power_mw


def test_driver_page(imported, driver_client, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import dashboard.components.simulation_api_client as client

    def request(method, base, path, **kwargs):
        response = driver_client.request(
            method, "/api/v1" + path, params=kwargs.get("params"), json=kwargs.get("json")
        )
        response.raise_for_status()
        return response.json()

    monkeypatch.setattr(client, "_request_json", request)
    app = AppTest.from_file(
        str(FIXTURES.parent / "dashboard/pages/9_Driver_Models.py"), default_timeout=30
    ).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception


def test_all_noncamera_driver_coverage(imported):
    from collections import Counter
    from scenario_db.db.models.definition import ScenarioVariant

    counts = Counter()
    with Session(imported, join_transaction_mode="create_savepoint") as db:
        variants = [
            v
            for v in db.query(ScenarioVariant)
            if "camera" not in v.scenario_id
            and v.scenario_id != "uc-video-call"
            and v.scenario_id.startswith(
                ("uc-audio", "uc-game", "uc-gallery", "uc-youtube", "uc-voice", "uc-video-playback")
            )
        ]
        assert len(variants) == 74
        for v in variants:
            report = evaluate_graph(load_canonical_graph(db, v.scenario_id, v.id))
            for row in report["rows"]:
                assert row["status"] not in {"unsupported", "invalid_input"}, (v.id, row)
                counts[(row["model"], row["status"])] += 1
        assert counts[("dpu", "calculated")] == 62
        assert counts[("mscl", "calculated")] == 6
        assert counts[("ufs", "missing_input")] == 12
        assert counts[("abox", "partial")] == 5


def test_calculation_trace_db_roundtrip(imported):
    from scenario_db.sim.runner import build_simulation_evidence
    from scenario_db.models.evidence.common import ExecutionContext
    from scenario_db.db.models.capability import SwProfile
    from scenario_db.db.models.evidence import Evidence
    from scenario_db.etl.mappers.evidence import upsert_simulation

    with Session(imported, join_transaction_mode="create_savepoint") as db:
        graph = load_canonical_graph(db, "uc-game-play", "game-fhd-60fps-m2m-upscale")
        inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))
        result = run_simulation(inputs)
        evidence = build_simulation_evidence(
            result,
            evidence_id="sim-driver-model-roundtrip",
            project_ref=graph.scenario.project_ref,
            execution_context=ExecutionContext(
                silicon_rev="EVT0",
                sw_baseline_ref=db.query(SwProfile).first().id,
                thermal="nominal",
            ),
        )
        upsert_simulation(
            evidence.model_dump(mode="json", exclude_none=True), "test-driver-trace", db
        )
        db.commit()
        stored = db.get(Evidence, "sim-driver-model-roundtrip")
        assert (
            stored.calculation_trace["driver_models"] == result.calculation_trace["driver_models"]
        )
