"""Hardware declarations, mode identity and pinned sensor experiments."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scenario_db.api.schemas.scenario_whatif import WhatIfChange
from scenario_db.api.services.whatif_conditions import apply_whatif_changes
from scenario_db.api.services.whatif_geometry import geometry_path, validate_geometry
from scenario_db.api.services.whatif_levers import chain_targets, sensor_targets
from scenario_db.api.services.whatif_sensors import catalog_binding_targets, prepare_sensor_graph, sensor_power_coverage
from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.sensor import SensorBoardLineup, SensorCatalog
from scenario_db.models.sensor import SensorModeBinding
from scenario_db.sim.external_devices import selected_sensor_mode
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.models import SimulationRunConfig
from tests.unit.api.test_whatif_levers import _graph


@pytest.fixture(scope="module")
def template():
    return _graph()


@pytest.fixture
def graph(template):
    return deepcopy(template)


def test_only_declared_crop_and_scaler_are_discovered(graph):
    assert {r["id"] for r in chain_targets(graph)} == {"byrp", "yuvsc"}
    with pytest.raises(ValueError, match="capability is not declared"):
        validate_geometry(graph, "mtnr", {"width": 1920, "height": 1080}, (4080, 2296))


@pytest.mark.parametrize("data,match", [
    ({"operation": "scale", "width": 1920, "height": 1080}, "not supported"),
    ({"width": 1921, "height": 1080}, "alignment"),
    ({"width": 1920, "height": 1080, "x": 3000}, "ROI exceeds"),
    ({"width": 1920, "height": 1080, "x": 1}, "offset requires"),
    ({"width": 1920, "height": 1080, "port": "BYRP_WDMA_BYR"}, "declared output port"),
])
def test_crop_constraints_reject_invalid_requests(graph, data, match):
    with pytest.raises(ValueError, match=match):
        validate_geometry(graph, "byrp", data, (4080, 2296))


def test_scale_ratio_and_crop_fields_are_validated(graph):
    sim = graph.ip_catalog["ip-yuvsc-is-v15-s5e9965"].capabilities["sim"]
    sim["geometry"]["operations"]["scale"]["max_downscale"] = 2
    with pytest.raises(ValueError, match="ratio"):
        validate_geometry(graph, "yuvsc", {"width": 1024, "height": 576}, (4080, 2296))
    with pytest.raises(ValueError, match="offsets"):
        validate_geometry(graph, "yuvsc", {"width": 2048, "height": 1152, "x": 0}, (4080, 2296))


def test_geometry_path_follows_port_and_stops_fixed_output_even_when_sizes_equal():
    variant = SimpleNamespace(node_configs={key: {"sim": {"width": 100, "height": 100}} for key in ("scale", "fixed", "output", "other")})
    variant.node_configs["fixed"]["sim"].update(output_width=100, output_height=100)
    graph = SimpleNamespace(variant=variant, pipeline_nodes=[{"id": key} for key in variant.node_configs],
                            pipeline_edges=[{"from": "scale", "to": "fixed", "type": "OTF", "port_pairs": [{"src": "out"}]},
                                            {"from": "scale", "to": "other", "type": "OTF", "port_pairs": [{"src": "dump"}]},
                                            {"from": "fixed", "to": "output", "type": "OTF"}])
    assert geometry_path(graph, "scale", (100, 100), "out") == (["fixed"], [])


def test_crop_preserves_declared_output_contract(graph):
    before = baseline_fingerprint(graph)
    original_output = deepcopy(graph.variant.node_configs["mcsc"]["sim"])
    candidate, _, _ = apply_whatif_changes(graph, [WhatIfChange(target="chain_size", node_id="byrp", operation="crop",
                                                               width=3744, height=2112, x=2, y=2)], SimulationRunConfig())
    assert candidate.variant.node_configs["byrp"]["sim"]["crop"] == {"width": 3744, "height": 2112, "x": 2, "y": 2}
    assert candidate.variant.size_overrides["record_out"] == graph.variant.size_overrides["record_out"]
    for key in ("output_width", "output_height", "output_size", "scale_size"):
        if key in original_output:
            assert candidate.variant.node_configs["mcsc"]["sim"][key] == original_output[key]
    assert baseline_fingerprint(graph) == before


def test_sensor_identity_is_not_deduplicated_or_starved(graph):
    row = next(ip for ip in graph.ip_catalog.values() if str(ip.category).lower() == "sensor")
    props = row.capabilities["properties"]
    example = deepcopy(next(iter(props["modes"].values())))
    example.update(sensor_fps=30, sensor_format="BAYER", sensor_size=[4080, 2296], sensor_bitwidth=10)
    props["modes"] = {f"same_size_different_readout_{n}": {**example, "v_valid_ms": n + 1} for n in range(60)}
    options = next(r for r in sensor_targets(graph, 60) if r["node_id"] == "sensor_rear")["options"]
    expected = {f"{row.id}#same_size_different_readout_{n}" for n in range(60)}
    assert expected <= {o["id"] for o in options}
    assert all(not o["fps_compatible"] for o in options if o["id"] in expected)


@pytest.mark.parametrize("reverse", [False, True])
def test_lower_target_fps_can_select_previously_incompatible_sensor(graph, reverse):
    config = SimulationRunConfig(fps=60)
    choice = next(c for c in sensor_targets(graph, 60)[0]["options"] if c.get("fps") == 30)
    changes = [WhatIfChange(target="sensor_mode", node_id="sensor_rear", option=choice["id"]),
               WhatIfChange(target="fps", value=30)]
    candidate, resolved, _ = apply_whatif_changes(graph, list(reversed(changes)) if reverse else changes, config)
    assert resolved.fps == 30
    assert candidate.variant.node_configs["sensor_rear"]["selected_mode"] == choice["mode"]


def test_mode_constraints_use_final_geometry_and_cadence(graph):
    params = graph.ip_catalog["ip-mtnr-is-v15-s5e9965"].capabilities["sim"]["modes"]["LowPower"]
    params["requires"] = {"max_size": [2048, 1152], "max_fps": 30}
    mode = WhatIfChange(target="ip_mode", node_id="mtnr", option="LowPower")
    with pytest.raises(ValueError, match="max_size"):
        apply_whatif_changes(graph, [mode], SimulationRunConfig())
    candidate, _, _ = apply_whatif_changes(graph, [mode, WhatIfChange(target="chain_size", node_id="yuvsc", width=1920, height=1080)], SimulationRunConfig())
    assert candidate.variant.node_configs["mtnr"]["selected_mode"] == "LowPower"


class Query:
    def __init__(self, rows): self.rows = rows
    def filter(self, *args): return self
    def order_by(self, *args): return self
    def all(self): return self.rows


class Database:
    def __init__(self, rows): self.rows = rows
    def get(self, cls, key): return next((r for r in self.rows.get(cls, []) if r.id == key), None)
    def query(self, cls): return Query(self.rows.get(cls, []))


def sensor_db(graph):
    ip = graph.ip_catalog[next(n["ip_ref"] for n in graph.pipeline_nodes if n["id"] == "sensor_rear")]
    name = ip.capabilities["properties"]["sensor_name"]
    mode = {"decoded": {"fps": 60, "size": [2048, 1152], "lanes": 4, "mipi_speed_mbps": 2000},
            "vc": {"dma0": {"vc0": {"map": 0, "size": [2048, 1152], "bits_per_pixel": 10,
                                       "hwformat_base": "RAW10", "data_class": "image"}}}}
    catalog = SensorCatalog(id="sensor-test", board="test-board", sensor_name=name, yaml_sha256="a" * 64,
                            document={"modes": {"mode0": mode}, "csis_wiring": {"phy": "DPHY"}})
    lineup = SensorBoardLineup(id="board-lineup-test", yaml_sha256="b" * 64,
                              document={"soc": "soc-exynos2600", "boards": {"test-board": {"configs": [
                                  {"config": "test-config", "lineup": {"rear": [name]}}]}}})
    binding = SensorModeBinding(catalog_ref=catalog.id, catalog_sha256=catalog.yaml_sha256, mode_label="mode0",
                                lineup_ref=lineup.id, lineup_sha256=lineup.yaml_sha256, board_config="test-config", slot="rear")
    return Database({IpCatalog: [ip], SensorCatalog: [catalog], SensorBoardLineup: [lineup]}), binding


def test_pinned_catalog_candidates_retain_source_and_validation_state(graph):
    db, binding = sensor_db(graph)
    targets = catalog_binding_targets(db, graph, 120)
    option = targets[0]["options"][0]
    assert option["sensor_binding"] == binding.model_dump()
    assert option["id"] == "sensor-test#mode0" and not option["fps_compatible"]
    assert "test-board/test-config/rear" in option["label"]


def test_kernel_chip_id_alias_matches_only_the_declared_platform(graph):
    from scenario_db.api.services.whatif_sensors import _same_source_soc
    assert _same_source_soc("s5e9965", "soc-exynos2600")
    assert not _same_source_soc("s5e9975", "soc-exynos2600")
    assert not _same_source_soc("s5e9965", "soc-exynos2700")
    assert not _same_source_soc("s5e9965", None)
    db, binding = sensor_db(graph)
    db.rows[SensorBoardLineup][0].document["soc"] = "s5e9965"
    assert catalog_binding_targets(db, graph)[0]["options"]
    candidate = prepare_sensor_graph(db, graph, SimulationRunConfig(sensor_modes={"sensor_rear": binding}))
    assert candidate.variant.node_configs["sensor_rear"]["resolved_sensor_mode"]["catalog_binding"]["catalog_ref"] == binding.catalog_ref


def test_pinned_binding_reshapes_once_and_preserves_original(graph):
    db, binding = sensor_db(graph)
    original = baseline_fingerprint(graph)
    config = SimulationRunConfig(sensor_modes={"sensor_rear": binding})
    candidate = prepare_sensor_graph(db, graph, config)
    assert candidate.variant.node_configs["byrp"]["sim"]["width"] == 2048
    assert candidate.variant.size_overrides["record_out"] == graph.variant.size_overrides["record_out"]
    candidate.variant.node_configs["mtnr"]["sim"]["width"] = 1000
    checked = prepare_sensor_graph(db, candidate, config)
    assert checked.variant.node_configs["mtnr"]["sim"]["width"] == 1000
    assert baseline_fingerprint(graph) == original
    assert sensor_power_coverage(checked)["power_mw"] is None


@pytest.mark.parametrize("violation,match", [("hash", "hash changed"), ("soc", "another SoC"), ("installed", "not installed"), ("fps", "FPS exceeds")])
def test_pinned_binding_rejects_invalid_source(graph, violation, match):
    db, binding = sensor_db(graph)
    config = SimulationRunConfig(sensor_modes={"sensor_rear": binding})
    if violation == "hash": binding.catalog_sha256 = "c" * 64
    if violation == "soc": db.rows[SensorBoardLineup][0].document["soc"] = "soc-exynos2700"
    if violation == "installed": db.rows[SensorBoardLineup][0].document["boards"]["test-board"]["configs"][0]["lineup"] = {}
    if violation == "fps": config.fps = 120
    with pytest.raises(ValueError, match=match):
        prepare_sensor_graph(db, graph, config)


def test_binding_applies_before_crop_and_final_validation_preserves_crop(graph):
    db, binding = sensor_db(graph)
    def callback(candidate, config):
        return prepare_sensor_graph(db, candidate, config)
    changes = [WhatIfChange(target="chain_size", node_id="yuvsc", operation="scale", width=1920, height=1080),
               WhatIfChange(target="sensor_binding", node_id="sensor_rear", option="sensor-test#mode0", sensor_binding=binding),
               WhatIfChange(target="fps", value=30)]
    candidate, config, _ = apply_whatif_changes(graph, changes, SimulationRunConfig(), prepare_sensor=callback)
    assert candidate.variant.node_configs["yuvsc"]["sim"]["width"] == 2048
    assert candidate.variant.node_configs["mtnr"]["sim"]["width"] == 1920
    assert config.fps == 30
    with pytest.raises(ValueError, match="FPS exceeds"):
        apply_whatif_changes(candidate, [WhatIfChange(target="fps", value=120)], config, prepare_sensor=callback)


def test_sensor_precision_changes_raw_buffers_without_changing_yuv(graph):
    db, binding = sensor_db(graph)
    db.rows[SensorCatalog][0].document["modes"]["mode0"]["vc"]["dma0"]["vc0"].update(bits_per_pixel=12, hwformat_base="RAW12")
    candidate = prepare_sensor_graph(db, graph, SimulationRunConfig(sensor_modes={"sensor_rear": binding}))
    assert candidate.variant.buffer_overrides["BYRP_BAYER_DUMP"]["bitdepth"] == 12
    assert "bitdepth" not in candidate.variant.buffer_overrides.get("MCSC_VIDEO", {})
    assert "bitdepth" not in candidate.variant.buffer_overrides.get("FRONT_BYRP_BAYER_DUMP", {})


@pytest.mark.parametrize("sample,expected", [
    ({"status": "measured", "power_mw": 120.0, "fps": 30.0, "source": {"measurement_ref": "measurement-rail"}}, 120.0),
    ({"status": "measured", "power_mw": 0.0, "fps": 30.0, "source": "measurement-zero"}, 0.0),
    ({"status": "measured", "power_mw": 120.0, "fps": 60.0, "source": "measurement-rail"}, None),
    ({"status": "assumed", "power_mw": 120.0, "fps": 30.0, "source": "estimate"}, None),
    ({"status": "measured", "power_mw": float("nan"), "fps": 30.0, "source": "measurement-rail"}, None),
    ({"status": "measured", "power_mw": 120.0, "fps": 30.0, "source": {}}, None),
])
def test_sensor_power_requires_valid_matching_measured_operating_point(graph, sample, expected):
    db, binding = sensor_db(graph)
    db.rows[SensorCatalog][0].document["modes"]["mode0"]["power_model"] = sample
    candidate = prepare_sensor_graph(db, graph, SimulationRunConfig(fps=30, sensor_modes={"sensor_rear": binding}))
    coverage = sensor_power_coverage(candidate, 30)
    assert coverage["power_mw"] == expected
    assert coverage["complete"] is (expected is not None)
