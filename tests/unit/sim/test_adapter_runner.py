from __future__ import annotations

from pathlib import Path

import pytest
import yaml


pytest.importorskip("networkx")
pytest.importorskip("simpy")

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.db.repositories.variant_resolution import ResolvedScenarioVariant, resolve_variant_from_rows
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.clock_corrections import _req_csis_clock_mhz
from scenario_db.sim.golden import compare_golden_result
from scenario_db.sim.readiness import check_simulation_readiness
from scenario_db.sim.models import DVFSLevel, DVFSTable, SimulationRunConfig
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation


def test_adapter_runner_builds_evidence_from_canonical_graph():
    graph = _graph()
    inputs = build_simulation_inputs(
        graph,
        SimulationRunConfig(include_timeline=True, timeline_frame_count=1),
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
    assert evidence.kpi["timeline_end_ms"] > 0
    assert evidence.kpi["critical_path_ms"] == 0.0
    assert evidence.kpi["critical_path_task_count"] == 0
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


def test_adapter_matches_sim_modes_case_insensitively():
    graph = _graph()
    graph.variant.node_configs["mfc"]["selected_mode"] = "normal"
    graph.ip_catalog["ip-mfc-v14"].capabilities = {
        "operating_modes": [],
        "sim": {
            "hw_name": "MFC",
            "modes": {
                "Normal": {
                    "ppc": 4,
                    "unit_power_mw_mp": 1.0,
                    "vdd": "VDD_INT",
                    "dvfs_group": "INT",
                },
            },
        },
    }

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))
    mfc = next(item for item in inputs.workloads if item.node_id == "mfc")

    assert mfc.sim_params.ppc == 4
    assert mfc.sim_params.unit_power_mw_mp == 1.0
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


def test_runner_builds_debug_calculation_trace():
    graph = _graph()
    inputs = build_simulation_inputs(
        graph,
        SimulationRunConfig(include_timeline=True, debug_trace=True),
    )

    result = run_simulation(inputs, dvfs_tables={})
    evidence = build_simulation_evidence(
        result,
        execution_context=ExecutionContext(
            silicon_rev="EVT0",
            sw_baseline_ref="sw-vendor-v1.2.3",
            thermal="normal",
        ),
        project_ref=inputs.project_ref,
        params_hash=params_hash(inputs),
        timestamp="2026-05-07T00:00:00+09:00",
    )

    trace = evidence.calculation_trace
    assert trace is not None
    assert trace["kpi"]["total_power_mw"]["result"] == result.total_power_mw
    assert trace["kpi"]["total_bw_mbs"]["result"] == result.bw_total_mbs
    assert trace["ip"][0]["required_clock"]["base_formula"].startswith("pixels * fps")
    assert "clock_correction_mhz" in trace["ip"][0]["required_clock"]
    assert trace["dma"][0]["result"]["bw_mbs"] == result.dma_breakdown[0].bw_mbs
    assert trace["dma"][0]["bw_power_formula"] == "bw_mbs * bw_power_coeff / 1000 * llc_weight"
    assert trace["timeline"]["summary"]["event_count"] == len(result.timeline_events)
    assert "critical_path" in trace["timeline"]
    assert "top_waits" in trace["timeline"]
    assert "cadence" in trace["timeline"]


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


def test_simulation_readiness_reports_blocking_catalog_gaps():
    graph = _graph()
    graph.ip_catalog["ip-isp-v12"].capabilities = {"operating_modes": []}

    report = check_simulation_readiness(graph)

    assert report["status"] == "blocked"
    assert report["summary"]["compute_nodes"] == 2
    assert any(issue["code"] == "MISSING_PPC" and issue["node_id"] == "isp0" for issue in report["errors"])
    assert any(issue["code"] == "MISSING_UNIT_POWER" and issue["node_id"] == "isp0" for issue in report["warnings"])


def test_simulation_readiness_uses_soc_profile_for_clean_graph():
    graph = _graph()

    report = check_simulation_readiness(graph)

    assert report["status"] == "ready"
    assert report["soc_id"] == "generic"
    assert report["summary"]["compute_nodes"] == 2
    assert report["errors"] == []
    assert report["warnings"] == []


