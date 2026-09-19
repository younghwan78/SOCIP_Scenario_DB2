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


def test_sensor_page(imported, api_client, monkeypatch, binding_request):
    from streamlit.testing.v1 import AppTest
    import dashboard.components.simulation_api_client as client
    def request(method, base, path, **kwargs):
        response = api_client.request(method, "/api/v1" + path, params=kwargs.get("params"), json=kwargs.get("json"))
        response.raise_for_status()
        return response.json()
    monkeypatch.setattr(client, "_request_json", request)
    app = AppTest.from_file(str(FIXTURES.parent / "dashboard/pages/8_Sensor_Catalog.py"), default_timeout=30).run()
    assert not app.exception
    app.selectbox[0].select("m2s").run()
    app.selectbox[1].select("sensor-gng-m2s").run()
    assert not app.exception
    assert len(app.metric) == 3
    assert "mode0 · 4080 × 3060 · 120 fps · RAW10 · Normal" in app.selectbox[2].options
    app.selectbox[2].select("mode0_aeb_nfi").run()
    assert not app.exception
    assert app.selectbox[2].value == "mode0_aeb_nfi"
    assert any("cadence is unresolved" in warning.value for warning in app.warning)
    assert any("AEB · NFI" in option for option in app.selectbox[2].options)
    assert any("max 60 fps" in option for option in app.selectbox[2].options)
    app.selectbox[2].select(binding_request["mode_label"]).run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error


def test_sensor_transport_api(imported, api_client):
    base = "/api/v1/sensors/catalogs/sensor-gng-m2s/modes/"
    r = api_client.get(base + "mode0/transport")
    assert r.status_code == 200
    report = r.json()
    assert report["board"] == "m2s"
    assert report["catalog_sha256"]
    assert report["csis_payload_bytes_s"] == 17554200 * 120
    assert report["dram_write_bytes_s"] is None
    r = api_client.get(base + "mode0_aeb_nfi/transport")
    assert r.json()["status"] == "cadence_unresolved"
    assert r.json()["csis_payload_bytes_s"] is None
    assert api_client.get(base + "mode999/transport").status_code == 404
    assert api_client.get(base.replace("sensor-gng-m2s", "sensor-missing") + "mode0/transport").status_code == 404


@pytest.fixture
def binding_request(imported):
    from scenario_db.db.repositories.scenario_graph import load_canonical_graph
    from scenario_db.sim.external_devices import selected_sensor_mode
    with Session(imported) as db:
        graph = load_canonical_graph(db, "uc-camera-recording", "cam-rec-r1-fhd30-vdis")
        node = next(n for n in graph.pipeline_nodes if n["id"] == "sensor_rear")
        base = selected_sensor_mode(graph, node)
        catalog = db.get(SensorCatalog, "sensor-gng-m2s")
        label = next(k for k, m in catalog.document["modes"].items()
                     if m["decoded"]["size"] == base["sensor_size"] and m["decoded"]["ex_mode"] == "EX_NONE")
    return {"scenario_id": graph.scenario_id, "variant_id": graph.variant_id,
            "node_id": "sensor_rear", "catalog_ref": "sensor-gng-m2s", "mode_label": label,
            "lineup_ref": "board-lineup-s5e9965", "board_config": "s5e9965.m2s_camera", "slot": "rear_wide"}


def test_sensor_binding_projection_and_rejection(imported, api_client, binding_request):
    from copy import deepcopy
    from scenario_db.db.repositories.scenario_graph import load_canonical_graph
    from scenario_db.sim.sensor_projection import resolve_sensor_modes
    from scenario_db.sim.adapter import build_simulation_inputs
    from scenario_db.sim.models import SimulationRunConfig
    from scenario_db.sim.runner import params_hash, run_simulation
    r = api_client.post("/api/v1/sensors/projection/prepare", json=binding_request)
    assert r.status_code == 200, r.text
    config = SimulationRunConfig(**r.json()["config"], include_timeline=False)
    with Session(imported) as db:
        graph = load_canonical_graph(db, binding_request["scenario_id"], binding_request["variant_id"])
        original = deepcopy(graph.variant.node_configs)
        baseline = build_simulation_inputs(graph)
        with pytest.raises(ValueError, match="resolved against DB"):
            build_simulation_inputs(graph, config)
        resolved = resolve_sensor_modes(db, graph, config)
        inputs = build_simulation_inputs(resolved, config)
        device = next(d for d in inputs.external_devices if d["node_id"] == "sensor_rear")
        assert device["mode"] == binding_request["mode_label"]
        assert device["catalog_binding"]["catalog_sha256"]
        assert device["transport"]["assumed_fps"] == 30
        assert device["v_valid_ms"] > 0
        assert device["timing_source"]["dt_mode_label"] == binding_request["mode_label"]
        assert graph.variant.node_configs == original
        assert params_hash(inputs) != params_hash(baseline)
        assert run_simulation(inputs).external_devices == inputs.external_devices
        for field, value, message in [
            ("catalog_sha256", "stale", "hash changed"),
            ("board_config", "missing", "not installed"),
            ("mode_label", "mode999", "unknown full"),
            ("mode_label", "mode0_aeb_nfi", "cadence"),
        ]:
            broken = config.model_copy(deep=True)
            setattr(broken.sensor_modes["sensor_rear"], field, value)
            with pytest.raises(ValueError, match=message):
                resolve_sensor_modes(db, graph, broken)
        fast = config.model_copy(update={"fps": 10000})
        with pytest.raises(ValueError, match="FPS exceeds"):
            resolve_sensor_modes(db, graph, fast)
        wrong = config.model_copy(deep=True)
        wrong.sensor_modes["cpu"] = wrong.sensor_modes.pop("sensor_rear")
        with pytest.raises(ValueError, match="active sensor"):
            resolve_sensor_modes(db, graph, wrong)
    bad = {**binding_request, "slot": "front"}
    assert api_client.post("/api/v1/sensors/projection/prepare", json=bad).status_code == 422


