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

Numerically the two are the same linear map (coeff == mw_per_gbps);
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
class BwPowerSettings:
    """Inputs a registered factory may use to build its model."""

    bw_power_coeff: float
    mw_per_gbps: float | None = None
    llc_hit_scale: float = 1.0


BwModelFactory = Callable[[BwPowerSettings], BwPowerModel]

BW_POWER_MODELS: dict[str, BwModelFactory] = {
    "legacy-coeff": lambda s: LegacyCoeffBwModel(bw_power_coeff=s.bw_power_coeff),
    "linear-per-gbps": lambda s: LinearPerGbpsBwModel(
        mw_per_gbps=BW_MW_PER_GBPS_DEFAULT if s.mw_per_gbps is None else s.mw_per_gbps,
        llc_hit_scale=s.llc_hit_scale,
    ),
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
    model_id = getattr(config, "bw_power_model", None)
    if not model_id:
        return None
    return resolve_bw_power_model(
        model_id,
        BwPowerSettings(
            bw_power_coeff=config.bw_power_coeff,
            mw_per_gbps=getattr(config, "bw_power_mw_per_gbps", None),
        ),
    )
