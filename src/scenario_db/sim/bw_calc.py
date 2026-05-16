from __future__ import annotations

from scenario_db.sim.constants import (
    BPP_DEFAULT,
    BPP_MAP,
    BW_POWER_COEFF_DEFAULT,
    PMIC_EFFICIENCY_DEFAULT,
    VBAT_DEFAULT,
)
from scenario_db.sim.models import PortBWResult, PortTransferSpec, PortType


def calc_port_bw(
    spec: PortTransferSpec,
    *,
    fps: float,
    bw_power_coeff: float = BW_POWER_COEFF_DEFAULT,
    vbat: float = VBAT_DEFAULT,
    pmic_efficiency: float = PMIC_EFFICIENCY_DEFAULT,
) -> PortBWResult:
    """Calculate DMA bandwidth and BW-induced power for one port."""

    direction = _direction(spec.port_type)
    if direction == "otf" or spec.width <= 0 or spec.height <= 0:
        return PortBWResult(
            node_id=spec.node_id,
            ip_ref=spec.ip_ref,
            hw_name=spec.hw_name,
            port=spec.port,
            direction=direction,
            width=spec.width,
            height=spec.height,
            size_mp=_size_mp(spec.width, spec.height),
            bw_mbs=0.0,
            bw_power_mw=0.0,
            bw_power_ma=0.0,
            format=spec.format,
            bitwidth=spec.bitwidth,
            compression=spec.compression,
            llc_enabled=spec.llc_enabled,
        )

    bpp = BPP_MAP.get((spec.format or "").upper(), BPP_DEFAULT)
    comp_ratio = effective_comp_ratio(spec)
    llc_weight = spec.llc_weight if spec.llc_enabled else 1.0
    bw_mbs = _bw_mbs(spec, fps=fps, bpp=bpp, comp_ratio=comp_ratio)
    bw_power_mw = bw_mbs * bw_power_coeff / 1000.0 * llc_weight
    bw_power_ma = (
        bw_power_mw / vbat / pmic_efficiency
        if vbat > 0 and pmic_efficiency > 0
        else 0.0
    )

    return PortBWResult(
        node_id=spec.node_id,
        ip_ref=spec.ip_ref,
        hw_name=spec.hw_name,
        port=spec.port,
        direction=direction,
        width=spec.width,
        height=spec.height,
        size_mp=_size_mp(spec.width, spec.height),
        bw_mbs=bw_mbs,
        bw_mbs_best=_optional_bw(spec, fps, bpp, spec.comp_ratio_min),
        bw_mbs_worst=_optional_bw(spec, fps, bpp, spec.comp_ratio_max),
        bw_power_mw=bw_power_mw,
        bw_power_ma=bw_power_ma,
        format=spec.format,
        bitwidth=spec.bitwidth,
        compression=spec.compression,
        llc_enabled=spec.llc_enabled,
    )


def _bw_mbs(
    spec: PortTransferSpec,
    *,
    fps: float,
    bpp: float,
    comp_ratio: float,
) -> float:
    return (
        comp_ratio
        * fps
        * spec.width
        * spec.height
        * (spec.bitwidth / 8.0)
        * bpp
        * spec.r_w_rate
        / 1e6
    )


def _optional_bw(
    spec: PortTransferSpec,
    fps: float,
    bpp: float,
    comp_ratio: float | None,
) -> float | None:
    if comp_ratio is None or not compression_enabled(spec.compression):
        return None
    return _bw_mbs(spec, fps=fps, bpp=bpp, comp_ratio=comp_ratio)


def effective_comp_ratio(spec: PortTransferSpec) -> float:
    return spec.comp_ratio if compression_enabled(spec.compression) else 1.0


def compression_enabled(compression: str | None) -> bool:
    normalized = str(compression or "").strip().lower()
    return normalized not in {"", "none", "no", "false", "off", "disable", "disabled", "comp_off"}


def _size_mp(width: int, height: int) -> float:
    return width * height / 1e6 if width > 0 and height > 0 else 0.0


def _direction(port_type: PortType) -> str:
    if port_type == PortType.DMA_READ:
        return "read"
    if port_type == PortType.DMA_WRITE:
        return "write"
    return "otf"
