from __future__ import annotations

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Scenario
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.db.repositories.variant_resolution import ResolvedScenarioVariant
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.shape_propagation import propagate_shapes


def test_shape_propagation_carries_sensor_shape_through_otf_and_scale():
    graph = _sensor_graph()

    shapes = propagate_shapes(graph)

    assert shapes.node("byrp").input.width == 4080
    assert shapes.node("byrp").input.height == 2296
    assert shapes.node("byrp").input.format == "BAYER"
    assert shapes.node("gdc").output.width == 1920
    assert shapes.node("gdc").output.height == 1080
    assert shapes.node("gdc").output.format == "YUV420"


def test_adapter_uses_propagated_shape_for_workloads_and_port_defaults():
    graph = _sensor_graph()

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))

    by_node = {item.node_id: item for item in inputs.workloads}
    assert (by_node["byrp"].width, by_node["byrp"].height) == (4080, 2296)
    assert (by_node["gdc"].width, by_node["gdc"].height) == (1920, 1080)
    gdc_wdma = next(item for item in inputs.port_transfers if item.node_id == "gdc" and item.port == "GDC_WDMA")
    assert (gdc_wdma.width, gdc_wdma.height) == (1920, 1080)
    assert gdc_wdma.format == "YUV420"


def _sensor_graph() -> CanonicalScenarioGraph:
    scenario = Scenario(
        id="uc-explore-camera",
        schema_version="2.2",
        project_ref="proj-explore",
        metadata_={"name": "Explore Camera"},
        pipeline={
            "nodes": [
                {"id": "sensor", "ip_ref": "ip-sensor", "role": "sensor"},
                {"id": "byrp", "ip_ref": "ip-camera", "role": "byrp"},
                {"id": "gdc", "ip_ref": "ip-camera", "role": "gdc"},
            ],
            "edges": [
                {"from": "sensor", "to": "byrp", "type": "OTF"},
                {"from": "byrp", "to": "gdc", "type": "OTF"},
            ],
            "buffers": {},
        },
        size_profile=None,
        design_axes=[],
        yaml_sha256="sha",
    )
    variant = ResolvedScenarioVariant(
        scenario_id=scenario.id,
        id="explore-fhd30",
        severity="medium",
        design_conditions={"fps": 30, "resolution": "FHD", "sensor_place": "rear"},
        size_overrides={},
        routing_switch={},
        topology_patch={},
        node_configs={
            "byrp": {"selected_mode": "Normal", "sim": {"inherit_shape": True}},
            "gdc": {
                "selected_mode": "Normal",
                "sim": {
                    "inherit_shape": True,
                    "scale": {"width": 1920, "height": 1080},
                    "output_format": "YUV420",
                    "outputs": [{"port": "GDC_WDMA", "port_type": "DMA_WRITE"}],
                },
            },
        },
        buffer_overrides={},
        ip_requirements={},
        sw_requirements=None,
        violation_policy=None,
        tags=[],
        derived_from_variant=None,
        resolved=True,
        inheritance_chain=[],
    )
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        ip_catalog={
            "ip-sensor": IpCatalog(
                id="ip-sensor",
                schema_version="2.2",
                category="sensor",
                hierarchy={},
                capabilities={
                    "properties": {
                        "place": "rear",
                        "phy_type": "CPHY",
                        "modes": {
                            "wide_video_16_9_30": {
                                "sensor_size": [4080, 2296],
                                "sensor_fps": 30,
                                "sensor_format": "BAYER",
                                "sensor_bitwidth": 12,
                                "sensor_mipi_speed": 3.993,
                            }
                        },
                    }
                },
                yaml_sha256="sha",
            ),
            "ip-camera": IpCatalog(
                id="ip-camera",
                schema_version="2.2",
                category="camera",
                hierarchy={},
                capabilities={
                    "sim": {
                        "hw_name": "CAM",
                        "ppc": 4,
                        "unit_power_mw_mp": 1.0,
                        "vdd": "VDD_CAM",
                        "dvfs_group": "CAM",
                    }
                },
                yaml_sha256="sha",
            ),
        },
    )
