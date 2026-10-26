"""Real Exynos2600 kernel catalog selections are executable What-if candidates."""
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from scenario_db.api.services.whatif_sensors import prepare_sensor_graph
from scenario_db.db.models.definition import Scenario
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.etl.loader import load_yaml_dir
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.models import SimulationRunConfig


@pytest.fixture(scope="module")
def camera_catalogs(engine):
    fixtures = Path(__file__).parents[2] / "db_Exynos2600_SM-S947B"
    with Session(engine) as db:
        result = load_yaml_dir(fixtures, db, validate=True, strict=True)
        assert result.ok and result.counts["sensor.catalog"] == 20
    return engine


def test_real_sensor_swap_targets_and_preview_preserve_pinned_source(camera_catalogs, api_client):
    scope = {"project_ref": "proj-sm-s947b", "scenario_id": "uc-cam-recording-e2600", "variant_id": "cam-rec-r1-uhd30-vdis"}
    response = api_client.get("/api/v1/scenario-whatif/targets", params=scope)
    assert response.status_code == 200, response.text
    targets = response.json()
    sensor = next(row for row in targets["sensor_bindings"] if row["id"] == "sensor_rear")
    options = {row["id"]: row for row in sensor["options"]}
    assert sensor["option_count"] == len(options) > 40
    assert {"S5KGNG", "S5KHP2", "IMX874"} <= {row["sensor"] for row in options.values()}
    # Same dimensions do not erase DT mode identity or alternate readout modes.
    assert {"sensor-hp2-m2s#mode0", "sensor-hp2-m2s#mode0_nfi"} <= options.keys()
    selected = options["sensor-hp2-m2s#mode2"]
    binding = selected["sensor_binding"]
    assert selected["supported"] and selected["fps_compatible"]
    assert binding["lineup_ref"] == "board-lineup-s5e9965"
    assert binding["board_config"] == "s5e9965.m2s_camera_02"
    assert binding["slot"] == "rear_wide"
    payload = {**scope, "expected_baseline_hash": targets["baseline_hash"], "expected_analysis_hash": targets["analysis_hash"],
               "changes": [{"target": "sensor_binding", "node_id": "sensor_rear", "option": selected["id"], "sensor_binding": binding}]}
    response = api_client.post("/api/v1/scenario-whatif/preview", json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["persisted"] is False
    assert preview["candidate"]["metrics"]["sensor_power_mw"] is None
    assert preview["delta"]["metrics"]["modeled_power_mw"] != 0
    assert preview["normalized_condition"]["config"]["sensor_modes"]["sensor_rear"] == binding
    assert preview["iq_required"] == ["sensor_binding"]
    answer = api_client.post("/api/v1/scenario-whatif/ask", json={**payload, "ask": "what_if"})
    assert answer.status_code == 200, answer.text
    assert "sensor-hp2-m2s / mode2" in answer.json()["answer"]["headline"]
    assert "None" not in answer.json()["answer"]["headline"]
    # Confirm the actual modeled input changed sensors and has the pinned CIS
    # timing, while the persisted baseline topology and its fingerprint did not.
    with Session(camera_catalogs) as db:
        graph = load_canonical_graph(db, scope["scenario_id"], scope["variant_id"], include_decision_context=False)
        before = baseline_fingerprint(graph)
        old_ref = next(node["ip_ref"] for node in graph.pipeline_nodes if node["id"] == "sensor_rear")
        config = SimulationRunConfig(sensor_modes={"sensor_rear": binding}, fps=30)
        candidate = prepare_sensor_graph(db, graph, config)
        device = next(item for item in build_simulation_inputs(candidate, config).external_devices if item["node_id"] == "sensor_rear")
        assert device["ip_ref"] != old_ref and device["name"] == "S5KHP2"
        assert device["mode"] == "mode2" and device["catalog_size"] == "4000x3000"
        assert device["v_valid_ms"] > 0 and device["timing_source"]["dt_mode_label"] == "mode2"
        assert device["catalog_binding"]["catalog_sha256"] == binding["catalog_sha256"]
        assert baseline_fingerprint(graph) == before == targets["baseline_hash"]
        persisted = db.get(Scenario, scope["scenario_id"])
        assert next(node["ip_ref"] for node in persisted.pipeline["nodes"] if node["id"] == "sensor_rear") == old_ref
