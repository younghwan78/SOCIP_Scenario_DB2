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
            silicon_rev="A0",
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
    assert {item.port for item in evidence.dma_breakdown} == {"RDMA_FE", "WDMA_BE", "MFC_RDMA"}
    assert evidence.timeline_events[-1].end_ms > 0


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
