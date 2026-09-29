from __future__ import annotations

from scenario_db.sim.constants import REFERENCE_FPS, REFERENCE_VOLTAGE_MV


def calc_active_power_mw(
    *,
    unit_power_mw_mp: float,
    resolution_mp: float,
    voltage_mv: float,
    fps: float,
    ref_voltage_mv: float = REFERENCE_VOLTAGE_MV,
    ref_fps: float = REFERENCE_FPS,
) -> float:
    """Power = unit_power * MP * (V / ref_V)^2 * (fps / ref_fps); refs default to 710mV / 30fps."""

    if unit_power_mw_mp <= 0 or resolution_mp <= 0 or voltage_mv <= 0 or fps <= 0:
        return 0.0
    v_scale = (voltage_mv / ref_voltage_mv) ** 2
    fps_scale = fps / ref_fps
    return unit_power_mw_mp * resolution_mp * v_scale * fps_scale

