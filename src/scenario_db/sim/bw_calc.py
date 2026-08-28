from __future__ import annotations

from scenario_db.sim.constants import (
    BPP_DEFAULT,
    BPP_MAP,
    BW_POWER_COEFF_DEFAULT,
    PMIC_EFFICIENCY_DEFAULT,
    VBAT_DEFAULT,
)
from scenario_db.sim.models import PortBWResult, PortTransferSpec, PortType
from scenario_db.sim.power_model import PowerModel, resolve_power_model


BW_MBS_FORMULA = "comp_ratio * fps * width * height * (bitwidth / 8) * format_bpp_factor * r_w_rate / 1e6"


def calc_port_bw(
    spec: PortTransferSpec,
    *,
    fps: float,
    bw_power_coeff: float = BW_POWER_COEFF_DEFAULT,
    vbat: float = VBAT_DEFAULT,
    pmic_efficiency: float = PMIC_EFFICIENCY_DEFAULT,
    power_model: PowerModel | None = None,
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
            comp_ratio=effective_comp_ratio(spec),
            llc_weight=spec.llc_weight if spec.llc_enabled else 1.0,
            r_w_rate=spec.r_w_rate,
            llc_enabled=spec.llc_enabled,
        )

    bpp = BPP_MAP.get((spec.format or "").upper(), BPP_DEFAULT)
    comp_ratio = effective_comp_ratio(spec)
    llc_weight = spec.llc_weight if spec.llc_enabled else 1.0
    bw_mbs = _bw_mbs(spec, fps=fps, bpp=bpp, comp_ratio=comp_ratio)
    model = power_model or resolve_power_model(None)
    bw_power_mw = model.memory_transfer_power_mw(
        bw_mbs=bw_mbs,
        bw_power_coeff=bw_power_coeff,
        llc_weight=llc_weight,
    )
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
        comp_ratio=comp_ratio,
        llc_weight=llc_weight,
        r_w_rate=spec.r_w_rate,
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


_COMPRESSION_OFF_TOKENS = {
    "", "none", "no", "false", "off", "disable", "disabled", "comp_off", "comp_none",
}


def normalize_compression(compression: str | None) -> str | None:
    """Canonical compression mode string, or None for any 'off' spelling.

    Single source of truth for the scattered 'none'/'disable'/'off'/COMP_OFF
    sentinels that previously diverged between sim and view layers.
    """
    text = str(compression or "").strip()
    if text.lower() in _COMPRESSION_OFF_TOKENS:
        return None
    return text


def compression_enabled(compression: str | None) -> bool:
    return normalize_compression(compression) is not None


def resolve_comp_ratio(
    compression: str | None,
    catalog: dict[str, float] | None = None,
    *,
    override: float | None = None,
) -> float:
    """Remaining-BW fraction for a compression mode (1.0 == no reduction).

    Resolution order: OFF/unknown-disabled -> 1.0; explicit override (for
    exploration) -> override; SoC catalog ratio for the mode -> that value;
    otherwise 1.0. This centralises what previously lived ad hoc in
    transfers/chain_templates/level0.
    """
    mode = normalize_compression(compression)
    if mode is None:
        return 1.0
    if override is not None:
        return float(override)
    if catalog:
        ratio = catalog.get(mode)
        if ratio is not None:
            return float(ratio)
    return 1.0


def _size_mp(width: int, height: int) -> float:
    return width * height / 1e6 if width > 0 and height > 0 else 0.0


def _direction(port_type: PortType) -> str:
    if port_type == PortType.DMA_READ:
        return "read"
    if port_type == PortType.DMA_WRITE:
        return "write"
    return "otf"
