from __future__ import annotations

from scenario_db.sim.constants import H_BLANK_MARGIN_DEFAULT


def calc_processing_time_ms(
    *,
    pixels: int | float,
    set_clock_mhz: float,
    ppc: float,
    h_blank_margin: float = H_BLANK_MARGIN_DEFAULT,
) -> float:
    """Calculate pixel-processing time in milliseconds."""

    if pixels <= 0 or set_clock_mhz <= 0 or ppc <= 0:
        return 0.0
    base_s = pixels / (set_clock_mhz * 1e6 * ppc)
    return base_s * (1.0 + h_blank_margin) * 1000.0

