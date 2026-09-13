from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, read, graph_from_fixture  # noqa: E402
from verify_priority_recording import assess_priority  # noqa: E402
from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim.adapter import build_simulation_inputs  # noqa: E402
from scenario_db.sim.bw_calc import calc_port_bw  # noqa: E402
from scenario_db.sim.models import PortTransferSpec, PortType, SimulationRunConfig  # noqa: E402
from scenario_db.sim.runner import run_simulation  # noqa: E402
from scenario_db.sim.timing_profiles import timing_profiles  # noqa: E402


@pytest.fixture(scope="module")
def graph_factory():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"], hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    def build(id, scenario="uc-camera-recording"):
        return graph_from_fixture(read(FIXTURE / "02_definition" / (scenario + ".yaml")), id, catalog)
    return build


def test_bitstream_bandwidth_is_bitrate_not_image_pixels_or_fps():
    spec = PortTransferSpec(node_id="writer", hw_name="CPU", port="READ", port_type=PortType.DMA_READ, width=0, height=0, bitrate_mbps=1000)
    assert calc_port_bw(spec, fps=30).bw_mbs == 125
    assert calc_port_bw(spec, fps=60).bw_mbs == 125
    assert calc_port_bw(spec.model_copy(update={"bitrate_mbps": 2000}), fps=30).bw_mbs == 250


def test_apv_uses_dedicated_hw_and_writer_scales_with_bitrate(graph_factory):
    graph = graph_factory("cam-rec-apv-uhd30-422-sdr", "uc-camera-recording-apv")
    assert all("mfc" not in n["ip_ref"] for n in graph.pipeline_nodes)
    first = timing_profiles(graph)["mpeg_writer"]["mean_ms"]
    graph.variant.design_conditions["record_bitrate_mbps"] *= 2
    assert timing_profiles(graph)["mpeg_writer"]["mean_ms"] == first * 2
    inputs = build_simulation_inputs(graph)
    ports = [p for p in inputs.port_transfers if p.bitrate_mbps]
    assert len(ports) == 4  # encode write, writer read/write, storage read
    assert all(p.bitrate_mbps == 2000 for p in ports)


def test_dual_preserves_two_ingress_sizes_and_shared_resources(graph_factory):
    inputs = build_simulation_inputs(graph_factory("cam-rec-pip-uhd30"))
    workloads = {w.node_id:w for w in inputs.workloads}
    assert (workloads["csis"].width, workloads["csis"].height) == (4080, 2296)
    assert (workloads["front_csis"].width, workloads["front_csis"].height) == (4000, 3000)
    tasks = {t["id"]:t for t in inputs.timeline_tasks}
    assert tasks["csis"]["resource_id"] == tasks["front_csis"]["resource_id"]
    assert tasks["pre_me_rta"]["resource_id"] == tasks["front_pre_me_rta"]["resource_id"]
    assert any(p.node_id=="front_mtnr" and "PREV" in p.port for p in inputs.port_transfers)


def test_8k30_user_sensor_size_is_not_automatically_cropped(graph_factory):
    inputs = build_simulation_inputs(graph_factory("cam-rec-r1-8k30-sdr"))
    csis = next(w for w in inputs.workloads if w.node_id=="csis")
    assert (csis.width, csis.height) == (7680, 4620)
    assert next(p for p in inputs.port_transfers if p.node_id=="mlsc" and p.port=="MLSC_W_GLPG0_Y").height == 4620


def test_fhd240_sensor120_cannot_be_accepted_by_raising_clock(graph_factory):
    graph = graph_factory("cam-rec-r1-fhd240")
    inputs = build_simulation_inputs(graph, SimulationRunConfig(timeline_frame_count=8))
    check = assess_priority(graph, inputs, run_simulation(inputs))
    assert not check["accepted"]
    assert "sensor_output_cadence_mismatch" in check["reasons"]


def test_portrait_segmentation_and_blend_gate_encoding(graph_factory):
    graph = graph_factory("cam-rec-r1-uhd30-portrait")
    inputs = build_simulation_inputs(graph)
    assert {"vps_seg", "portrait_blend"} <= {t["id"] for t in inputs.timeline_tasks}
    assert any(e["from"]=="portrait_blend" and e["to"]=="mfc_enc" for e in inputs.timeline_edges)
    assert not any(e["from"]=="mcsc" and e["to"]=="mfc_enc" for e in inputs.timeline_edges)


def test_assumed_clock_grid_is_applied_without_dvfs_table(graph_factory):
    from scenario_db.sim.dvfs_resolver import DvfsResolver
    graph = graph_factory("cam-rec-r1-fhd30-portrait")
    graph.variant.node_configs["vps_seg"].setdefault("sim", {})["manual_clock_mhz"] = 1000
    inputs = build_simulation_inputs(graph)
    resolved = DvfsResolver({}).resolve(inputs.workloads)
    assert resolved["vps_seg"].set_clock_mhz >= 1000
    assert resolved["vps_od"].set_clock_mhz == resolved["vps_seg"].set_clock_mhz
    vps = next(w for w in inputs.workloads if w.node_id=="vps_seg")
    vps.sim_params.max_clock_mhz = 900
    assert not DvfsResolver({}).resolve(inputs.workloads)["vps_seg"].feasible


def test_bitstream_trace_explains_bitrate_accounting():
    from scenario_db.sim.debug_trace import _dma_traces
    spec = PortTransferSpec(node_id="writer", hw_name="CPU", port="READ", port_type=PortType.DMA_READ, width=0, height=0, bitrate_mbps=1000)
    result = calc_port_bw(spec, fps=30)
    trace = _dma_traces([spec], dma_breakdown=[result], fps=30, bw_power_coeff=80, vbat=3.8, pmic_efficiency=.9)[0]
    assert trace["bw_formula"] == "bitrate_mbps / 8 * r_w_rate"
    assert trace["inputs"]["bitrate_mbps"] == 1000
    assert trace["result"]["bw_mbs"] == 125
