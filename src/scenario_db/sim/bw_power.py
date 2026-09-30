"""Pluggable BW-induced (memory) power models.

The runner turns each DMA port's bandwidth into memory power through a
``BwPowerModel`` and then folds the per-port results into one memory-rail
number through ``aggregate_power_mw``. Splitting the two steps is the hook a
later MIF-level / residual model needs: it can override the aggregate (total
BW -> minimum MIF level -> rail power) without touching the runner or the
per-port DMA accounting.

Registered models (``BW_POWER_MODELS``):

- ``legacy-coeff``: today's formula, bit-exact.
  ``P = bw_mbs * bw_power_coeff / 1000 * llc_weight``.
- ``linear-per-gbps``: the "N mW per 1 GB/s" rule of thumb, with the unit
  spelled out (1 GB/s = 1000 MB/s).
  ``P = (bw_mbs / 1000) * mw_per_gbps * llc_factor``.

- ``mif-linear``: ``base(MIF level) + e_rd * RD + e_wr * WR`` with the MIF
  level from the scenario QoS lock / governor; coefficients fitted per SoC
  from measurements (``sim/bw_fit.py``).

Numerically the first two are the same linear map (coeff == mw_per_gbps);
``legacy-coeff`` exists so existing runs keep the exact floating-point
evaluation order.

When no BW model is selected the engine keeps using
``PowerModel.memory_transfer_power_mw`` (default configuration is unchanged).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

# Rule-of-thumb default when a linear model is selected without a coefficient.
BW_MW_PER_GBPS_DEFAULT = 50.0
MBS_PER_GBPS = 1000.0


@dataclass(frozen=True)
class BwPowerContext:
    """Run-level facts a model may need beyond one port (extensible)."""

    memory_rail: str = "MIF"
    total_bw_mbs: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BwPowerModel(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def version(self) -> str: ...

    def port_power_mw(
        self,
        *,
        bw_mbs: float,
        direction: str,
        llc_enabled: bool,
        llc_weight: float,
        context: BwPowerContext | None = None,
    ) -> float: ...

    def aggregate_power_mw(
        self,
        port_power_mw: Sequence[float],
        *,
        context: BwPowerContext | None = None,
    ) -> float:
        """Memory-rail power from all per-port results (default: their sum)."""
        ...

    def formula(self) -> str: ...

    def describe(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LegacyCoeffBwModel:
    """``bw_mbs * coeff / 1000 * llc_weight`` - identical to the pre-registry code."""

    bw_power_coeff: float
    model_id: str = "legacy-coeff"
    version: str = "1.0"

    def port_power_mw(
        self,
        *,
        bw_mbs: float,
        direction: str,
        llc_enabled: bool,
        llc_weight: float,
        context: BwPowerContext | None = None,
    ) -> float:
        if bw_mbs <= 0:
            return 0.0
        return bw_mbs * self.bw_power_coeff / 1000.0 * llc_weight

    def aggregate_power_mw(
        self,
        port_power_mw: Sequence[float],
        *,
        context: BwPowerContext | None = None,
    ) -> float:
        return sum(port_power_mw)

    def formula(self) -> str:
        return "bw_mbs * bw_power_coeff / 1000 * llc_weight"

    def describe(self) -> dict[str, Any]:
        return {"id": self.model_id, "version": self.version, "bw_power_coeff": self.bw_power_coeff}


@dataclass(frozen=True)
class LinearPerGbpsBwModel:
    """``P = BW[GB/s] * mw_per_gbps * llc_factor`` (GB/s = 1000 MB/s).

    ``llc_hit_scale`` scales how much of the LLC saving (``1 - llc_weight``)
    is credited; 1.0 keeps ``llc_factor == llc_weight``.
    """

    mw_per_gbps: float = BW_MW_PER_GBPS_DEFAULT
    llc_hit_scale: float = 1.0
    model_id: str = "linear-per-gbps"
    version: str = "1.0"

    def _llc_factor(self, llc_weight: float) -> float:
        if self.llc_hit_scale == 1.0:
            return llc_weight
        return 1.0 - (1.0 - llc_weight) * self.llc_hit_scale

    def port_power_mw(
        self,
        *,
        bw_mbs: float,
        direction: str,
        llc_enabled: bool,
        llc_weight: float,
        context: BwPowerContext | None = None,
    ) -> float:
        if bw_mbs <= 0:
            return 0.0
        return bw_mbs / MBS_PER_GBPS * self.mw_per_gbps * self._llc_factor(llc_weight)

    def aggregate_power_mw(
        self,
        port_power_mw: Sequence[float],
        *,
        context: BwPowerContext | None = None,
    ) -> float:
        return sum(port_power_mw)

    def formula(self) -> str:
        return "(bw_mbs / 1000) * mw_per_gbps * llc_factor"

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.model_id,
            "version": self.version,
            "mw_per_gbps": self.mw_per_gbps,
            "llc_hit_scale": self.llc_hit_scale,
        }


@dataclass(frozen=True)
class MifLinearBwModel:
    """``P_mem = base(MIF level) + e_rd * RD + e_wr * WR`` (GB/s; fitted per SoC).

    - Per port: ``e_dir * bw / 1000 * llc_factor`` (DRAM energy of that traffic).
    - Aggregate: port energy + unmodelled masters' energy + ``base_mw`` of the
      MIF level, where level = max(QoS lock of the scenario's DVFS scenario,
      lowest level whose ``capacity x governor_util`` covers DRAM traffic).
    The coefficients come from ``sim/bw_fit.py`` over measured scenarios.
    """

    e_read: float
    e_write: float
    opps: tuple[tuple[float, float, float | None], ...] = ()   # (mhz, base_mw, capacity_mbs)
    governor_util: float = 0.6
    qos_lock: tuple[tuple[str, float], ...] = ()
    other_masters_mbs: float = 0.0
    llc_hit_scale: float = 1.0
    model_id: str = "mif-linear"
    version: str = "1.0"

    def _llc_factor(self, llc_weight: float) -> float:
        return 1.0 - (1.0 - llc_weight) * self.llc_hit_scale

    def port_power_mw(self, *, bw_mbs: float, direction: str, llc_enabled: bool, llc_weight: float,
                      context: BwPowerContext | None = None) -> float:
        if bw_mbs <= 0:
            return 0.0
        e = self.e_write if direction == "write" else self.e_read
        return bw_mbs / MBS_PER_GBPS * e * self._llc_factor(llc_weight)

    def mif_state(self, context: BwPowerContext | None) -> dict[str, Any]:
        extra = context.extra if context else {}
        dram = float(extra.get("dram_mbs", context.total_bw_mbs if context and context.total_bw_mbs else 0.0))
        load = dram + self.other_masters_mbs
        lock = dict(self.qos_lock).get(str(extra.get("dvfs_sn") or ""), 0.0)
        level = None
        reason = "governor"
        for mhz, base_mw, capacity in self.opps:
            if capacity is not None and capacity * self.governor_util < load:
                continue
            level = (mhz, base_mw, capacity)
            break
        if level is None and self.opps:
            level, reason = self.opps[-1], "saturated"
        if level is not None and lock > level[0]:
            level = next((o for o in self.opps if o[0] >= lock - 1e-9), self.opps[-1])
            reason = "qos_lock"
        return {
            "mif_mhz": level[0] if level else None,
            "base_mw": level[1] if level else 0.0,
            "capacity_mbs": level[2] if level else None,
            "reason": reason if level else "no_levels",
            "dram_mbs": round(dram, 3),
            "other_masters_mbs": self.other_masters_mbs,
            "load_mbs": round(load, 3),
            "qos_lock_mhz": lock or None,
            "utilization": round(load / level[2], 4) if level and level[2] else None,
            "other_masters_mw": round(self.other_masters_mbs / MBS_PER_GBPS * self.e_read, 6),
        }

    def aggregate_power_mw(self, port_power_mw: Sequence[float], *, context: BwPowerContext | None = None) -> float:
        state = self.mif_state(context)
        return sum(port_power_mw) + state["other_masters_mw"] + state["base_mw"]

    def formula(self) -> str:
        return "base(MIF level) + e_rd * RD[GB/s] + e_wr * WR[GB/s] (llc-adjusted)"

    def describe(self) -> dict[str, Any]:
        return {"id": self.model_id, "version": self.version, "e_read_mw_per_gbps": self.e_read,
                "e_write_mw_per_gbps": self.e_write, "mif_levels": len(self.opps),
                "governor_util": self.governor_util, "other_masters_mbs": self.other_masters_mbs}


@dataclass(frozen=True)
class BwPowerSettings:
    """Inputs a registered factory may use to build its model."""

    bw_power_coeff: float
    mw_per_gbps: float | None = None
    llc_hit_scale: float = 1.0
    params: Any = None   # BwPowerParams, for models with more than a coefficient


def _mif_linear(settings: BwPowerSettings) -> MifLinearBwModel:
    bw = settings.params
    default = BW_MW_PER_GBPS_DEFAULT if settings.mw_per_gbps is None else settings.mw_per_gbps
    if bw is None:
        return MifLinearBwModel(e_read=default, e_write=default)
    return MifLinearBwModel(
        e_read=bw.e_read_mw_per_gbps if bw.e_read_mw_per_gbps is not None else default,
        e_write=bw.e_write_mw_per_gbps if bw.e_write_mw_per_gbps is not None else default,
        opps=tuple((o.mhz, o.base_mw, o.capacity_mbs) for o in bw.mif_opps),
        governor_util=bw.governor_util,
        qos_lock=tuple(sorted(bw.qos_lock_mhz_by_dvfs_sn.items())),
        other_masters_mbs=bw.other_masters_mbs,
        llc_hit_scale=settings.llc_hit_scale,
    )


BwModelFactory = Callable[[BwPowerSettings], BwPowerModel]

BW_POWER_MODELS: dict[str, BwModelFactory] = {
    "legacy-coeff": lambda s: LegacyCoeffBwModel(bw_power_coeff=s.bw_power_coeff),
    "linear-per-gbps": lambda s: LinearPerGbpsBwModel(
        mw_per_gbps=BW_MW_PER_GBPS_DEFAULT if s.mw_per_gbps is None else s.mw_per_gbps,
        llc_hit_scale=s.llc_hit_scale,
    ),
    "mif-linear": _mif_linear,
}


def resolve_bw_power_model(model_id: str, settings: BwPowerSettings) -> BwPowerModel:
    factory = BW_POWER_MODELS.get(model_id)
    if factory is None:
        raise ValueError(
            f"Unknown BW power model '{model_id}' (registered: {sorted(BW_POWER_MODELS)})"
        )
    return factory(settings)


def bw_model_from_config(config: Any) -> BwPowerModel | None:
    """The BW model selected by a ``SimulationRunConfig``, or None (built-in path)."""
    from scenario_db.sim.power_params import effective_power_params

    params = effective_power_params(config)
    model_id = getattr(config, "bw_power_model", None) or (params.bw_model if params else None)
    if not model_id:
        return None
    mw_per_gbps = getattr(config, "bw_power_mw_per_gbps", None)
    if mw_per_gbps is None and params is not None:
        mw_per_gbps = params.bw.mw_per_gbps
    return resolve_bw_power_model(
        model_id,
        BwPowerSettings(
            bw_power_coeff=config.bw_power_coeff,
            mw_per_gbps=mw_per_gbps,
            llc_hit_scale=params.bw.llc_hit_scale if params else 1.0,
            params=params.bw if params else None,
        ),
    )