def test_runner_warns_when_all_compute_core_power_is_zero():
    graph = _graph()
    graph.ip_catalog["ip-isp-v12"].capabilities = {"operating_modes": []}
    graph.ip_catalog["ip-mfc-v14"].capabilities = {"operating_modes": []}

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))
    result = run_simulation(inputs, dvfs_tables={})

    assert any("no capabilities.sim" in warning for warning in result.warnings)
    assert any("All compute IP core power is zero" in warning for warning in result.warnings)
    assert any("All compute IP HW time is zero" in warning for warning in result.warnings)


def test_demo_imported_fhd30_fixture_has_nonzero_compute_power_without_warnings():
    graph = _demo_generated_graph("uc-demo-import-recording", "FHD30-Imported")

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=True))
    result = run_simulation(inputs, dvfs_tables={})

    assert result.warnings == []
    assert result.core_power_mw > 0
    assert result.hw_time_max_ms > 0
    power_by_node = {node_id: item.total_power_mw for node_id, item in result.resolved.items()}
    for node_id in ("csis0", "isp0", "mfc", "dpu"):
        assert power_by_node[node_id] > 0
    assert "llc" not in power_by_node


def test_simulation_regression_smoke_keeps_reference_kpis_and_clocks_stable():
    base_inputs = build_simulation_inputs(
        _graph(),
        SimulationRunConfig(include_timeline=True, timeline_frame_count=2, debug_trace=True),
    )
    base_result = run_simulation(
        base_inputs,
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

    assert base_result.warnings == []
    assert base_result.total_power_mw == pytest.approx(48.328742, rel=1e-6)
    assert base_result.bw_total_mbs == pytest.approx(233.28)
    assert base_result.hw_time_max_ms == pytest.approx(2.046316, rel=1e-6)
    assert base_result.timeline_end_ms == pytest.approx(36.740449, rel=1e-6)
    assert base_result.resolved["isp0"].set_clock_mhz == pytest.approx(400.0)
    assert base_result.resolved["mfc"].set_clock_mhz == pytest.approx(266.0)

    demo_inputs = build_simulation_inputs(
        _demo_generated_graph("uc-demo-import-recording", "FHD30-Imported"),
        SimulationRunConfig(include_timeline=True, timeline_frame_count=2, debug_trace=True),
    )
    demo_result = run_simulation(demo_inputs, dvfs_tables={})

    assert demo_result.warnings == []
    assert demo_result.total_power_mw == pytest.approx(58.745088, rel=1e-6)
    assert demo_result.bw_total_mbs == pytest.approx(419.904)
    assert demo_result.hw_time_max_ms == pytest.approx(29.75)
    assert demo_result.timeline_end_ms == pytest.approx(92.833333, rel=1e-6)
    assert demo_result.resolved["csis0"].clock_correction_reason == "otf_group_clock_align(otf-0, leader=isp0)"
    assert demo_result.resolved["isp0"].clock_correction_reason == "otf_group_clock_align(otf-0, leader=isp0)"
    assert demo_result.resolved["csis0"].required_clock_mhz == pytest.approx(18.296470588235298)
    assert demo_result.resolved["isp0"].required_clock_mhz == pytest.approx(18.296470588235298)
    assert demo_result.resolved["mfc"].required_clock_mhz == pytest.approx(18.296470588235298)
    assert demo_result.resolved["dpu"].required_clock_mhz == pytest.approx(18.296470588235298)


# Timing references use node-level resources and OTF reservations (2026-09-05).
# Capacity invariants below independently guard the corrected schedule.
def test_exynos2600_camera_recording_vdis_preserves_is_v15_timing_contract():
    inputs = build_simulation_inputs(
        _exynos2600_generated_graph("uc-camera-recording", "cam-rec-r1-fhd30-vdis"),
        SimulationRunConfig(include_timeline=True, timeline_frame_count=4, debug_trace=True),
    )
    result = run_simulation(inputs, dvfs_tables={})
    sensor = next(item for item in result.external_devices if item["device_type"] == "sensor")
    assert sensor["mode"] == "cis_4sum_idcg_ln4_raw12_4080x2296_30fps_3993msps"
    assert sensor["size"] == "4080x2296"
    assert sensor["v_valid_ms"] == pytest.approx(18.987754, abs=1e-6)
    assert result.resolved["csis"].required_clock_mhz == pytest.approx(285.2142857142857)
    rt_events = {event.node_id: event for event in result.timeline_events if event.frame_index == 0}
    for node in ["csis", "pdp", "byrp", "rgbp", "yuvsc", "mlsc"]:
        assert rt_events[node].start_ms == pytest.approx(rt_events["sensor_rear"].start_ms)
        assert rt_events[node].end_ms == pytest.approx(rt_events["sensor_rear"].end_ms)
    assert rt_events["post_crta"].start_ms == pytest.approx(rt_events["mlsc"].end_ms + 1.0)
    assert rt_events["post_crta"].duration_ms == pytest.approx(0.3)
    assert rt_events["pre_me_rta"].duration_ms == pytest.approx(3.0)
    assert rt_events["post_irta"].duration_ms == pytest.approx(4.0)
    assert "lme" not in rt_events  # included in preME, never counted twice
    lme = next(row for row in result.timing_breakdown if row.node_id == "lme")
    assert lme.hw_time_ms <= 3.0 + 1e-9
    assert any("assumed wall time" in warning for warning in result.warnings)
    assert any("core power estimate will be zero" in warning for warning in result.warnings)
    assert result.bw_total_mbs == pytest.approx(4092.40188 + 1008 * 756 * 30 / 1e6)


def test_full_debug_trace_includes_timeline_event_rows():
    inputs = build_simulation_inputs(
        _exynos2600_generated_graph("uc-camera-recording", "cam-rec-r1-fhd30-vdis"),
        SimulationRunConfig(include_timeline=True, timeline_frame_count=2, debug_trace=True, debug_trace_level="full"),
    )
    result = run_simulation(inputs, dvfs_tables={})

    trace = result.calculation_trace
    assert trace is not None
    assert trace["trace_level"] == "full"
    assert len(trace["timeline"]["events"]) == len(result.timeline_events)
    assert {"task_id", "start_ms", "end_ms", "bottleneck_reason"}.issubset(trace["timeline"]["events"][0])


@pytest.mark.parametrize(
    ("variant_id", "channels", "sensor_name"),
    [("cam-rec-r1-uhd30-vdis", 2, "GNG"), ("cam-rec-f1-fhd30", 1, "IMX874")],
)
def test_exynos2600_camera_recording_paths_match_board_and_output_policy(variant_id, channels, sensor_name):
    graph = _exynos2600_generated_graph("uc-camera-recording", variant_id)
    inputs = build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=4))
    result = run_simulation(inputs, dvfs_tables={})
    sensor = next(row for row in result.external_devices if row["device_type"] == "sensor")
    assert sensor_name.lower() in sensor["ip_ref"].lower()
    ports = [row for row in inputs.port_transfers if row.node_id == "mcsc"]
    assert len(ports) == channels
    assert ports[0].width == 1920 and ports[0].height == 1080
    if channels == 2:
        assert ports[1].width == 3840 and ports[1].height == 2160
    assert {"mlsc", "pdp", "csis", "vps_od"}.issubset(result.resolved)
    assert "n3aa" not in result.resolved and "csispdp" not in result.resolved
    assert len([event for event in result.timeline_events if event.node_id == "panel"]) == 4