def test_sensor_binding_persists_through_simulation_api(imported, api_client, binding_request):
    prepared = api_client.post("/api/v1/sensors/projection/prepare", json=binding_request).json()
    from scenario_db.db.models.capability import SwProfile
    with Session(imported) as db:
        sw_id = db.query(SwProfile).first().id
    payload = {"scenario_id": binding_request["scenario_id"], "variant_id": binding_request["variant_id"],
               "execution_context": {"silicon_rev": "EVT1", "sw_baseline_ref": sw_id, "thermal": "nominal"},
               "config": {**prepared["config"], "include_timeline": False}, "persist": True}
    r = api_client.post("/api/v1/simulation/run", json=payload)
    assert r.status_code == 200, r.text
    device = next(d for d in r.json()["result"]["external_devices"] if d["node_id"] == "sensor_rear")
    assert device["catalog_binding"]["mode_label"] == binding_request["mode_label"]

    assert r.json()["persisted"]
    from scenario_db.db.models.evidence import Evidence
    with Session(imported) as db:
        stored = db.get(Evidence, r.json()["evidence_id"])
        assert stored.execution_context["method"] == "projection"
        assert next(d for d in stored.external_devices if d["node_id"] == "sensor_rear")["catalog_binding"] == device["catalog_binding"]
    payload["config"]["sensor_modes"]["sensor_rear"]["catalog_sha256"] = "stale"
    assert api_client.post("/api/v1/simulation/run", json=payload).status_code == 422


def test_bound_catalog_timing_and_simulation_duration(imported, api_client, binding_request):
    r = api_client.get("/api/v1/sensors/catalogs/sensor-gng-m2s/modes/mode0/timing")
    assert r.status_code == 200
    assert r.json()["valid_time_ms"] == pytest.approx(7.6915760869565215)
    assert r.json()["binding_status"] == "verified_mode_index"
    assert r.json()["source"]["mode_label"] == "cis_4sum_ln1_raw10_4080x3060_120fps_3993msps"
    assert api_client.get("/api/v1/sensors/catalogs/sensor-gng-m2s/modes/mode0_nfi/timing").json()["binding_status"] == "unmapped"
    from scenario_db.db.repositories.scenario_graph import load_canonical_graph
    from scenario_db.sim.sensor_projection import resolve_sensor_modes
    from scenario_db.sim.adapter import build_simulation_inputs
    from scenario_db.sim.models import SimulationRunConfig
    from scenario_db.sim.runner import run_simulation
    prepared = api_client.post("/api/v1/sensors/projection/prepare", json=binding_request).json()
    config = SimulationRunConfig(**prepared["config"])
    with Session(imported) as db:
        graph = load_canonical_graph(db, binding_request["scenario_id"], binding_request["variant_id"])
        inputs = build_simulation_inputs(resolve_sensor_modes(db, graph, config), config)
        device = next(d for d in inputs.external_devices if d["node_id"] == "sensor_rear")
        assert device["fps"] == 30  # Retain scenario cadence, not the setfile's maximum FPS.
        result = run_simulation(inputs)
        events = [e for e in result.timeline_events if e.node_id == "sensor_rear"]
        assert events
        assert events[0].v_valid_ms == pytest.approx(device["v_valid_ms"])
        source = next(t for t in inputs.timeline_tasks if t["id"] == "sensor_rear")
        assert source["source_valid_ms"] == pytest.approx(device["v_valid_ms"])
        # OTF group reservations can outlast readout when downstream HW is slower.
        assert events[0].end_ms - events[0].start_ms >= device["v_valid_ms"]


def test_timing_profile_drift_strict_rollback(imported, tmp_path):
    from copy import deepcopy
    import yaml
    from scenario_db.etl.loader import LoaderValidationError
    with Session(imported) as db:
        row = db.get(SensorTimingProfile, "sensortiming-s5kgng-seta-19p2")
        original = row.yaml_sha256
        doc = deepcopy(row.document)
        label = "cis_4sum_ln1_raw10_4080x3060_120fps_3993msps"
        doc["modes"][label]["line_length_pck"] += 8
        (tmp_path / "profile.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(LoaderValidationError, match="inputs changed"):
            load_yaml_dir(tmp_path, db, validate=True, strict=True)
        assert db.get(SensorTimingProfile, row.id).yaml_sha256 == original
