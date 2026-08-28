"""Pluggable power models for the simulation engine.

The engine estimates three power buckets — per-IP core power, memory
(BW-driven) power, and CPU/cluster power — through one strategy object, so a
project can swap or calibrate the physics without touching the runner:

- ``ip_active_power_mw``: dynamic power of one IP instance at its resolved
  operating point.
- ``memory_transfer_power_mw``: DRAM/interconnect power induced by one DMA
  port's traffic. The runner attributes the sum to the memory rail
  (``SimulationRunConfig.memory_rail``), not to the initiating IP's rail.
- CPU power has no model yet (SW tasks carry no compute model); the runner
  still emits an empty ``cpu`` bucket so evidence, comparison, and
  calibration schemas are stable when it lands.

Every simulation evidence records ``power_breakdown.model`` (id + version),
so results are attributable to the exact physics that produced them. Register
new implementations (e.g. a C·V²·f + leakage model, or a per-SoC calibrated
wrapper) in ``POWER_MODELS``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scenario_db.sim.power_calc import calc_active_power_mw


class PowerModel(Protocol):
    model_id: str
    version: str

    def ip_active_power_mw(
        self,
        *,
        unit_power_mw_mp: float,
        resolution_mp: float,
        voltage_mv: float,
        fps: float,
    ) -> float: ...

    def memory_transfer_power_mw(
        self,
        *,
        bw_mbs: float,
        bw_power_coeff: float,
        llc_weight: float,
    ) -> float: ...


@dataclass(frozen=True)
class V1VfpsModel:
    """The original ScenarioDB physics, unchanged.

    IP:     P = unit_power_mw_mp · MP · (V / 710mV)² · (fps / 30)
    Memory: P = BW_mbs · bw_power_coeff / 1000 · llc_weight
    """

    model_id: str = "v1-vfps"
    version: str = "1.0"

    def ip_active_power_mw(
        self,
        *,
        unit_power_mw_mp: float,
        resolution_mp: float,
        voltage_mv: float,
        fps: float,
    ) -> float:
        return calc_active_power_mw(
            unit_power_mw_mp=unit_power_mw_mp,
            resolution_mp=resolution_mp,
            voltage_mv=voltage_mv,
            fps=fps,
        )

    def memory_transfer_power_mw(
        self,
        *,
        bw_mbs: float,
        bw_power_coeff: float,
        llc_weight: float,
    ) -> float:
        if bw_mbs <= 0:
            return 0.0
        return bw_mbs * bw_power_coeff / 1000.0 * llc_weight


DEFAULT_POWER_MODEL_ID = "v1-vfps"

POWER_MODELS: dict[str, PowerModel] = {
    "v1-vfps": V1VfpsModel(),
}


def resolve_power_model(model_id: str | None) -> PowerModel:
    effective = model_id or DEFAULT_POWER_MODEL_ID
    model = POWER_MODELS.get(effective)
    if model is None:
        raise ValueError(
            f"Unknown power model '{effective}' (registered: {sorted(POWER_MODELS)})"
        )
    return model