def test_golden_comparator_accepts_reference_result_and_reports_diffs():
    inputs = build_simulation_inputs(
        _demo_generated_graph("uc-demo-import-recording", "FHD30-Imported"),
        SimulationRunConfig(include_timeline=True, timeline_frame_count=2, debug_trace=True),
    )
    result = run_simulation(inputs, dvfs_tables={})
    expected = {
        "warnings": [],
        "metrics": {
            "total_power_mw": {"value": 58.745088, "rel_tol": 1e-6},
            "bw_total_mbs": {"value": 419.904, "abs_tol": 1e-6},
        },
        "resolved": {"csis0": {"required_clock_mhz": {"value": 18.296470588235298, "abs_tol": 1e-6}}},
    }

    assert compare_golden_result(result, expected) == []
    diffs = compare_golden_result(result, {"metrics": {"total_power_mw": {"value": 1.0, "abs_tol": 0.0}}})
    assert diffs[0]["field"] == "metrics.total_power_mw"


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


def test_adapter_excludes_llc_memory_from_compute_workloads():
    graph = _graph()
    graph.scenario.pipeline["nodes"].append({"id": "llc", "ip_ref": "ip-llc-v2", "role": "memory"})
    graph.ip_catalog["ip-llc-v2"] = IpCatalog(
        id="ip-llc-v2",
        schema_version="2.2",
        category="memory",
        hierarchy={},
        capabilities={"sim": {"modes": {"Normal": {"ppc": 0, "unit_power_mw_mp": 0}}}},
        yaml_sha256="sha",
    )

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))

    assert {item.node_id for item in inputs.workloads} == {"isp0", "mfc"}
    assert not any("llc" in warning for warning in inputs.warnings)


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


