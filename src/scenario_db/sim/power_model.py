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
        clock_gating_eff: float | None = None,
        power_gating_eff: float | None = None,
        leakage_mw: float | None = None,
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
        clock_gating_eff: float | None = None,
        power_gating_eff: float | None = None,
        leakage_mw: float | None = None,
    ) -> float:
        # v1 has no clock / gating / leakage terms: those arguments are ignored.
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


# Static power exponent: leakage_mw is characterised at the reference voltage.
IP_LEAK_EXPONENT = 2.5


def busy_share(set_clock_mhz: float | None, ref_clock_mhz: float | None) -> float:
    """Share of time the IP is busy when clocked at f_set for work that needs f_ref."""
    if not set_clock_mhz or not ref_clock_mhz or set_clock_mhz <= 0 or ref_clock_mhz <= 0:
        return 1.0
    return min(1.0, ref_clock_mhz / set_clock_mhz)


def clock_factor(fraction: float | None, set_clock_mhz: float | None, ref_clock_mhz: float | None,
                 clock_gating_eff: float | None = None) -> float:
    """(1 - a) + a * r * [busy + idle * (1 - cg)], r = f_set / f_ref, busy = min(1, 1/r)."""
    if not fraction or not set_clock_mhz or not ref_clock_mhz or ref_clock_mhz <= 0:
        return 1.0
    ratio = set_clock_mhz / ref_clock_mhz
    busy = busy_share(set_clock_mhz, ref_clock_mhz)
    gated = clock_gating_eff or 0.0
    return (1.0 - fraction) + fraction * ratio * (busy + (1.0 - busy) * (1.0 - gated))


def leakage_power_mw(leakage_mw: float | None, voltage_mv: float, ref_voltage_mv: float,
                     power_gating_eff: float | None, busy: float) -> float:
    """leak(V) * (1 - pg * idle): power gating removes leakage while idle."""
    if not leakage_mw or voltage_mv <= 0 or ref_voltage_mv <= 0:
        return 0.0
    return leakage_mw * (voltage_mv / ref_voltage_mv) ** IP_LEAK_EXPONENT * (1.0 - (power_gating_eff or 0.0) * (1.0 - busy))


@dataclass(frozen=True)
class V2VfClockModel(V1VfpsModel):
    """v1 plus a set-clock term and (optional) gating-aware leakage.

    IP: P = P_v1 · [(1 - a) + a · r · (busy + idle · (1 - cg))] + leak(V) · (1 - pg · idle)
        r = f_set / f_ref, busy = min(1, 1/r), idle = 1 - busy

    - ``P_v1`` = unit_power · MP · (V / ref_V)² · (fps / ref_fps): the work
      done per frame at the resolved voltage (unchanged physics).
    - ``f_ref``: the clock the IP physically needs — throughput (pixels·fps /
      util-cap / ppc) or a physical lower bound (sensor ingress, v-valid
      streaming, SW-stage budget), whichever is higher; the operating point
      ``unit_power_mw_mp`` stands for.
    - ``a`` (``clock_power_fraction``): share of that power that scales with
      the set clock instead of the work. Per IP/mode in the catalog sim block,
      otherwise ``power_model_params.ip_clock_power_fraction``, otherwise 0.
    - ``cg`` / ``pg`` (``clock_gating_eff`` / ``power_gating_eff``): how much
      of the clock / leakage is removed while the IP idles (perfetto gating
      ratios). ``leakage_mw``: static power at ref_V (x (V/ref_V)^2.5).

    This lets "run fast then gate" and "run at the lowest clock that fits"
    be compared with one formula. With a = 0, cg = pg = 0 and no leakage the
    result equals v1 exactly; cg = 0 is the previous v2 behaviour.
    """

    model_id: str = "v2-vf"
    version: str = "1.1"
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
        clock_gating_eff: float | None = None,
    ) -> float:
        return clock_factor(self.applied_clock_power_fraction(clock_power_fraction), set_clock_mhz,
                            ref_clock_mhz, clock_gating_eff)

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
        clock_gating_eff: float | None = None,
        power_gating_eff: float | None = None,
        leakage_mw: float | None = None,
    ) -> float:
        base = super().ip_active_power_mw(
            unit_power_mw_mp=unit_power_mw_mp,
            resolution_mp=resolution_mp,
            voltage_mv=voltage_mv,
            fps=fps,
        )
        dynamic = base * self.clock_factor(
            set_clock_mhz=set_clock_mhz,
            ref_clock_mhz=ref_clock_mhz,
            clock_power_fraction=clock_power_fraction,
            clock_gating_eff=clock_gating_eff,
        )
        leak = leakage_power_mw(leakage_mw, voltage_mv, self.ref_voltage_mv, power_gating_eff,
                                busy_share(set_clock_mhz, ref_clock_mhz))
        return dynamic + leak


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
