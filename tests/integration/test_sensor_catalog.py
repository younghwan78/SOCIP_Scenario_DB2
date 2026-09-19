import json
from pathlib import Path
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from scenario_db.etl.loader import load_yaml_dir
from scenario_db.db.models.sensor import SensorCatalog, SensorTimingProfile, ProjectSensorSelection
from scenario_db.db.models.definition import ScenarioVariant

FIXTURES = Path(__file__).parents[2] / "db_fixtures_Exynos2600_S26Plus"

@pytest.fixture(scope="module")
def imported(engine):
    with Session(engine) as db:
        result = load_yaml_dir(FIXTURES, db, validate=True, strict=True)
        assert result.ok
        assert result.counts["sensor.catalog"] == 20
        assert result.counts["sensor.timing_profile"] == 1
        assert db.scalar(select(func.count()).select_from(ScenarioVariant).where(ScenarioVariant.scenario_id == "uc-camera-recording")) == 75
        catalogs = db.query(SensorCatalog).all()
        assert sum(len(x.document["modes"]) for x in catalogs) == 449
        before = {c.id: (c.yaml_sha256, c.document) for c in catalogs}
        assert load_yaml_dir(FIXTURES, db, validate=True, strict=True).ok
        assert before == {c.id: (c.yaml_sha256, c.document) for c in db.query(SensorCatalog)}
    return engine


def test_catalog_and_readout_api(imported, api_client):
    r = api_client.get("/api/v1/sensors/catalogs", params={"board": "m2s"})
    assert r.status_code == 200 and r.json()["total"] == 6
    r = api_client.get("/api/v1/sensors/catalogs/sensor-gng-m2s/modes/mode0_aeb_nfi/timing")
    assert r.status_code == 200 and r.json()["status"] == "missing_timing"
    profile = api_client.get("/api/v1/sensors/timing-profiles", params={"sensor_name": "S5KGNG"}).json()["items"][0]
    assert len(profile["modes"]) == 47
    r = api_client.get(f"/api/v1/sensors/timing-profiles/{profile['id']}/modes/{'cis_4sum_ln1_raw10_4080x3060_120fps_3993msps'}")
    assert r.status_code == 200
    t = r.json()
    assert t["valid_time_ms"] == pytest.approx(7.6915760869565215)
    assert api_client.post("/api/v1/sensors/timing/calculate", json=t["inputs"]).json()["valid_time_ms"] == t["valid_time_ms"]
    assert api_client.get("/api/v1/sensors/catalogs/sensor-gng-m2s/modes/mode999/timing").status_code == 404


def test_project_selection_reuses_catalog_and_rejects_orphan(imported, api_client):
    payload = {"project_ref": "proj-sm-s947b", "slot": "rear_wide", "catalog_ref": "sensor-gng-m2s", "lineup_ref": "board-lineup-s5e9965", "board_config": "s5e9965.m2s_camera"}
    r = api_client.post("/api/v1/sensors/selections", json=payload)
    assert r.status_code == 200, r.text
    assert api_client.post("/api/v1/sensors/selections", json=payload).status_code == 200
    payload.update(catalog_ref="sensor-imx955-m1s", slot="rear_wide", board_config="s5e9965.m1s_camera")
    assert api_client.post("/api/v1/sensors/selections", json=payload).status_code == 422
    with Session(imported) as db:
        assert db.scalar(select(func.count()).select_from(ProjectSensorSelection)) == 1