def test_adapter_records_external_devices_and_prefers_sensor_place():
    graph = _graph()
    graph.variant.design_conditions.update(
        {
            "fps": 30,
            "resolution": "FHD",
            "subscenario": "FHD_VIDEO",
            "sensor_place": "front",
        }
    )
    graph.scenario.pipeline["nodes"] = [
        {"id": "sensor_rear", "ip_ref": "ip-sensor-rear-s5e9965", "role": "sensor"},
        {"id": "sensor_front", "ip_ref": "ip-sensor-front-s5e9965", "role": "sensor"},
        *graph.scenario.pipeline["nodes"],
        {"id": "panel", "ip_ref": "ip-display-panel-s5e9965", "role": "display_output"},
    ]
    graph.scenario.pipeline["edges"] = [
        {"from": "sensor_front", "to": "isp0", "type": "OTF"},
        *graph.scenario.pipeline["edges"],
        {"from": "mfc", "to": "panel", "type": "OTF"},
    ]
    graph.ip_catalog["ip-sensor-rear-s5e9965"] = IpCatalog(
        id="ip-sensor-rear-s5e9965",
        schema_version="2.2",
        category="sensor",
        hierarchy={},
        capabilities={
            "properties": {
                "place": "rear",
                "modes": {"binning_4x4": {"sensor_size": [4000, 3000], "sensor_fps": 60, "sensor_format": "BAYER"}},
            }
        },
        yaml_sha256="sha",
    )
    graph.ip_catalog["ip-sensor-front-s5e9965"] = IpCatalog(
        id="ip-sensor-front-s5e9965",
        schema_version="2.2",
        category="sensor",
        hierarchy={},
        capabilities={
            "properties": {
                "place": "front",
                "modes": {"normal": {"sensor_size": [3648, 2736], "sensor_fps": 60, "sensor_format": "BAYER"}},
            }
        },
        yaml_sha256="sha",
    )
    graph.ip_catalog["ip-display-panel-s5e9965"] = IpCatalog(
        id="ip-display-panel-s5e9965",
        schema_version="2.2",
        category="display",
        hierarchy={},
        capabilities={"properties": {"display_size": [3088, 1440], "format": "RGB", "refresh_rates": [60, 120]}},
        yaml_sha256="sha",
    )

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=False))
    devices = {item["node_id"]: item for item in inputs.external_devices}

    assert devices["sensor_front"]["ip_ref"] == "ip-sensor-front-s5e9965"
    assert devices["sensor_front"]["catalog_size"] == "3648x2736"
    assert devices["sensor_front"]["active_size"] == "3648x2052"
    assert devices["sensor_front"]["active_size_source"] == "derived_16_9_crop_from_catalog_width"
    assert devices["sensor_front"]["v_valid_ms"] == pytest.approx(1000.0 / 60.0)
    assert devices["sensor_front"]["v_valid_source"] == "frame_period_fallback_no_vblank"
    assert devices["panel"]["size"] == "3088x1440"


def test_adapter_applies_sensor_otf_csis_clock_correction():
    graph = _graph()
    graph.variant.design_conditions.update(
        {
            "fps": 30,
            "resolution": "FHD",
            "subscenario": "FHD_VIDEO",
            "sensor_place": "rear",
        }
    )
    graph.scenario.pipeline["nodes"] = [
        {"id": "sensor_rear", "ip_ref": "ip-sensor-rear-s5e9965", "role": "sensor"},
        *graph.scenario.pipeline["nodes"],
    ]
    graph.scenario.pipeline["edges"] = [
        {"from": "sensor_rear", "to": "isp0", "type": "OTF"},
        *graph.scenario.pipeline["edges"],
    ]
    graph.ip_catalog["ip-sensor-rear-s5e9965"] = IpCatalog(
        id="ip-sensor-rear-s5e9965",
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
                        "sensor_fps": 30.0,
                        "sensor_pclk": 3_532_800_000,
                        "sensor_line_length_pck": 29_216,
                        "sensor_format": "BAYER",
                        "sensor_bitwidth": 12,
                        "sensor_mipi_speed": 3.993,
                        "sensor_sbwc": "enable",
                    }
                },
            }
        },
        yaml_sha256="sha",
    )

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=True))
    by_node = {item.node_id: item for item in inputs.workloads}
    result = run_simulation(inputs, dvfs_tables={})

    expected_clock = 3.993 * (16 / 7) * 3 / (12 * 4) * 1000
    assert by_node["isp0"].clock_correction_mhz == pytest.approx(expected_clock)
    assert by_node["mfc"].clock_correction_mhz == 0.0
    assert result.resolved["isp0"].required_clock_mhz == pytest.approx(expected_clock)
    sensor = next(item for item in inputs.external_devices if item["device_type"] == "sensor")
    assert sensor["v_valid_ms"] == pytest.approx((29_216 * 1000 / 3_532_800_000) * 2296)
    assert sensor["v_valid_source"] == "sensor_line_length_pck * 1000 / sensor_pclk * height"
    assert sensor["line_length_pck"] == 29_216
    assert sensor["pclk"] == 3_532_800_000


