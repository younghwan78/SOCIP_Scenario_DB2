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
    graph.variant.size_overrides = {}
    inputs = build_simulation_inputs(graph, None)
    assert any(w.startswith("GPU_M2M_BUF: no size") for w in inputs.warnings)
    assert not any(p.port.startswith("GPU_M2M_BUF") for p in inputs.port_transfers)


def test_an_unknown_pixel_format_is_reported():
    graph = _exynos2600_generated_graph(GAME, "game-fhd-60fps-sdr")
    graph.variant.buffer_overrides = {"GPU_DPU_BUF": {"format": "XYZ_UNKNOWN"}}
    inputs = build_simulation_inputs(graph, None)
    assert any("XYZ_UNKNOWN" in w and "bytes-per-pixel" in w for w in inputs.warnings)
