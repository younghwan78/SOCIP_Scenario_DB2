from __future__ import annotations

from scenario_db.sim.constants import REFERENCE_FPS, REFERENCE_VOLTAGE_MV


def calc_active_power_mw(
    *,
    unit_power_mw_mp: float,
    resolution_mp: float,
    voltage_mv: float,
    fps: float,
) -> float:
    """Power = unit_power * MP * (V / 710mV)^2 * (fps / 30)."""

    if unit_power_mw_mp <= 0 or resolution_mp <= 0 or voltage_mv <= 0 or fps <= 0:
        return 0.0
    v_scale = (voltage_mv / REFERENCE_VOLTAGE_MV) ** 2
    fps_scale = fps / REFERENCE_FPS
    return unit_power_mw_mp * resolution_mp * v_scale * fps_scale