@pytest.mark.parametrize(
    ("phy_type", "sbwc_enabled", "expected"),
    [
        ("CPHY", False, 3.993 * (16 / 7) * 3 / 12 * 1000),
        ("CPHY", True, 3.993 * (16 / 7) * 3 / (12 * 4) * 1000),
        ("DPHY", False, 3.993 * 4 / 12 * 1000),
        ("DPHY", True, 3.993 * 4 / (12 * 4) * 1000),
    ],
)
def test_csis_mipi_clock_formula_applies_ppc_only_for_sbwc(phy_type, sbwc_enabled, expected):
    assert _req_csis_clock_mhz(
        sensor_mipi_speed=3.993,
        sensor_bitwidth=12,
        sensor_phy_type=phy_type,
        ppc=4,
        sensor_sbwc_enabled=sbwc_enabled,
    ) == pytest.approx(expected)


def test_adapter_aligns_sensor_otf_group_without_reapplying_mipi_clock_to_downstream_ips():
    graph = _graph()
    graph.variant.design_conditions.update(
        {
            "fps": 30,
            "resolution": "FHD",
            "subscenario": "FHD_VIDEO",
            "sensor_place": "rear",
        }
    )
    graph.scenario.pipeline["nodes"] = [
        {"id": "sensor_rear", "ip_ref": "ip-sensor-rear-s5e9965", "role": "sensor"},
        {"id": "csispdp", "ip_ref": "ip-isp-v12", "role": "csispdp"},
        {"id": "byrp", "ip_ref": "ip-isp-v12", "role": "byrp"},
    ]
    graph.scenario.pipeline["edges"] = [
        {"from": "sensor_rear", "to": "csispdp", "type": "OTF"},
        {"from": "csispdp", "to": "byrp", "type": "OTF"},
    ]
    graph.variant.node_configs = {
        "csispdp": {
            "selected_mode": "Normal",
            "sim": {"inputs": [{"port": "OTF_IN", "width": 1920, "height": 1080, "format": "BAYER"}]},
        },
        "byrp": {
            "selected_mode": "Normal",
            "sim": {"inputs": [{"port": "OTF_IN", "width": 1920, "height": 1080, "format": "BAYER"}]},
        },
    }
    graph.ip_catalog["ip-isp-v12"].capabilities = {
        "operating_modes": [],
        "sim": {
            "hw_name": "ISP",
            "vdd": "VDD_CAM",
            "dvfs_group": "CAM",
            "modes": {"Normal": {"ppc": 0, "unit_power_mw_mp": 0}},
            "role_modes": {
                "csispdp": {
                    "hw_name": "PDP",
                    "modes": {
                        "Normal": {
                            "ppc": 8,
                            "unit_power_mw_mp": 1,
                            "vdd": "VDD_CAM",
                            "dvfs_group": "CSIS",
                        }
                    },
                },
                "byrp": {
                    "hw_name": "BYRP",
                    "modes": {
                        "Normal": {
                            "ppc": 4,
                            "unit_power_mw_mp": 1,
                            "vdd": "VDD_CAM",
                            "dvfs_group": "CAM",
                        }
                    },
                },
            },
        },
    }
    graph.ip_catalog["ip-sensor-rear-s5e9965"] = IpCatalog(
        id="ip-sensor-rear-s5e9965",
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
                        "sensor_fps": 30.0,
                        "sensor_pclk": 3_532_800_000,
                        "sensor_line_length_pck": 29_216,
                        "sensor_format": "BAYER",
                        "sensor_bitwidth": 12,
                        "sensor_mipi_speed": 3.993,
                        "sensor_sbwc": "enable",
                    }
                },
            }
        },
        yaml_sha256="sha",
    )

    inputs = build_simulation_inputs(graph, SimulationRunConfig(include_timeline=True))
    by_node = {item.node_id: item for item in inputs.workloads}
    result = run_simulation(
        inputs,
        dvfs_tables={
            "CSIS": DVFSTable(
                domain="CSIS",
                levels=[
                    DVFSLevel(level=0, speed_mhz=800, voltages={4: 800}),
                    DVFSLevel(level=2, speed_mhz=533, voltages={4: 675}),
                    DVFSLevel(level=4, speed_mhz=332, voltages={4: 606.25}),
                    DVFSLevel(level=7, speed_mhz=133, voltages={4: 562.5}),
                ],
            ),
            "CAM": DVFSTable(
                domain="CAM",
                levels=[
                    DVFSLevel(level=0, speed_mhz=800, voltages={4: 800}),
                    DVFSLevel(level=2, speed_mhz=533, voltages={4: 675}),
                    DVFSLevel(level=4, speed_mhz=332, voltages={4: 606.25}),
                    DVFSLevel(level=7, speed_mhz=133, voltages={4: 562.5}),
                ],
            ),
        },
    )

    ingress_clock = 3.993 * (16 / 7) * 3 / (12 * 8) * 1000
    downstream_mipi_clock = 3.993 * (16 / 7) * 3 / (12 * 4) * 1000
    assert by_node["csispdp"].clock_correction_mhz == pytest.approx(ingress_clock)
    assert by_node["csispdp"].clock_correction_reason.startswith("sensor_ingress_req_csis_clock")
    assert by_node["byrp"].clock_correction_mhz == pytest.approx(ingress_clock)
    assert by_node["byrp"].clock_correction_mhz < downstream_mipi_clock
    assert by_node["byrp"].clock_correction_reason == "otf_group_clock_align(otf-0, leader=csispdp)"
    assert result.resolved["csispdp"].set_clock_mhz == pytest.approx(332.0)
    assert result.resolved["byrp"].set_clock_mhz == pytest.approx(332.0)


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


