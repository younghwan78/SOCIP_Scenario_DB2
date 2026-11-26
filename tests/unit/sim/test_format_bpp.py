"""R-5b-1: one bytes-per-pixel lookup (steady BW, debug trace, event jobs) and the GPU / SW-timed buffer DMA."""

import pytest

from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.bw_calc import calc_port_bw
from scenario_db.sim.constants import format_bpp_factor
from scenario_db.sim.jobs import _bytes_per_px
from scenario_db.sim.models import PortTransferSpec, PortType
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

GAME = "uc-game-play-e2600"


@pytest.mark.parametrize(("fmt", "bitwidth", "bytes_px", "basis"), [
    ("RGBA8888", 8, 4.0, "packed"),
    ("RGBA1010102", 10, 4.0, "packed"),        # a packed 32-bit pixel, not 4 x 10 / 8
    ("NV12", 8, 1.5, "exact"),
    ("YUV420_10BIT", 16, 3.0, "exact"),
    ("YUV422_10BIT", 10, 2.5, "exact"),
    ("RAW_BAYER_16", 16, 2.0, "prefix:RAW"),
    ("SOMETHING", 8, 1.0, "default"),
])
def test_one_lookup_gives_the_bytes_per_pixel(fmt, bitwidth, bytes_px, basis):
    factor, how = format_bpp_factor(fmt, bitwidth)
    assert how == basis and factor * bitwidth / 8 == pytest.approx(bytes_px)
    assert _bytes_per_px(fmt, bitwidth) == pytest.approx(bytes_px)          # event jobs use the same lookup


def test_steady_bw_of_an_fhd_rgba_framebuffer():
    spec = PortTransferSpec(node_id="gpu", ip_ref="ip-gpu", hw_name="GPU", port="FB", port_type=PortType.DMA_WRITE,
                            width=1920, height=1080, format="RGBA8888", bitwidth=8)
    assert calc_port_bw(spec, fps=120).bw_mbs == pytest.approx(1920 * 1080 * 4 * 120 / 1e6)


def _ports(variant, scenario=GAME):
    inputs = build_simulation_inputs(_exynos2600_generated_graph(scenario, variant), None)
    return {(p.node_id, p.port): p for p in inputs.port_transfers}, inputs.warnings


def test_the_m2m_upscale_path_has_its_buffers():
    ports, _ = _ports("game-fhd-60fps-m2m-upscale")
    assert (ports["gpu", "GPU_M2M_BUF_WDMA"].width, ports["gpu", "GPU_M2M_BUF_WDMA"].height) == (2560, 1440)
    assert (ports["dpu", "M2M_DPU_BUF_RDMA"].width, ports["dpu", "M2M_DPU_BUF_RDMA"].height) == (1440, 3120)
    assert {("m2m_scaler", "GPU_M2M_BUF_RDMA"), ("m2m_scaler", "M2M_DPU_BUF_WDMA")} <= set(ports)


def test_a_sw_timed_gpu_still_writes_its_buffer():
    ports, _ = _ports("game-fhd-60fps-gpu-heavy-overlay")       # SurfaceFlinger GPU fallback: a sw_timing task
    assert ("gpu", "GPU_DPU_BUF_WDMA") in ports and ("dpu", "GPU_DPU_BUF_RDMA") in ports


def test_a_buffer_without_a_size_is_reported_not_silently_dropped():
    graph = _exynos2600_generated_graph(GAME, "game-fhd-60fps-m2m-upscale")
    sim = graph.variant.node_configs["gpu"]["sim"]
    sim.pop("width"), sim.pop("height")                 # no anchor, no design resolution, no producer surface
    inputs = build_simulation_inputs(graph, None)
    assert any(w.startswith("GPU_M2M_BUF: no size") for w in inputs.warnings)
    assert not any(p.port.startswith("GPU_M2M_BUF") for p in inputs.port_transfers)