def test_noncamera_inputs_and_camera_readout_projection(imported):
    from scenario_db.db.repositories.scenario_graph import load_canonical_graph
    from scenario_db.sim.adapter import build_simulation_inputs
    from scenario_db.sim.models import SimulationRunConfig
    from scenario_db.models.sensor import SensorTiming
    ids = ["uc-audio-mp3-playback", "uc-audio-streaming", "uc-gallery-display", "uc-game-play",
        "uc-game-streaming", "uc-video-playback-local", "uc-voice-call", "uc-youtube-playback"]
    with Session(imported) as db:
        variants = db.query(ScenarioVariant).filter(ScenarioVariant.scenario_id.in_(ids)).all()
        assert len(variants) == 74
        for v in variants:
            graph = load_canonical_graph(db, v.scenario_id, v.id)
            inputs = build_simulation_inputs(graph)
            inactive = {n for n,c in (v.node_configs or {}).items() if (c.get("sim") or {}).get("active") is False}
            assert not inactive.intersection(w.node_id for w in inputs.workloads)
            assert not inactive.intersection(t["id"] for t in inputs.timeline_tasks)
            sw = {n for n,c in (v.node_configs or {}).items() if c.get("sw_timing")}
            assert not sw.intersection(w.node_id for w in inputs.workloads)
        profile = db.get(SensorTimingProfile, "sensortiming-s5kgng-seta-19p2")
        mode = "cis_4sum_ln1_raw10_4080x3060_120fps_3993msps"
        t = SensorTiming.model_validate(profile.document["modes"][mode])
        # Use a synthetic explicit sensor selection on a real DB-backed graph; do not mutate DB.
        graph = load_canonical_graph(db, "uc-camera-recording", "cam-rec-r1-fhd30-vdis")
        graph.variant.node_configs = {**(graph.variant.node_configs or {}), "sensor_rear": {"selected_mode": mode}}
        config = SimulationRunConfig(sensor_readout={"sensor_rear": t})
        before = dict(graph.variant.node_configs["sensor_rear"])
        inputs = build_simulation_inputs(graph, config)
        device = next(x for x in inputs.external_devices if x["node_id"] == "sensor_rear")
        assert device["csis_frame_window_ms"] == pytest.approx(7.6915760869565215)
        assert graph.variant.node_configs["sensor_rear"] == before
        from scenario_db.sim.runner import run_simulation
        result = run_simulation(inputs, dvfs_tables={})
        events = [e for e in result.timeline_events if e.node_id == "sensor_rear"]
        assert events
        assert events[0].end_ms - events[0].start_ms == pytest.approx(device["csis_frame_window_ms"])



def test_reuse_across_projects_and_strict_rollback(imported, api_client, tmp_path):
    from copy import deepcopy
    import yaml
    from scenario_db.db.models.definition import Project
    from scenario_db.etl.loader import LoaderValidationError
    with Session(imported) as db:
        source = db.get(Project, "proj-sm-s947b")
        if db.get(Project, "proj-next-sensor-reuse") is None:
            db.add(Project(id="proj-next-sensor-reuse", schema_version=source.schema_version,
                metadata_=deepcopy(source.metadata_), globals_=deepcopy(source.globals_), yaml_sha256="test-next-project"))
            db.commit()
        before = db.get(SensorCatalog, "sensor-gng-m2s").yaml_sha256
        doc = deepcopy(db.get(SensorCatalog, "sensor-gng-m2s").document)
        doc["mode_count"] += 1
        (tmp_path / "invalid.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(LoaderValidationError):
            load_yaml_dir(tmp_path, db, validate=True, strict=True)
        assert db.get(SensorCatalog, "sensor-gng-m2s").yaml_sha256 == before
    r = api_client.post("/api/v1/sensors/selections", json={"project_ref": "proj-next-sensor-reuse", "slot": "rear_wide",
        "catalog_ref": "sensor-gng-m2s", "lineup_ref": "board-lineup-s5e9965", "board_config": "s5e9965.m2s_camera"})
    assert r.status_code == 200, r.text
    assert api_client.get("/api/v1/sensors/selections", params={"project_ref": "proj-next-sensor-reuse"}).json()["items"][0]["catalog_ref"] == "sensor-gng-m2s"


def test_sensor_page(imported, api_client, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import dashboard.components.simulation_api_client as client
    def request(method, base, path, **kwargs):
        response = api_client.request(method, "/api/v1" + path, params=kwargs.get("params"))
        response.raise_for_status()
        return response.json()
    monkeypatch.setattr(client, "_request_json", request)
    app = AppTest.from_file(str(FIXTURES.parent / "dashboard/pages/8_Sensor_Catalog.py"), default_timeout=30).run()
    assert not app.exception
    app.selectbox[0].select("m2s").run()
    app.selectbox[1].select("sensor-gng-m2s").run()
    assert not app.exception
    assert len(app.metric) == 3