def _demo_generated_graph(scenario_id: str, variant_id: str) -> CanonicalScenarioGraph:
    root = Path(__file__).resolve().parents[3]
    scenario_raw = _read_yaml(root / "demo" / "generated" / "scenariodb" / "02_definition" / f"{scenario_id}.yaml")
    scenario = Scenario(
        id=scenario_raw["id"],
        schema_version=str(scenario_raw["schema_version"]),
        project_ref=scenario_raw["project_ref"],
        metadata_=scenario_raw.get("metadata") or {},
        pipeline=scenario_raw.get("pipeline") or {},
        size_profile=scenario_raw.get("size_profile"),
        design_axes=scenario_raw.get("design_axes"),
        yaml_sha256="sha",
    )
    variant_rows = {
        item["id"]: ScenarioVariant(
            scenario_id=scenario_id,
            id=item["id"],
            severity=item.get("severity"),
            design_conditions=item.get("design_conditions") or {},
            design_conditions_override=item.get("design_conditions_override") or {},
            size_overrides=item.get("size_overrides") or {},
            routing_switch=item.get("routing_switch") or {},
            topology_patch=item.get("topology_patch") or {},
            node_configs=item.get("node_configs") or {},
            buffer_overrides=item.get("buffer_overrides") or {},
            ip_requirements=item.get("ip_requirements") or {},
            sw_requirements=item.get("sw_requirements"),
            violation_policy=item.get("violation_policy"),
            tags=item.get("tags") or [],
            derived_from_variant=item.get("derived_from_variant"),
        )
        for item in scenario_raw.get("variants") or []
    }
    variant = resolve_variant_from_rows(variant_rows, scenario_id, variant_id)
    hw_dir = root / "demo" / "generated" / "scenariodb" / "00_hw"
    ip_catalog = {
        ip_id: _ip_catalog_from_yaml(hw_dir / f"{ip_id}.yaml")
        for ip_id in ("ip-csis-v8", "ip-isp-v12", "ip-mfc-v14", "ip-dpu-v9", "ip-llc-v2")
    }
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        ip_catalog=ip_catalog,
    )


