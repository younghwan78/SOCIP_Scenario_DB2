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

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from scenario_db.sim.constants import REFERENCE_FPS, REFERENCE_VOLTAGE_MV
from scenario_db.sim.power_calc import calc_active_power_mw

if TYPE_CHECKING:
    from scenario_db.models.capability.power_model import PowerModelParams


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
        set_clock_mhz: float | None = None,
        ref_clock_mhz: float | None = None,
        clock_power_fraction: float | None = None,
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

    IP:     P = unit_power_mw_mp · MP · (V / ref_V)² · (fps / ref_fps)
    Memory: P = BW_mbs · bw_power_coeff / 1000 · llc_weight

    ``ref_voltage_mv`` / ``ref_fps`` default to the historical 710 mV / 30 fps
    constants; a ``power_model_params`` document overrides them per SoC
    (``with_params``).
    """

    model_id: str = "v1-vfps"
    version: str = "1.0"
    ref_voltage_mv: float = REFERENCE_VOLTAGE_MV
    ref_fps: float = REFERENCE_FPS

    def with_params(self, params: PowerModelParams) -> V1VfpsModel:
        return replace(
            self,
            ref_voltage_mv=params.ref_voltage_mv or self.ref_voltage_mv,
            ref_fps=params.ref_fps or self.ref_fps,
        )

    def ip_active_power_mw(
        self,
        *,
        unit_power_mw_mp: float,
        resolution_mp: float,
        voltage_mv: float,
        fps: float,
        set_clock_mhz: float | None = None,
        ref_clock_mhz: float | None = None,
        clock_power_fraction: float | None = None,
    ) -> float:
        # v1 has no clock term: set/ref clock and fraction are ignored.
        return calc_active_power_mw(
            unit_power_mw_mp=unit_power_mw_mp,
            resolution_mp=resolution_mp,
            voltage_mv=voltage_mv,
            fps=fps,
            ref_voltage_mv=self.ref_voltage_mv,
            ref_fps=self.ref_fps,
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


@dataclass(frozen=True)
class V2VfClockModel(V1VfpsModel):
    """v1 plus a set-clock term (clock tree / ungated logic).

    IP: P = P_v1 · [(1 - a) + a · f_set / f_ref]

    - ``P_v1`` = unit_power · MP · (V / ref_V)² · (fps / ref_fps): the work
      done per frame at the resolved voltage (unchanged physics).
    - ``f_ref``: the clock the IP physically needs — throughput (pixels·fps /
      util-cap / ppc) or a physical lower bound (sensor ingress, v-valid
      streaming, SW-stage budget), whichever is higher; the operating point
      ``unit_power_mw_mp`` stands for.
    - ``a`` (``clock_power_fraction``): share of that power that scales with
      the set clock instead of the work. Per IP/mode in the catalog sim block,
      otherwise ``power_model_params.ip_clock_power_fraction``, otherwise 0.

    With a = 0, or f_set == f_ref, the result equals v1 exactly. With a > 0 a
    clock set above the need (OTF / DVFS-group alignment, DVFS quantisation,
    overflow guard or other configured / measured overrides) costs power even
    at the same voltage.
    """

    model_id: str = "v2-vf"
    version: str = "1.0"
    default_clock_power_fraction: float = 0.0

    def with_params(self, params: PowerModelParams) -> V2VfClockModel:
        base = super().with_params(params)
        fraction = getattr(params, "ip_clock_power_fraction", None)
        return replace(
            base,
            default_clock_power_fraction=self.default_clock_power_fraction if fraction is None else fraction,
        )

    def applied_clock_power_fraction(self, clock_power_fraction: float | None) -> float:
        return self.default_clock_power_fraction if clock_power_fraction is None else clock_power_fraction

    def clock_factor(
        self,
        *,
        set_clock_mhz: float | None,
        ref_clock_mhz: float | None,
        clock_power_fraction: float | None,
    ) -> float:
        fraction = self.applied_clock_power_fraction(clock_power_fraction)
        if not fraction or not set_clock_mhz or not ref_clock_mhz or ref_clock_mhz <= 0:
            return 1.0
        return (1.0 - fraction) + fraction * (set_clock_mhz / ref_clock_mhz)

    def ip_active_power_mw(
        self,
        *,
        unit_power_mw_mp: float,
        resolution_mp: float,
        voltage_mv: float,
        fps: float,
        set_clock_mhz: float | None = None,
        ref_clock_mhz: float | None = None,
        clock_power_fraction: float | None = None,
    ) -> float:
        base = super().ip_active_power_mw(
            unit_power_mw_mp=unit_power_mw_mp,
            resolution_mp=resolution_mp,
            voltage_mv=voltage_mv,
            fps=fps,
        )
        return base * self.clock_factor(
            set_clock_mhz=set_clock_mhz,
            ref_clock_mhz=ref_clock_mhz,
            clock_power_fraction=clock_power_fraction,
        )


DEFAULT_POWER_MODEL_ID = "v1-vfps"

POWER_MODELS: dict[str, PowerModel] = {
    "v1-vfps": V1VfpsModel(),
    "v2-vf": V2VfClockModel(),
}


def resolve_power_model(
    model_id: str | None,
    params: PowerModelParams | None = None,
) -> PowerModel:
    """Registered model, specialised with ``params`` (reference V/fps) when given."""
    effective = model_id or DEFAULT_POWER_MODEL_ID
    model = POWER_MODELS.get(effective)
    if model is None:
        raise ValueError(
            f"Unknown power model '{effective}' (registered: {sorted(POWER_MODELS)})"
        )
    if params is not None:
        if params.ip_model != model.model_id:
            raise ValueError(
                f"power params '{params.params_ref}' target ip_model '{params.ip_model}' "
                f"but the run uses power_model '{model.model_id}'"
            )
        with_params = getattr(model, "with_params", None)
        if with_params is not None:
            return with_params(params)
    return model