def test_an_unknown_pixel_format_is_reported():
    graph = _exynos2600_generated_graph(GAME, "game-fhd-60fps-sdr")
    graph.variant.buffer_overrides = {"GPU_DPU_BUF": {"format": "XYZ_UNKNOWN"}}
    inputs = build_simulation_inputs(graph, None)
    assert any("XYZ_UNKNOWN" in w and "bytes-per-pixel" in w for w in inputs.warnings)


def test_a_sized_buffer_ignores_the_producer_surface():
    graph = _exynos2600_generated_graph(GAME, "game-fhd-60fps-sdr")
    graph.variant.node_configs["gpu"]["sim"].update(width=640, height=480)
    ports, _ = _ports_of(graph)
    assert (ports["gpu", "GPU_DPU_BUF_WDMA"].width, ports["gpu", "GPU_DPU_BUF_WDMA"].height) == (1920, 1080)


def _ports_of(graph, config=None):
    inputs = build_simulation_inputs(graph, config)
    return {(p.node_id, p.port): p for p in inputs.port_transfers}, inputs.warnings


YT = ("uc-vid-youtube-e2600", "yt-1080p30-av1-gpu-overlay")


def test_a_sw_timed_bitstream_moves_at_its_bitrate():
    ports, _ = _ports(YT[1], YT[0])
    es = ports["sw_demux", "NET_ES_BUF_WDMA"]
    assert es.bitrate_mbps is not None and es.width == 0
    assert calc_port_bw(es, fps=30).bw_mbs == pytest.approx(es.bitrate_mbps / 8)


def test_a_sw_timed_bitstream_without_a_bitrate_is_left_out():
    graph = _exynos2600_generated_graph(*YT)
    graph.variant.design_conditions = {k: v for k, v in graph.variant.design_conditions.items() if k != "bitrate_mbps"}
    for cfg in graph.variant.node_configs.values():
        if isinstance(cfg.get("sim"), dict):
            cfg["sim"].pop("bitrate_mbps", None)
    ports, warnings = _ports_of(graph)
    assert ("sw_demux", "NET_ES_BUF_WDMA") not in ports and any("has no bitrate_mbps" in w for w in warnings)


def test_a_sw_timed_node_keeps_its_own_rate():
    from scenario_db.sim.models import SimulationRunConfig
    from scenario_db.sim.runner import run_simulation

    graph = _exynos2600_generated_graph(*YT)
    own = float(graph.variant.node_configs["gpu"]["sim"]["fps"])
    bw = {f: {(d.node_id, d.port): d.bw_mbs for d in run_simulation(build_simulation_inputs(
        _exynos2600_generated_graph(*YT), SimulationRunConfig(fps=f))).dma_breakdown} for f in (own, 2 * own)}
    key = next(k for k in bw[own] if k[0] == "gpu")
    assert bw[2 * own][key] == pytest.approx(bw[own][key])


def test_the_bpp_rule_is_in_the_params_hash_only_where_it_moves():
    from scenario_db.sim import runner
    from scenario_db.sim.constants import bpp_rule_moves

    assert bpp_rule_moves("RGBA8888") and bpp_rule_moves("YUV422_10BIT", 10)
    assert not bpp_rule_moves("NV12") and not bpp_rule_moves("RAW_BAYER_16", 16) and not bpp_rule_moves("BITSTREAM")
    game = build_simulation_inputs(_exynos2600_generated_graph(GAME, "game-fhd-120fps-sdr"), None)
    plain = build_simulation_inputs(_exynos2600_generated_graph("uc-vid-youtube-e2600", "yt-1080p30-h264-sdr"), None)
    assert "bpp_rule" in _payload(runner, game) and "bpp_rule" not in _payload(runner, plain)


def _payload(runner, inputs):
    import json

    seen = {}
    real = json.dumps

    def spy(obj, *a, **k):
        seen.update(obj)
        return real(obj, *a, **k)

    runner.json.dumps = spy
    try:
        runner.params_hash(inputs)
    finally:
        runner.json.dumps = real
    return seen
