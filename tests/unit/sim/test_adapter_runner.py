from __future__ import annotations

import pytest


pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Scenario
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.db.repositories.variant_resolution import ResolvedScenarioVariant
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import DVFSLevel, DVFSTable, SimulationRunConfig
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation


def test_adapter_runner_builds_evidence_from_canonical_graph():
    graph = _graph()
    inputs = build_simulation_inputs(
        graph,
        SimulationRunConfig(include_timeline=True),
    )

    assert [item.node_id for item in inputs.workloads] == ["isp0", "mfc"]
    assert len(inputs.port_transfers) == 3

    result = run_simulation(
        inputs,
        dvfs_tables={
            "CAM": DVFSTable(
                domain="CAM",
                levels=[
                    DVFSLevel(level=0, speed_mhz=600, voltages={4: 780}),
                    DVFSLevel(level=1, speed_mhz=400, voltages={4: 700}),
                ],
            ),
            "INT": DVFSTable(
                domain="INT",
                levels=[
                    DVFSLevel(level=0, speed_mhz=533, voltages={4: 760}),
                    DVFSLevel(level=1, speed_mhz=266, voltages={4: 680}),
                ],
            ),
        },
    )
    hash_value = params_hash(inputs)
    evidence = build_simulation_evidence(
        result,
        execution_context=ExecutionContext(
            silicon_rev="EVT0",
            sw_baseline_ref="sw-vendor-v1.2.3",
            thermal="hot",
        ),
        project_ref=inputs.project_ref,
        params_hash=hash_value,
        timestamp="2026-05-07T00:00:00+09:00",
    )

    assert result.total_power_mw > 0
    assert result.bw_total_mbs > 0
    assert result.timeline_events[-1].task_id == "mfc"
    assert evidence.kind == "evidence.simulation"
    assert evidence.params_hash == hash_value
    assert evidence.kpi["critical_path_ms"] > 0
    assert evidence.kpi["critical_path_task_count"] >= 1
    assert {item.port for item in evidence.dma_breakdown} == {"RDMA_FE", "WDMA_BE", "MFC_RDMA"}
    assert evidence.timeline_events[-1].end_ms > 0


def test_adapter_uses_mode_specific_sim_params():
    graph = _graph()
    graph.variant.node_configs["isp0"]["selected_mode"] = "tDMSC"
    graph.ip_catalog["ip-isp-v12"].capabilities = {
        "operating_modes": [],
        "sim": {
            "hw_name": "ISP",
            "vdd": "VDD_CAM",
            "dvfs_group": "CAM",
            "modes": {
                "Normal": {"ppc": 4, "unit_power_mw_mp": 10},
                "tDMSC": {"ppc": 2, "unit_power_mw_mp": 14.5},
            },
        },
    }

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))
    isp = next(item for item in inputs.workloads if item.node_id == "isp0")

    assert isp.mode == "tDMSC"
    assert isp.sim_params.ppc == 2
    assert isp.sim_params.unit_power_mw_mp == 14.5
    assert inputs.warnings == []


def test_adapter_uses_role_specific_sim_params():
    graph = _graph()
    graph.scenario.pipeline["nodes"][0]["role"] = "bayer_processing"
    graph.ip_catalog["ip-isp-v12"].capabilities = {
        "operating_modes": [],
        "sim": {
            "hw_name": "ISP",
            "modes": {
                "Normal": {"ppc": 0, "unit_power_mw_mp": 0},
            },
            "role_modes": {
                "bayer_processing": {
                    "hw_name": "BYRP",
                    "modes": {
                        "Normal": {
                            "ppc": 4,
                            "unit_power_mw_mp": 4.34,
                            "vdd": "VDD_CAM",
                            "dvfs_group": "CAM",
                        }
                    },
                }
            },
        },
    }

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))
    isp = next(item for item in inputs.workloads if item.node_id == "isp0")

    assert isp.hw_name == "BYRP"
    assert isp.sim_params.ppc == 4
    assert isp.sim_params.unit_power_mw_mp == 4.34
    assert inputs.warnings == []


