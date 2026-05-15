from __future__ import annotations

from types import SimpleNamespace

from scenario_db.db.repositories import scenario_graph
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.external_devices import selected_sensor_mode


def test_sensor_mode_from_node_config_fills_missing_sensor_full_override():
    graph = _graph(sensor_full_override=None)

    assert hasattr(scenario_graph, "_apply_sensor_mode_size_overrides")
    scenario_graph._apply_sensor_mode_size_overrides(graph)

    assert graph.variant.size_overrides["sensor_full"] == "4080x2296"


def test_sensor_mode_resolution_preserves_explicit_sensor_full_override():
    graph = _graph(sensor_full_override="4000x2252")

    assert hasattr(scenario_graph, "_apply_sensor_mode_size_overrides")
    scenario_graph._apply_sensor_mode_size_overrides(graph)

    assert graph.variant.size_overrides["sensor_full"] == "4000x2252"


def test_selected_sensor_mode_prefers_node_config_mode_over_design_fallback():
    graph = _graph(sensor_full_override=None)
    graph.variant.design_conditions["sensor_mode"] = "full_4_3"

    mode = selected_sensor_mode(graph, {"id": "sensor0", "ip_ref": "ip-sensor-rear"})

    assert mode["mode_id"] == "wide_16_9_30"
    assert mode["sensor_size"] == [4080, 2296]


def _graph(sensor_full_override: str | None) -> CanonicalScenarioGraph:
    size_overrides = {}
    if sensor_full_override:
        size_overrides["sensor_full"] = sensor_full_override
    return CanonicalScenarioGraph(
        scenario=SimpleNamespace(
            id="uc-camera-recording",
            project_ref="proj-s5e9995",
            pipeline={
                "nodes": [
                    {"id": "sensor0", "ip_ref": "ip-sensor-rear", "role": "sensor"},
                    {"id": "csis0", "ip_ref": "ip-csis"},
                ],
                "edges": [{"from": "sensor0", "to": "csis0", "type": "OTF"}],
            },
            size_profile={"anchors": {"sensor_full": "0x0"}},
        ),
        variant=SimpleNamespace(
            id="FHD30",
            design_conditions={"resolution": "FHD", "fps": 30},
            size_overrides=size_overrides,
            node_configs={"sensor0": {"mode": "wide_16_9_30"}},
            routing_switch={},
            topology_patch={},
        ),
        ip_catalog={
            "ip-sensor-rear": SimpleNamespace(
                id="ip-sensor-rear",
                category="sensor",
                capabilities={
                    "properties": {
                        "place": "rear",
                        "phy_type": "CPHY",
                        "modes": {
                            "wide_16_9_30": {
                                "sensor_size": [4080, 2296],
                                "sensor_fps": 30.0,
                                "sensor_format": "BAYER",
                                "sensor_bitwidth": 12,
                            },
                            "full_4_3": {
                                "sensor_size": [8160, 6120],
                                "sensor_fps": 15.0,
                                "sensor_format": "BAYER",
                                "sensor_bitwidth": 12,
                            },
                        },
                    }
                },
            ),
            "ip-csis": SimpleNamespace(id="ip-csis", category="camera", capabilities={}),
        },
    )
