from __future__ import annotations

import pytest

from scenario_db.sim import bw_calc, debug_trace
from scenario_db.sim.bw_calc import calc_port_bw
from scenario_db.sim.models import PortTransferSpec, PortType


def test_calc_port_bw_dma_write_with_compression():
    result = calc_port_bw(
        PortTransferSpec(
            node_id="isp0",
            ip_ref="ip-isp-v12",
            hw_name="ISP",
            port="WDMA_BE",
            port_type=PortType.DMA_WRITE,
            width=1920,
            height=1080,
            format="NV12",
            bitwidth=8,
            compression="SBWC",
            comp_ratio=0.5,
            comp_ratio_min=0.3,
            comp_ratio_max=0.7,
        ),
        fps=30,
    )

    assert result.direction == "write"
    assert result.width == 1920
    assert result.height == 1080
    assert result.size_mp == pytest.approx(2.0736)
    assert result.bw_mbs == pytest.approx(46.656)
    assert result.bw_mbs_best == pytest.approx(27.9936)
    assert result.bw_mbs_worst == pytest.approx(65.3184)
    assert result.bw_power_mw == pytest.approx(3.73248)
    assert result.comp_ratio == pytest.approx(0.5)
    assert result.llc_weight == pytest.approx(1.0)


def test_calc_port_bw_ignores_comp_ratio_when_compression_is_off():
    result = calc_port_bw(
        PortTransferSpec(
            node_id="mlsc0",
            ip_ref="ip-isp-v12",
            hw_name="MLSC",
            port="MLSC_WDMA0_L0",
            port_type=PortType.DMA_WRITE,
            width=2400,
            height=1350,
            format="YUV420",
            bitwidth=10,
            compression="COMP_OFF",
            comp_ratio=0.5,
            comp_ratio_min=0.3,
            comp_ratio_max=0.7,
        ),
        fps=30,
    )

    assert result.bw_mbs == pytest.approx(182.25)
    assert result.bw_mbs_best is None
    assert result.bw_mbs_worst is None
    assert result.comp_ratio == pytest.approx(1.0)


@pytest.mark.parametrize("fmt", ["YUV420_10BIT", "YUV420_SBWC", "YUV420_SBWCL"])
def test_calc_port_bw_uses_yuv420_bpp_for_yuv420_aliases(fmt):
    result = calc_port_bw(
        PortTransferSpec(
            node_id="mfc0",
            ip_ref="ip-mfc-v12",
            hw_name="MFC",
            port="MFC_WDMA",
            port_type=PortType.DMA_WRITE,
            width=1920,
            height=1080,
            format=fmt,
            bitwidth=10,
            compression="COMP_OFF",
        ),
        fps=30,
    )

    assert result.bw_mbs == pytest.approx(116.64)


def test_calc_port_bw_applies_comp_ratio_to_yuv420_sbwc_alias():
    result = calc_port_bw(
        PortTransferSpec(
            node_id="dpu0",
            ip_ref="ip-dpu-v12",
            hw_name="DPU",
            port="DPU_RDMA",
            port_type=PortType.DMA_READ,
            width=1920,
            height=1080,
            format="YUV420_SBWC",
            bitwidth=8,
            compression="COMP_SBWC_LOSSLESS",
            comp_ratio=0.5,
        ),
        fps=30,
    )

    assert result.bw_mbs == pytest.approx(46.656)
    assert result.comp_ratio == pytest.approx(0.5)


def test_calc_port_bw_otf_returns_zero():
    result = calc_port_bw(
        PortTransferSpec(
            node_id="csis0",
            hw_name="CSIS",
            port="COUTFIFO",
            port_type=PortType.OTF_OUT,
            width=4000,
            height=2252,
        ),
        fps=30,
    )

    assert result.direction == "otf"
    assert result.bw_mbs == 0.0
    assert result.bw_power_mw == 0.0


def test_debug_trace_uses_bw_formula_from_bw_calc():
    assert hasattr(bw_calc, "BW_MBS_FORMULA")
    spec = PortTransferSpec(
        node_id="isp0",
        ip_ref="ip-isp-v12",
        hw_name="ISP",
        port="WDMA_BE",
        port_type=PortType.DMA_WRITE,
        width=1920,
        height=1080,
        format="NV12",
        bitwidth=8,
        compression="SBWC",
        comp_ratio=0.5,
    )
    result = calc_port_bw(spec, fps=30)

    trace = debug_trace._dma_traces(
        [spec],
        dma_breakdown=[result],
        fps=30,
        bw_power_coeff=80,
        vbat=3.8,
        pmic_efficiency=0.9,
    )[0]

    assert trace["formula"] == bw_calc.BW_MBS_FORMULA
    assert trace["bw_formula"] == bw_calc.BW_MBS_FORMULA