def test_runner_uses_reference_voltage_when_dvfs_table_is_missing():
    graph = _graph()
    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))

    result = run_simulation(inputs, dvfs_tables={})

    assert result.core_power_mw > 0
    assert result.resolved["isp0"].set_voltage_mv > 0


def test_adapter_falls_back_to_variant_resolution_and_m2m_edges():
    graph = _graph()
    graph.scenario.size_profile = None
    graph.variant.design_conditions = {"fps": 30, "resolution": "FHD"}
    graph.variant.node_configs["isp0"]["sim"] = {}
    graph.variant.node_configs["mfc"]["sim"] = {}

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))

    assert {item.node_id: (item.width, item.height) for item in inputs.workloads} == {
        "isp0": (1920, 1080),
        "mfc": (1920, 1080),
    }
    assert [(item.node_id, item.port_type) for item in inputs.port_transfers] == [
        ("isp0", "DMA_WRITE"),
        ("mfc", "DMA_READ"),
    ]


def test_adapter_warns_when_sim_params_default_to_zero():
    graph = _graph()
    graph.ip_catalog["ip-isp-v12"].capabilities = {"operating_modes": [], "sim": {"hw_name": "ISP"}}

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))
    isp = next(item for item in inputs.workloads if item.node_id == "isp0")

    assert isp.sim_params.ppc == 0.0
    assert isp.sim_params.unit_power_mw_mp == 0.0
    assert any("isp0" in warning and "ppc=0" in warning for warning in inputs.warnings)
    assert any("isp0" in warning and "unit_power_mw_mp=0.0" in warning for warning in inputs.warnings)


def test_adapter_excludes_external_sensor_and_panel_from_compute_workloads():
    graph = _graph()
    graph.scenario.pipeline["nodes"].extend(
        [
            {"id": "sensor_front", "ip_ref": "ip-sensor-front-s5e9965", "role": "sensor"},
            {"id": "panel", "ip_ref": "ip-display-panel-s5e9965", "role": "panel"},
        ]
    )
    graph.ip_catalog["ip-sensor-front-s5e9965"] = IpCatalog(
        id="ip-sensor-front-s5e9965",
        schema_version="2.2",
        category="sensor",
        hierarchy={},
        capabilities={"sim": {"modes": {"Normal": {"ppc": 0, "unit_power_mw_mp": 0}}}},
        yaml_sha256="sha",
    )
    graph.ip_catalog["ip-display-panel-s5e9965"] = IpCatalog(
        id="ip-display-panel-s5e9965",
        schema_version="2.2",
        category="display",
        hierarchy={},
        capabilities={"sim": {"modes": {"Normal": {"ppc": 0, "unit_power_mw_mp": 0}}}},
        yaml_sha256="sha",
    )

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))

    assert {item.node_id for item in inputs.workloads} == {"isp0", "mfc"}
    assert not any("sensor_front" in warning for warning in inputs.warnings)
    assert not any("panel" in warning for warning in inputs.warnings)


def test_adapter_adds_sensor_source_and_panel_sink_timing_constraints():
    graph = _graph()
    graph.variant.design_conditions["fps"] = 60
    graph.scenario.pipeline["task_graph"] = {
        "nodes": [
            {"id": "t_sensor", "label": "Sensor", "layer": "hw"},
            {"id": "t_csis", "label": "CSIS", "layer": "hw", "ip_ref": "ip-csis-v8"},
            {"id": "t_dpu", "label": "DPU", "layer": "hw", "ip_ref": "ip-dpu-v9"},
        ],
        "edges": [
            {"from": "t_sensor", "to": "t_csis", "type": "OTF"},
            {"from": "t_csis", "to": "t_dpu", "type": "M2M"},
        ],
    }
    graph.ip_catalog["ip-sensor-front-s5e9965"] = IpCatalog(
        id="ip-sensor-front-s5e9965",
        schema_version="2.2",
        category="sensor",
        hierarchy={},
        capabilities={
            "properties": {
                "modes": {
                    "mode0": {
                        "sensor_fps": 60.0,
                        "sensor_size": [4000, 2252],
                        "sensor_pclk": 1_760_000_000,
                        "sensor_line_length_pck": 6440,
                    }
                }
            }
        },
        yaml_sha256="sha",
    )
    graph.ip_catalog["ip-display-panel-s5e9965"] = IpCatalog(
        id="ip-display-panel-s5e9965",
        schema_version="2.2",
        category="display",
        hierarchy={},
        capabilities={"properties": {"refresh_rates": [60, 120]}},
        yaml_sha256="sha",
    )

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=True))
    by_task = {task["id"]: task for task in inputs.timeline_tasks}

    assert by_task["t_sensor"]["constraint_type"] == "source"
    assert by_task["t_sensor"]["source_fps"] == 60.0
    assert by_task["t_sensor"]["v_valid_ms"] == pytest.approx(8.240273)
    assert by_task["t_sensor"]["duration_ms"] == pytest.approx(8.240273)
    assert by_task["t_dpu"]["constraint_type"] == "sink"
    assert by_task["t_dpu"]["refresh_hz"] == 60.0
    assert by_task["t_dpu"]["deadline_ms"] == pytest.approx(16.666667)