def _exynos2600_generated_graph(scenario_id: str, variant_id: str) -> CanonicalScenarioGraph:
    root = Path(__file__).resolve().parents[3]
    fixture_root = root / "db_fixtures_Exynos2600_S26Plus"
    scenario_raw = _read_yaml(fixture_root / "02_definition" / f"{scenario_id}.yaml")
    scenario = Scenario(
        id=scenario_raw["id"],
        schema_version=str(scenario_raw["schema_version"]),
        project_ref=scenario_raw["project_ref"],
        metadata_=scenario_raw.get("metadata") or {},
        pipeline=scenario_raw.get("pipeline") or {},
        size_profile=scenario_raw.get("size_profile"),
        design_axes=scenario_raw.get("design_axes"),
        yaml_sha256="sha",
    )
    variant_rows = {
        item["id"]: ScenarioVariant(
            scenario_id=scenario_id,
            id=item["id"],
            severity=item.get("severity"),
            design_conditions=item.get("design_conditions") or {},
            design_conditions_override=item.get("design_conditions_override") or {},
            size_overrides=item.get("size_overrides") or {},
            routing_switch=item.get("routing_switch") or {},
            topology_patch=item.get("topology_patch") or {},
            node_configs=item.get("node_configs") or {},
            buffer_overrides=item.get("buffer_overrides") or {},
            ip_requirements=item.get("ip_requirements") or {},
            sw_requirements=item.get("sw_requirements"),
            violation_policy=item.get("violation_policy"),
            tags=item.get("tags") or [],
            derived_from_variant=item.get("derived_from_variant"),
        )
        for item in scenario_raw.get("variants") or []
    }
    variant = resolve_variant_from_rows(variant_rows, scenario_id, variant_id)
    ip_catalog = {
        raw["id"]: IpCatalog(
            id=raw["id"],
            schema_version=str(raw["schema_version"]),
            category=raw.get("category"),
            hierarchy=raw.get("hierarchy") or {},
            capabilities=raw.get("capabilities") or {},
            rtl_version=raw.get("rtl_version"),
            compatible_soc=raw.get("compatible_soc") or [],
            yaml_sha256="sha",
        )
        for raw in (_read_yaml(path) for path in (fixture_root / "00_hw").glob("ip-*.yaml"))
    }
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        ip_catalog=ip_catalog,
    )


def _ip_catalog_from_yaml(path: Path) -> IpCatalog:
    raw = _read_yaml(path)
    return IpCatalog(
        id=raw["id"],
        schema_version=str(raw["schema_version"]),
        category=raw.get("category"),
        hierarchy=raw.get("hierarchy") or {},
        capabilities=raw.get("capabilities") or {},
        rtl_version=raw.get("rtl_version"),
        compatible_soc=raw.get("compatible_soc") or [],
        yaml_sha256="sha",
    )


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("variant_id", ["cam-rec-r1-fhd30-vdis", "cam-rec-r1-uhd30-vdis", "cam-rec-f1-fhd30"])
def test_recording_schedule_respects_physical_resource_capacity(variant_id):
    inputs = build_simulation_inputs(
        _exynos2600_generated_graph("uc-camera-recording", variant_id),
        SimulationRunConfig(include_timeline=True, timeline_frame_count=4),
    )
    result = run_simulation(inputs, dvfs_tables={})
    reservations = {}
    for event in result.timeline_events:
        if not event.resource_id:
            continue
        key = (event.resource_id, event.otf_group_id or event.task_id)
        start, end = reservations.get(key, (event.start_ms, event.end_ms))
        reservations[key] = (min(start, event.start_ms), max(end, event.end_ms))
    for resource in {key[0] for key in reservations}:
        intervals = sorted(value for key, value in reservations.items() if key[0] == resource)
        for previous, current in zip(intervals, intervals[1:]):
            assert previous[1] <= current[0] + 1e-6, resource


