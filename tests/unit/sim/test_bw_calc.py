from __future__ import annotations

import pytest

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