def _graph() -> CanonicalScenarioGraph:
    scenario = Scenario(
        id="uc-camera-recording",
        schema_version="2.2",
        project_ref="proj-A-exynos2500",
        metadata_={"name": "Camera Recording"},
        pipeline={
            "nodes": [
                {"id": "isp0", "ip_ref": "ip-isp-v12"},
                {"id": "mfc", "ip_ref": "ip-mfc-v14"},
            ],
            "edges": [
                {"from": "isp0", "to": "mfc", "type": "M2M", "buffer": "RECORD_BUF"},
            ],
            "buffers": {
                "RECORD_BUF": {"size_ref": "record_out", "format": "NV12"},
            },
        },
        size_profile={"anchors": {"record_out": "1920x1080"}},
        design_axes=[],
        yaml_sha256="sha",
    )
    variant = ResolvedScenarioVariant(
        scenario_id="uc-camera-recording",
        id="FHD30-SDR-H265",
        severity="heavy",
        design_conditions={"fps": 30},
        size_overrides={},
        routing_switch={},
        topology_patch={},
        node_configs={
            "isp0": {
                "selected_mode": "Normal",
                "sim": {
                    "inputs": [
                        {
                            "port": "RDMA_FE",
                            "width": 1920,
                            "height": 1080,
                            "format": "NV12",
                            "bitwidth": 8,
                        }
                    ],
                    "outputs": [
                        {
                            "port": "WDMA_BE",
                            "width": 1920,
                            "height": 1080,
                            "format": "NV12",
                            "bitwidth": 8,
                            "compression": "SBWC",
                            "comp_ratio": 0.5,
                        }
                    ],
                },
            },
            "mfc": {
                "selected_mode": "Normal",
                "sim": {
                    "inputs": [
                        {
                            "port": "MFC_RDMA",
                            "width": 1920,
                            "height": 1080,
                            "format": "NV12",
                            "bitwidth": 8,
                        }
                    ]
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
        inheritance_chain=["FHD30-SDR-H265"],
    )
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        ip_catalog={
            "ip-isp-v12": IpCatalog(
                id="ip-isp-v12",
                schema_version="2.2",
                category="camera",
                hierarchy={},
                capabilities={
                    "operating_modes": [],
                    "sim": {
                        "hw_name": "ISP",
                        "ppc": 4,
                        "unit_power_mw_mp": 10,
                        "vdd": "VDD_CAM",
                        "dvfs_group": "CAM",
                    },
                },
                yaml_sha256="sha",
            ),
            "ip-mfc-v14": IpCatalog(
                id="ip-mfc-v14",
                schema_version="2.2",
                category="codec",
                hierarchy={},
                capabilities={
                    "operating_modes": [],
                    "sim": {
                        "hw_name": "MFC",
                        "ppc": 4,
                        "unit_power_mw_mp": 5,
                        "vdd": "VDD_INT",
                        "dvfs_group": "INT",
                    },
                },
                yaml_sha256="sha",
            ),
        },
    )