def test_runner_uses_owning_node_fps_for_port_bandwidth():
    """Mixed-rate pipelines: a port's traffic runs at its node's fps, not one
    scenario-global fps (pre-fix every port used config.fps)."""
    from scenario_db.sim.models import (
        IPSimParams,
        IPWorkload,
        PortTransferSpec,
        PortType,
        SimulationInputs,
    )

    def _workload(node_id: str, fps: float) -> IPWorkload:
        return IPWorkload(
            node_id=node_id,
            ip_ref=f"ip-{node_id}",
            hw_name=node_id.upper(),
            width=1920,
            height=1080,
            fps=fps,
            sim_params=IPSimParams(hw_name=node_id.upper(), ppc=4, unit_power_mw_mp=10),
        )

    def _port(node_id: str) -> PortTransferSpec:
        return PortTransferSpec(
            node_id=node_id,
            ip_ref=f"ip-{node_id}",
            hw_name=node_id.upper(),
            port="WDMA0",
            port_type=PortType.DMA_WRITE,
            width=1920,
            height=1080,
            format="YUV420",
            bitwidth=8,
        )

    inputs = SimulationInputs(
        scenario_id="uc-x",
        variant_id="v1",
        config=SimulationRunConfig(fps=30.0, include_timeline=False),
        workloads=[_workload("isp0", 30.0), _workload("dpu0", 120.0)],
        port_transfers=[_port("isp0"), _port("dpu0")],
    )

    result = run_simulation(inputs, dvfs_tables={})
    bw = {item.node_id: item.bw_mbs for item in result.dma_breakdown}

    assert bw["dpu0"] == pytest.approx(bw["isp0"] * 4.0)


@pytest.mark.parametrize("case, preme, post", [("min", 2.5, 3.0), ("mean", 3.0, 4.0), ("max", 4.0, 5.6)])
def test_is_v15_timing_sensitivity_and_history_dma(case, preme, post):
    suffix = "" if case == "mean" else "-timing-" + case
    graph = _exynos2600_generated_graph("uc-camera-recording", "cam-rec-r1-fhd30-vdis" + suffix)
    inputs = build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=1))
    result = run_simulation(inputs, dvfs_tables={})
    events = {row.node_id: row for row in result.timeline_events}
    assert events["pre_me_rta"].duration_ms == pytest.approx(preme)
    assert events["post_irta"].duration_ms == pytest.approx(post)
    assert events["post_crta"].start_ms - events["mlsc"].end_ms == pytest.approx(1.0)
    assert "lme" not in events
    history = [p for p in inputs.port_transfers if p.node_id == "mtnr" and "_PREV_" in p.port]
    assert len(history) == 26  # 13 image planes in each direction, no double-counted YUV444
    assert len([p for p in history if p.format == "Y"]) == 26
    assert len([p for p in inputs.port_transfers if p.node_id == "mtnr" and "_CUR_" in p.port]) == 13
    for port in inputs.port_transfers:
        modules = graph.ip_catalog[port.ip_ref].capabilities["properties"].get("modules", [])
        assert port.port in {m["name"] for m in modules}
    for layer in range(5):
        planes = [p for p in history if f"_L{layer}_" in p.port]
        assert {(p.width, p.height) for p in planes} == {((4080 + 2**layer - 1) // 2**layer, (2296 + 2**layer - 1) // 2**layer)}
    digest = {row["task"]: row for row in inputs.sw_task_timing}
    assert digest["pre_me_rta"]["includes_hw_nodes"] == ["lme"]
    assert digest["post_crta"]["value_source"] == "assumed"


def test_is_v15_estimated_evidence_keeps_timing_and_exploration_status():
    from scenario_db.models.evidence.common import ExecutionContext
    from scenario_db.sim.runner import build_simulation_evidence
    from scenario_db.sim.service import _simulation_evidence_dict

    inputs = build_simulation_inputs(_exynos2600_generated_graph("uc-camera-recording", "cam-rec-r1-fhd30-vdis"))
    result = run_simulation(inputs, dvfs_tables={})
    evidence = build_simulation_evidence(result, execution_context=ExecutionContext(
        silicon_rev="EVT1", sw_baseline_ref="sw-vendor-v1.2.3", thermal="room", method="calculation",
    ))
    assert {row.instance_index for row in evidence.ip_breakdown if row.ip == "ip-gdc-is-v15-s5e9965"} == {0, 1}
    assert evidence.run.source == "estimated"
    assert evidence.resolution_result.overall_feasibility == "exploration_only"
    payload = _simulation_evidence_dict(evidence)
    assert len(payload["sw_task_timing"]) == 5
    row = next(row for row in payload["sw_task_timing"] if row["task"] == "post_crta")
    assert row["min_ms"] == 0.1 and row["mean_ms"] == 0.3 and row["max_ms"] == 0.5
    assert row["start_jitter_mean_ms"] == 1.0


def test_is_v15_invalid_timing_profile_is_rejected():
    graph = _exynos2600_generated_graph("uc-camera-recording", "cam-rec-r1-fhd30-vdis")
    graph.variant.node_configs["post_crta"]["sw_timing"]["min_ms"] = 10.0
    with pytest.raises(ValueError, match="min_ms"):
        build_simulation_inputs(graph)
